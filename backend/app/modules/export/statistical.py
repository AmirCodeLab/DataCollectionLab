"""Stata `.dta` and SPSS `.sav` — where the file format has opinions.

CSV has no types, no name limits and no opinions; these two have all three, and
`backend/tests/test_statistical_writers.py` records what `pyreadstat` actually
does about each. Four of its answers are load-bearing here:

**The exporter decides the type; the library is never allowed to.** readstat
infers a column's type from the values it holds, and a declared pandas dtype
does not override it — so one unreadable row silently turns a numeric column
into a text one, `100.0` into `"100.0"`, and nothing in the library's return
says so. Same form, same do-file, two exports, two types. Here the storage type
is computed from the **plan** plus one recorded reason, every file is read back
after writing, and a column that did not come back as its declared type is an
exception rather than a surprise six months later.

**Names are ours to shorten.** readstat enforces SPSS's 64-character limit and
not Stata's 32, so it will write a `.dta` that Stata itself refuses — and
`members[i3].age` is not a variable name in either format. Truncation is
therefore deliberate, deterministic, collision-free, and recorded in the
manifest per column: two fields truncating to one name would be a silent merge
of two questions' answers, which is the export mistake of exactly the shape
item 5 is about.

**Variable labels are ours to shorten too**, for the same reason: SPSS truncates
at 256 and Stata's own 80 is not enforced at all.

**And so is the longest string each format can hold.** Reading the bytes rather
than asking the library settles both halves: a `.dta` promotes anything over
2,045 bytes to a `strL` on its own — the type code in `<variable_types>` says
`32768` — so a long answer is genuinely fine there. A `.sav` is not: readstat
wrote 40,000 bytes past SPSS's documented 32,767-byte maximum without a word.
So the limit is enforced here, in **bytes** rather than characters, because both
formats size a string in bytes and 20,000 Arabic characters are 40,000 of them.

**Value labels are unusable**, and that is a finding rather than a choice. A
label keyed by the string code `V000023` is written against `0` in a `.dta` — a
name attached to a value that is not in the data. Our codes are strings by
design (§3.1: the key is the cell's value, exactly), so the resolved name goes
in its own column, exactly as it does in the CSV.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from .cells import ENCRYPTED, Cell
from .plan import Column
from .shape import Table

#: What a column is stored as. There is deliberately **no `datetime`**: a
#: `.dta` and a `.sav` store a moment as a double with no offset, so writing one
#: means either dropping the offset — which changes when something happened — or
#: converting to UTC, which changes the value the file round-trips to. A
#: `datetime` and the `started_at` / `received_at` stamps are therefore written
#: as ISO strings, exactly as `time` already is. A `date` has no offset to lose,
#: so it *is* written as a real date, which is worth having: a Stata user handed
#: a string date has to parse it before they can do anything with it.
type Storage = Literal["numeric", "string", "date"]

#: Stata's limit. SPSS allows 64; the tighter one is used for both so that one
#: export's column names are the same names in either file.
NAME_LIMIT = 32
#: Stata's limit for a variable label. SPSS allows 256 and enforces it.
LABEL_LIMIT = 80
#: Stata's `str#` maximum, in **bytes**. Above it readstat writes a `strL`
#: instead — verified by reading the type code out of the file, not by asking
#: the library — so a long answer is not a problem in a `.dta` at all. Kept as a
#: named constant because it is the threshold the characterisation test asserts.
STATA_STR_LIMIT_BYTES = 2045

#: The longest string each format can hold, in **bytes**, or None for no
#: practical limit. Bytes and not characters: both formats size a string in
#: bytes, and this platform is Swahili and Arabic from the start — 20,000
#: Arabic characters are 40,000 bytes, and a character-counted check would wave
#: them through.
#:
#: `dta` is None because a `strL` holds up to 2 GB. `sav` is SPSS's documented
#: maximum for a string variable. **readstat enforces neither**: it wrote 40,000
#: bytes into a `.sav` without complaint, which is the same shape as its writing
#: a `.dta` variable name Stata refuses — the library implements the format it
#: can and leaves the application's own rules to the caller. So the caller
#: decides, here, rather than producing a file SPSS may not open.
MAX_STRING_BYTES: dict[str, int | None] = {"dta": None, "sav": 32767}
#: 13 mangles Arabic and Swahili silently. Pinned rather than defaulted.
DTA_VERSION = 15

_NUMERIC_COMPONENTS = frozenset({"lat", "lon", "alt", "accuracy", "size"})
_NUMERIC_TYPES = frozenset({"integer", "decimal", "boolean"})
_NUMERIC_META = frozenset({"form_version", "instance_index"})


class ValueTooLong(Exception):
    """A value will not fit the format the caller asked for.

    Refused rather than truncated, and refused rather than written and hoped
    for. Truncating loses an answer to keep a file tidy, which is the failure
    this module exists to prevent; writing it anyway produces a file the target
    application may refuse to open, with nothing said. Neither is a trade this
    exporter gets to make on a customer's behalf.

    It names the formats that *can* hold the value, because that is the useful
    half: CSV, XLSX and Stata all take it, so a refusal here costs an SPSS user
    one flag rather than their data.
    """

    def __init__(self, column: str, found: int, limit: int, fmt: str) -> None:
        works = ", ".join(
            name for name in ("csv", "xlsx", "dta", "sav") if name != fmt
        )
        super().__init__(
            f"`{column}` holds a value of {found:,} bytes and a {fmt} string "
            f"holds at most {limit:,}. It is not truncated to fit — export this "
            f"form as {works} instead, all of which hold it."
        )
        self.column = column
        self.found = found
        self.limit = limit
        self.format = fmt


class TypeChanged(Exception):
    """A column is not the type it was declared as — at either of two moments.

    Before writing: a value that will not go into the column its plan chose,
    which would otherwise be dropped to keep the type tidy. After writing: a
    column that came back as something else, because readstat types a column
    from its values and there is no way to *ask* for numeric — only to write it
    and look.

    Raised rather than warned, in both cases. The whole point of this module is
    that the file's types are a statement the exporter makes and the manifest
    records; a file that lies about its own types is worse than no file. The
    check has already earned itself: an all-null `date` column was silently
    coming back as a **string** column, so an empty date question gave the same
    form two different schemas depending on whether anybody answered it.
    """


@dataclass(frozen=True)
class StatColumn:
    """One column as it appears in a `.dta` or `.sav`."""

    #: The name in the file. May be shortened; `source` is the name the CSV uses.
    name: str
    source: str
    storage: Storage
    #: What the storage would be if nothing in this export forced a change.
    declared_storage: Storage
    #: Why it changed, or None. Recorded per column in the manifest, because a
    #: type that moves between exports of one form is something a do-file author
    #: has to be able to see.
    changed_because: str | None
    label: str | None


def declared_storage(column: Column) -> Storage:
    """The type a column has by virtue of the form, before any data is seen."""
    if column.source == "label":
        return "string"
    if column.source == "count":
        return "numeric"
    if column.source == "meta":
        return "numeric" if (column.field_id or column.name) in _NUMERIC_META else "string"
    if column.component is not None:
        return "numeric" if column.component in _NUMERIC_COMPONENTS else "string"
    if column.data_type in _NUMERIC_TYPES:
        return "numeric"
    return "date" if column.data_type == "date" else "string"


def plan_columns(columns: Sequence[Column], rows: Sequence[Sequence[Cell]]) -> list[StatColumn]:
    """Names and storage types for one table, decided before anything is written.

    The only two things about the data that may change a type are recorded:
    an unreadable value, which has to be able to say `ENCRYPTED`, and a date
    that will not parse, which must not be thrown away to keep a column tidy.
    """
    taken: set[str] = set()
    planned: list[StatColumn] = []
    for index, column in enumerate(columns):
        cells = [row[index] for row in rows] if rows else []
        declared = declared_storage(column)
        reason = _forced_string(declared, cells)
        planned.append(
            StatColumn(
                name=_claim(column.name, taken),
                source=column.name,
                storage="string" if reason else declared,
                declared_storage=declared,
                changed_because=reason,
                label=_variable_label(column),
            )
        )
    return planned


def _forced_string(declared: Storage, cells: Sequence[Cell]) -> str | None:
    if declared == "string":
        return None
    if any(cell == ENCRYPTED for cell in cells):
        # The token is the point. A numeric column cannot hold it, and the
        # alternative — writing it as missing — is the failure item 5 names:
        # every tool treats missing as absent and averages the readable rows.
        return "holds ENCRYPTED, which a numeric column cannot"
    if declared == "date" and any(
        cell is not None and _as_date(cell) is None for cell in cells
    ):
        return "holds a value that is not a valid date"
    return None


def _claim(wanted: str, taken: set[str]) -> str:
    """A legal, unique, ≤32-character name, chosen the same way every time.

    Collisions are resolved by replacing the **tail** rather than appending, so
    the result still fits. The serial is assigned in plan order, and plan order
    is a function of the form versions alone — so the same form shortens to the
    same names in every export, which is what a do-file written last month
    depends on.
    """
    safe = "".join(character if character.isalnum() else "_" for character in wanted)
    if not safe or not safe[0].isalpha():
        # SPSS refuses a leading underscore and both refuse a leading digit.
        safe = f"v_{safe}"
    name = safe[:NAME_LIMIT]
    serial = 1
    while name.lower() in taken:
        serial += 1
        suffix = f"_{serial}"
        name = safe[: NAME_LIMIT - len(suffix)] + suffix
    taken.add(name.lower())
    return name


def _variable_label(column: Column) -> str | None:
    """The question text, qualified, and short enough for Stata.

    Qualified because four columns of one geopoint would otherwise all read
    `Dwelling location` in `describe`, which is worse than no label: it looks
    like four answers to one question rather than one answer in four parts.
    """
    if column.label is None:
        return None
    qualifier = column.component or ("label" if column.source == "label" else None)
    label = column.label if qualifier is None else f"{column.label} ({qualifier})"
    return label if len(label) <= LABEL_LIMIT else label[: LABEL_LIMIT - 1] + "…"


def check_string_lengths(
    planned: Sequence[StatColumn],
    rows: Sequence[Sequence[Cell]],
    *,
    fmt: str,
) -> None:
    """Refuse any value the format cannot hold. Measured in UTF-8 bytes.

    Runs before a byte is written, so the refusal names the column rather than
    arriving as a file that will not open. `.dta` has no limit to check: a value
    over `STATA_STR_LIMIT_BYTES` becomes a `strL`, which holds 2 GB.
    """
    limit = MAX_STRING_BYTES.get(fmt)
    if limit is None:
        return
    for index, stat in enumerate(planned):
        if stat.storage != "string":
            continue
        for row in rows:
            cell = row[index]
            if cell is None:
                continue
            found = len(str(cell).encode())
            if found > limit:
                raise ValueTooLong(stat.name, found, limit, fmt)


def write_table(
    table: Table, planned: Sequence[StatColumn], *, fmt: Literal["dta", "sav"]
) -> bytes:
    """One table as one file, with the types it declared and no others."""
    import pandas
    import pyreadstat

    check_string_lengths(planned, table.rows, fmt=fmt)

    frame = pandas.DataFrame(
        {
            stat.name: _series(pandas, stat, [row[index] for row in table.rows])
            for index, stat in enumerate(planned)
        },
        columns=[stat.name for stat in planned],
    )

    handle, path = tempfile.mkstemp(suffix=f".{fmt}")
    os.close(handle)
    try:
        if fmt == "dta":
            pyreadstat.write_dta(
                frame,
                path,
                version=DTA_VERSION,
                column_labels=[stat.label for stat in planned],
            )
        else:
            pyreadstat.write_sav(
                frame, path, column_labels=[stat.label for stat in planned]
            )
        _verify(path, planned, fmt)
        with open(path, "rb") as written:
            return written.read()
    finally:
        if os.path.exists(path):
            os.unlink(path)


def read_table(
    data: bytes, *, fmt: Literal["dta", "sav"]
) -> tuple[tuple[str, ...], tuple[tuple[Cell, ...], ...]]:
    """Header and rows, with the format's own types turned back into cells."""
    import pyreadstat

    handle, path = tempfile.mkstemp(suffix=f".{fmt}")
    os.close(handle)
    try:
        with open(path, "wb") as scratch:
            scratch.write(data)
        read = pyreadstat.read_dta if fmt == "dta" else pyreadstat.read_sav
        frame, _ = read(path)
    finally:
        if os.path.exists(path):
            os.unlink(path)

    header = tuple(str(name) for name in frame.columns)
    rows = tuple(
        tuple(_cell(value) for value in record) for record in frame.itertuples(index=False)
    )
    return header, rows


def _series(pandas: Any, stat: StatColumn, cells: Sequence[Cell]) -> Any:
    """One column, as the type its plan chose — or an exception.

    A value that will not go in is refused here rather than written as missing.
    Coercing it away would keep the column's type tidy and lose an answer, which
    is the whole failure this module is written against: `plan_columns` is
    supposed to have already turned the column to text for exactly these cases,
    so reaching this is a bug in the plan and not a property of the data.
    """
    if stat.storage == "numeric":
        numbers: list[float | None] = []
        for cell in cells:
            if cell is None:
                numbers.append(None)
                continue
            try:
                numbers.append(float(cell))
            except (TypeError, ValueError):
                raise TypeChanged(
                    f"{stat.name} is planned as numeric and holds {cell!r}. A "
                    "numeric column cannot carry it, and writing it as missing "
                    "would delete it — plan the column as text instead."
                ) from None
        return pandas.Series(numbers, dtype="float64")

    if stat.storage == "date":
        dates: list[dt.date | None] = []
        for cell in cells:
            if cell is None:
                dates.append(None)
                continue
            found = _as_date(cell)
            if found is None:
                raise TypeChanged(
                    f"{stat.name} is planned as a date and holds {cell!r}, which "
                    "is not one. Writing it as missing would delete it — plan "
                    "the column as text instead."
                )
            dates.append(found)
        if any(date is not None for date in dates):
            # An object column of real `date` objects comes back as real dates.
            # Writing `datetime64` instead returns midnight `Timestamp`s, and a
            # date that acquires a time is a date that no longer round-trips.
            return pandas.Series(dates, dtype=object)
        # …but a column of nothing but `None` is typed *string* by readstat,
        # which would make an empty date column a text one and hand the same
        # form two different schemas depending on whether anyone answered.
        # `NaT` in a datetime64 column is the spelling that stays numeric.
        return pandas.Series([pandas.NaT] * len(cells), dtype="datetime64[ns]")

    # A null in a string column comes back as the empty string whatever is
    # written, so it is written that way: what was declared and what returns
    # agree, and `_verify` stays a real check rather than a known exception.
    return pandas.Series(["" if cell is None else str(cell) for cell in cells], dtype=object)


def _as_date(cell: Cell) -> dt.date | None:
    """An ISO `YYYY-MM-DD` as a real date, or None if it is not one."""
    try:
        return dt.date.fromisoformat(str(cell))
    except ValueError:
        return None


def _verify(path: str, planned: Sequence[StatColumn], fmt: str) -> None:
    """Read the file back and check every column is the type it was written as.

    This is the guard the module exists for. readstat decides a type from the
    values, so the only way to know a numeric column stayed numeric is to look —
    and looking is cheap next to an export nobody can analyse.
    """
    import pandas
    import pyreadstat

    read = pyreadstat.read_dta if fmt == "dta" else pyreadstat.read_sav
    frame, meta = read(path)

    expected_readstat = {
        "numeric": "double",
        "string": "string",
        "date": "double",
    }
    for stat in planned:
        actual = meta.readstat_variable_types.get(stat.name)
        wanted = expected_readstat[stat.storage]
        if actual != wanted:
            raise TypeChanged(
                f"{stat.name} was written as {stat.storage} and came back as "
                f"{actual!r}, not {wanted!r}. readstat types a column from its "
                "values, so this means a value did not match its declared type."
            )
        if stat.storage == "date" and len(frame):
            sample = frame[stat.name].dropna()
            if len(sample) and not isinstance(
                sample.iloc[0], dt.date | dt.datetime | pandas.Timestamp
            ):
                raise TypeChanged(
                    f"{stat.name} was written as {stat.storage} and came back as "
                    f"{type(sample.iloc[0]).__name__}"
                )


def _cell(value: Any) -> Cell:
    """One value out of a statistical file, as a cell the reader understands."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        # Missing in a numeric column. Empty, not the string "nan".
        return None
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, str):
        return value
    if isinstance(value, int | float):
        return float(value)
    text = str(value)
    # A pandas Timestamp arrives here on some versions; its ISO form is what a
    # date cell holds everywhere else in this exporter.
    return text.replace(" ", "T") if _looks_like_a_stamp(text) else text


def _looks_like_a_stamp(text: str) -> bool:
    return len(text) >= 19 and text[4] == "-" and text[7] == "-" and text[10] == " "


def bundle_files(
    tables: Sequence[Table],
    planned: Mapping[str, Sequence[StatColumn]],
    *,
    fmt: Literal["dta", "sav"],
) -> list[tuple[str, bytes]]:
    return [
        (f"{table.name}.{fmt}", write_table(table, planned[table.name], fmt=fmt))
        for table in tables
    ]
