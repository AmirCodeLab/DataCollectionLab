"""The companion CSVs beside an XLSForm, read as dataset rows.

`select_one_from_file villages.csv` names a file that is not in the workbook.
XLSForm ships it beside the .xlsx and nothing in the spreadsheet describes its
contents, so an importer that reads only the workbook cannot know whether the
question has two options or fifty thousand — or any.

## The same accounting as the workbook, one level out

`workbook.py` refuses to lose a cell in silence. This refuses to lose a *file*
in silence, which is the same argument moved one level out: a question whose
choice list did not arrive is a question with no options, and a form with a
question that offers nothing is a perfectly valid form. Nothing downstream can
tell. So every companion file named by the survey sheet is in exactly one of
three states by the end of an import — read, refused with a reason, or reported
missing by name — and every file *supplied* that nothing named is reported too,
because an unreferenced CSV is usually a filename typo on one side or the other.

## Why the parsing is fussy

These files are produced by people, in Excel, on Windows, in Swahili, and then
emailed. Every rule below exists because the alternative is a plausible-looking
dataset that is quietly wrong:

  encoding      cp1252 read as UTF-8 raises; UTF-8 read as cp1252 gives
                mojibake and no error at all, so the fallback is *named* in a
                warning rather than applied quietly
  delimiter     a semicolon-separated file parses perfectly as one-column CSV.
                It is refused, not guessed at, because the guess is a dataset
                with one column and no key
  ragged rows   a row with more cells than the header would lose the extra
                ones. A row with fewer is Excel trimming trailing blanks, which
                is ordinary — so one is refused and the other is padded and
                counted
  blank header  a column with no name cannot be referenced by `valueColumn`,
                a `labelColumn` or a filter, so it cannot be silently kept

Values stay strings, always. A CSV holds text; §3.1 makes the key the cell's
value exactly, and turning `007` into `7` on the way in would make it stop
matching the answer collected from it.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

#: What ODK requires of a `select_one_from_file` CSV, and therefore what this
#: assumes when the form does not say otherwise: `name` is the stored value,
#: `label` is what the enumerator reads.
DEFAULT_VALUE_COLUMN = "name"
DEFAULT_LABEL_COLUMN = "label"

#: `label::Swahili (sw)` on the choices sheet is `label::Swahili (sw)` in the
#: CSV too — same convention, same parser, one place.
_LANGUAGE_COLUMN = re.compile(r"^(?P<base>[a-z_:]+?)::(?P<language>.+)$")

#: A file this size is not reference data somebody meant to attach. The limit
#: is on the decoded text rather than the upload so that a compressed upload
#: cannot expand past it.
MAX_CSV_BYTES = 64 * 1024 * 1024

#: Beyond this a dataset is not a choice list any more, whatever it is.
#: Deliberately above the 50k rows §12's performance contract is written
#: against, so the limit refuses absurdity rather than the intended case.
MAX_ROWS = 500_000


class CsvUnreadable(Exception):
    """This file is not a readable CSV of reference data.

    Distinct from a diagnostic about its contents, the same way `WorkbookError`
    is distinct from a diagnostic about a form: there is no row to point at.
    The message is written to be shown to whoever attached the file.
    """


@dataclass
class CompanionCsv:
    """One companion file, read.

    `columns` keeps the file's own order — it is what the report prints and
    what a person matches against the file they have open.
    """

    file_name: str
    columns: list[str]
    rows: list[dict[str, str]]
    #: How the bytes were decoded. Named in the report when it was not UTF-8,
    #: because a wrong guess here is invisible in every other way.
    encoding: str = "utf-8"
    #: Non-fatal findings about the file itself: padded rows, skipped blanks,
    #: a fallback encoding. Sentences, ready to show.
    warnings: list[str] = field(default_factory=list)

    def label_columns(self) -> dict[str, str]:
        """Language tag -> column name, from `label` / `label::English (en)`.

        Mirrors the choices sheet exactly. A file with a plain `label` column
        and no language suffix yields `{}` here and the caller pairs it with
        the form's default language — species names have no language, and
        inventing one for them would put `la` in the IR for no reason.
        """
        found: dict[str, str] = {}
        for column in self.columns:
            match = _LANGUAGE_COLUMN.match(column)
            if not match or match.group("base") != DEFAULT_LABEL_COLUMN:
                continue
            language = match.group("language").strip()
            tagged = re.search(r"\(([A-Za-z-]{2,})\)\s*$", language)
            key = (
                tagged.group(1).lower()
                if tagged
                else (re.sub(r"[^a-z0-9]+", "_", language.lower()).strip("_") or language)
            )
            found[key] = column
        return found


def _decode(file_name: str, data: bytes) -> tuple[str, str, list[str]]:
    """Text, the encoding used, and a warning if it was not UTF-8.

    UTF-8 is tried strictly first and cp1252 only as a *named* fallback. The
    asymmetry is the point: cp1252 bytes read as UTF-8 raise, so the wrong
    guess in that direction is loud, while UTF-8 bytes read as cp1252 succeed
    and produce `Kilimanjaro` as `KilimanjaroÂ` — a dataset that looks fine,
    publishes fine, and shows an enumerator a mangled village name.
    """
    warnings: list[str] = []
    try:
        return data.decode("utf-8-sig"), "utf-8", warnings
    except UnicodeDecodeError as failure:
        offset = failure.start

    try:
        text = data.decode("cp1252")
    except UnicodeDecodeError as failure:
        raise CsvUnreadable(
            f"`{file_name}` is not text this importer can read: it is not UTF-8 "
            f"(byte {offset}) and not Windows-1252 either (byte {failure.start}). "
            "Save it from Excel as 'CSV UTF-8'."
        ) from failure

    warnings.append(
        f"`{file_name}` is not UTF-8 (byte {offset} is not valid UTF-8) and was read "
        "as Windows-1252, which is what Excel's plain 'CSV' export produces. Check "
        "any accented or Swahili name in the report below; if one looks wrong, "
        "re-save the file from Excel as 'CSV UTF-8'."
    )
    return text, "cp1252", warnings


def _header(file_name: str, raw: list[str]) -> list[str]:
    columns: list[str] = []
    for index, cell in enumerate(raw):
        name = cell.strip()
        if not name:
            # Trailing empty header cells are what a spreadsheet leaves behind
            # and carry no data; one in the middle is a column that cannot be
            # named, and therefore cannot be a value, label or filter column.
            if any(c.strip() for c in raw[index + 1 :]):
                raise CsvUnreadable(
                    f"`{file_name}` has a column with no name (column "
                    f"{index + 1} of the header row). A column that cannot be "
                    "named cannot be selected, labelled or filtered on."
                )
            break
        columns.append(name)

    if not columns:
        raise CsvUnreadable(f"`{file_name}` has no header row, so its columns have no names.")

    seen: dict[str, str] = {}
    for column in columns:
        folded = column.casefold()
        if folded in seen:
            raise CsvUnreadable(
                f"`{file_name}` has two columns named `{seen[folded]}` and `{column}`. "
                "A lookup by column name would be ambiguous, so which of them a "
                "form meant cannot be decided."
            )
        seen[folded] = column
    return columns


def read_companion_csv(file_name: str, data: bytes) -> CompanionCsv:
    """Read one companion CSV, or refuse it with a sentence saying why."""
    if not data.strip():
        raise CsvUnreadable(
            f"`{file_name}` is empty. An empty reference list offers nothing to "
            "choose from, and is almost always a file that failed to export."
        )
    if len(data) > MAX_CSV_BYTES:
        raise CsvUnreadable(
            f"`{file_name}` is {len(data) // (1024 * 1024)} MB, past the "
            f"{MAX_CSV_BYTES // (1024 * 1024)} MB limit for reference data."
        )

    text, encoding, warnings = _decode(file_name, data)

    # A semicolon-separated file parses as a one-column CSV without complaint,
    # and the resulting dataset has a single column whose name is the whole
    # header line. Refused rather than guessed at, and named so the fix is
    # obvious — this is what Excel writes on a machine with a European locale.
    first_line = text.splitlines()[0] if text.splitlines() else ""
    if "," not in first_line and ";" in first_line:
        raise CsvUnreadable(
            f"`{file_name}` looks semicolon-separated: its header row has no comma "
            f"and {first_line.count(';')} semicolon(s). Excel writes this on a "
            "machine whose locale uses the comma as a decimal separator. Re-save "
            "it as 'CSV UTF-8' with comma separators."
        )

    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        raw_rows = list(reader)
    except csv.Error as failure:
        raise CsvUnreadable(f"`{file_name}` could not be parsed as CSV: {failure}") from failure

    if not raw_rows:
        raise CsvUnreadable(f"`{file_name}` has no rows at all.")

    columns = _header(file_name, raw_rows[0])
    width = len(columns)

    rows: list[dict[str, str]] = []
    blank = 0
    padded = 0
    for number, values in enumerate(raw_rows[1:], start=2):
        if not any(v.strip() for v in values):
            blank += 1
            continue
        # Trailing cells beyond the named columns are only ignorable when they
        # hold nothing; anything else is data with no column to go in.
        if len(values) > width and any(v.strip() for v in values[width:]):
            raise CsvUnreadable(
                f"`{file_name}` row {number} has {len(values)} values but the header "
                f"names {width} columns, and the extra value(s) are not empty "
                f"({', '.join(repr(v) for v in values[width:][:3])}). A value with no "
                "column would be dropped, so the file is refused rather than "
                "half-read. An unquoted comma inside a name is the usual cause."
            )
        if len(values) < width:
            padded += 1
            values = values + [""] * (width - len(values))
        rows.append({column: values[index] for index, column in enumerate(columns)})
        if len(rows) > MAX_ROWS:
            raise CsvUnreadable(
                f"`{file_name}` has more than {MAX_ROWS:,} rows. That is past what "
                "this platform will deliver to a device as a choice list."
            )

    if not rows:
        raise CsvUnreadable(
            f"`{file_name}` has a header row and no data. An empty reference list "
            "offers nothing to choose from."
        )
    if blank:
        warnings.append(f"{blank} blank row(s) in `{file_name}` were skipped.")
    if padded:
        warnings.append(
            f"{padded} row(s) in `{file_name}` had fewer values than the header has "
            "columns; the missing ones were read as empty. Excel writes this when "
            "the trailing cells of a row were never filled in."
        )

    return CompanionCsv(
        file_name=file_name,
        columns=columns,
        rows=rows,
        encoding=encoding,
        warnings=warnings,
    )
