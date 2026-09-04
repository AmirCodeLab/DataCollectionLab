"""What `pyreadstat` actually does — measured before the exporter was written.

docs/project-conventions.md item 5 says to check what the `.dta` and `.sav` writers do with a
string in a numeric column *before* trusting the `ENCRYPTED` token there. This
file is that check, kept. It asserts library behaviour rather than our own,
which is unusual and deliberate: every decision in `export/statistical.py`
rests on one of these answers, and a library upgrade that changes one would
otherwise change what our files mean with nothing to see.

The four answers that decided the design:

1. **The token is not coerced to missing.** It survives — but the writer
   silently retypes the **whole column** to string to make that possible. So
   the danger is not lost data, it is a column whose type depends on whether
   any row in *this* export happened to be unreadable. Same form, same script,
   two exports, two types.
2. **readstat infers the type from the values, and a declared pandas dtype does
   not override it.** So the exporter has to decide the type itself and then
   *verify* what came back — which is what `statistical.write_dta` does.
3. **readstat enforces SPSS's 64-character name limit and not Stata's 32.** It
   will happily write a `.dta` that Stata itself refuses. Same for variable
   labels: SPSS truncates at 256, Stata's own 80 is not enforced at all.
4. **A value label keyed by a string code is silently written against `0`** in
   a `.dta`. Our choice codes are strings, so value labels are not usable and
   the resolved name goes in its own column instead.
5. **A long string is a `strL` in a `.dta` and out of spec in a `.sav`.** Read
   out of the file rather than asked of the library: over 2,045 **bytes** the
   `.dta` type code becomes `32768`, which is `strL` and holds 2 GB. A `.sav`
   took 40,000 bytes past SPSS's 32,767-byte maximum without a word — the same
   shape as the name limit, so the same answer: we enforce it ourselves.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import pytest

pandas = pytest.importorskip("pandas")
pyreadstat = pytest.importorskip("pyreadstat")

TOKEN = "ENCRYPTED"


def _roundtrip(frame: Any, path: Path, fmt: str, **kwargs: Any) -> tuple[Any, Any]:
    write, read = (
        (pyreadstat.write_dta, pyreadstat.read_dta)
        if fmt == "dta"
        else (pyreadstat.write_sav, pyreadstat.read_sav)
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        write(frame, str(path), **kwargs)
        return read(str(path))


@pytest.mark.parametrize("fmt", ["dta", "sav"])
def test_the_token_survives_beside_numbers_by_retyping_the_whole_column(
    tmp_path: Path, fmt: str
) -> None:
    """Answer 1, and the whole design decision.

    The failure docs/project-conventions.md warned about — the token coerced to missing, so a mean
    is computed over the rows that happen to be readable — does **not** happen.
    What happens instead is subtler and is why the exporter cannot leave this to
    the library: `100.0` comes back as the *string* `"100.0"`, because one
    unreadable row turned a numeric column into a text one. Nothing in the
    library's return says it did that.
    """
    frame = pandas.DataFrame({"income": pandas.Series([100.0, TOKEN, 250.5], dtype=object)})
    back, meta = _roundtrip(frame, tmp_path / f"t.{fmt}", fmt)

    assert list(back["income"]) == ["100.0", TOKEN, "250.5"]
    assert meta.readstat_variable_types["income"] == "string"


@pytest.mark.parametrize("fmt", ["dta", "sav"])
def test_the_same_column_is_numeric_when_nothing_is_unreadable(
    tmp_path: Path, fmt: str
) -> None:
    """The other half of answer 1: the type follows the data, not the schema.

    This pair is the instability. A do-file that says `summarize income` works
    against one export of a form and not the next, and the difference is which
    interviews happened to be encrypted. `export/statistical.py` decides the
    type from the plan and records it in the manifest so the change is at least
    stated; the library on its own states nothing.
    """
    frame = pandas.DataFrame({"income": pandas.Series([100.0, 250.5], dtype=object)})
    _, meta = _roundtrip(frame, tmp_path / f"t.{fmt}", fmt)

    assert meta.readstat_variable_types["income"] == "double"


def test_a_declared_dtype_does_not_override_the_inference(tmp_path: Path) -> None:
    """Answer 2. There is no way to *ask* for a numeric column; only to write one."""
    numbers = pandas.DataFrame({"v": pandas.Series([1.0, 2.0], dtype=object)})
    _, meta = _roundtrip(numbers, tmp_path / "n.dta", "dta")
    assert meta.readstat_variable_types["v"] == "double"

    with pytest.raises(Exception, match="format string"):
        _roundtrip(
            pandas.DataFrame({"v": pandas.Series([1.0, TOKEN], dtype=object)}),
            tmp_path / "s.sav",
            "sav",
            variable_format={"v": "%20s"},
        )


def test_stata_name_and_label_limits_are_not_enforced(tmp_path: Path) -> None:
    """Answer 3, and why `statistical.py` has its own limits.

    An 80-character variable name writes a `.dta` this library reads back
    perfectly and Stata refuses: Stata's limit is 32. A 300-character variable
    label writes whole, and Stata's limit is 80. SPSS's own limits *are*
    enforced — 64 and 256 — which is what makes the gap easy to miss: the
    format that complains is not the one with the tighter rule.
    """
    long_name = "m" + "x" * 79
    _, meta = _roundtrip(pandas.DataFrame({long_name: [1.0]}), tmp_path / "l.dta", "dta")
    assert long_name in meta.readstat_variable_types, "readstat wrote a name Stata rejects"

    with pytest.raises(Exception, match="too long"):
        _roundtrip(pandas.DataFrame({long_name: [1.0]}), tmp_path / "l.sav", "sav")

    _, dta_meta = _roundtrip(
        pandas.DataFrame({"v": [1.0]}), tmp_path / "c.dta", "dta", column_labels=["L" * 300]
    )
    assert len(dta_meta.column_names_to_labels["v"]) == 300, "Stata's 80 is not enforced"

    _, sav_meta = _roundtrip(
        pandas.DataFrame({"v": [1.0]}), tmp_path / "c.sav", "sav", column_labels=["L" * 300]
    )
    assert len(sav_meta.column_names_to_labels["v"]) == 256, "SPSS's 256 is enforced"


@pytest.mark.parametrize(
    "name, fmt",
    [
        ("members[i3].age", "dta"),
        ("members[i3].age", "sav"),
        ("members.i3.age", "dta"),
        ("_submission_id", "sav"),
        ("2nd_visit", "dta"),
    ],
)
def test_the_characters_a_value_path_contains_are_refused(
    tmp_path: Path, name: str, fmt: str
) -> None:
    """A repeat path is not a variable name in either format, and `.` and `_`
    differ *between* the two — so the safe set is the intersection, which is
    what `statistical.py` targets."""
    with pytest.raises(Exception, match="illegal"):
        _roundtrip(pandas.DataFrame({name: [1.0]}), tmp_path / f"x.{fmt}", fmt)


def test_a_value_label_keyed_by_a_string_code_lands_on_zero(tmp_path: Path) -> None:
    """Answer 4, and it is a silent corruption rather than a refusal.

    `V000023` labelled `Nyamburi Kati` comes back as `0` labelled
    `Nyamburi Kati` — a name attached to a value that is not in the data. Our
    choice codes are strings by design (§3.1: the key is the cell's value,
    exactly), so value labels are not available to us and the resolved name goes
    in its own column, exactly as it does in the CSV.
    """
    _, meta = _roundtrip(
        pandas.DataFrame({"village": ["V000023"]}),
        tmp_path / "v.dta",
        "dta",
        variable_value_labels={"village": {"V000023": "Nyamburi Kati"}},
    )
    assert meta.variable_value_labels == {"village": {0: "Nyamburi Kati"}}


def test_two_columns_with_one_name_are_refused_rather_than_merged(tmp_path: Path) -> None:
    """The backstop under our own truncation rule.

    Two long field names truncating to the same 32 characters would be a silent
    merge — one column of two questions' answers, with nothing wrong on the
    face of it. The library refuses, which makes it a crash rather than a merge;
    `statistical.py` resolves collisions before it gets here so it is neither.
    """
    frame = pandas.DataFrame([[1.0, 2.0]], columns=["same", "same"])
    with pytest.raises(Exception, match="unique column names"):
        _roundtrip(frame, tmp_path / "d.dta", "dta")


def test_dta_13_mangles_unicode_and_14_does_not(tmp_path: Path) -> None:
    """Why the writer pins a version instead of taking the default.

    This platform is RTL and Swahili from the start. A `.dta` written at
    version 13 returns `Ø§Ù„Ø´Ø¹Ø§Ø¹` for Arabic — the file is not corrupt, it is
    a pre-unicode format, and the damage is silent.
    """
    swahili = "Mkoa wa Arusha — الشعاع"
    frame = pandas.DataFrame({"mkoa": [swahili]})

    old, _ = _roundtrip(frame, tmp_path / "13.dta", "dta", version=13)
    assert old["mkoa"].iloc[0] != swahili

    new, _ = _roundtrip(frame, tmp_path / "14.dta", "dta", version=14)
    assert new["mkoa"].iloc[0] == swahili


@pytest.mark.parametrize("fmt", ["dta", "sav"])
def test_what_each_scalar_type_becomes(tmp_path: Path, fmt: str) -> None:
    """The type table the exporter is written against.

    Integers and booleans come back as doubles — both formats store one numeric
    type — so `42` is `42.0` and `True` is `1.0`. A real date survives as a real
    date, which is worth having: a Stata user who gets a string date has to
    parse it before they can do anything. A null in a string column comes back
    as the empty string, which is the same normalisation the CSV already makes.
    """
    import datetime

    frame = pandas.DataFrame(
        {
            "an_int": pandas.Series([42], dtype="int64"),
            "a_float": [0.1 + 0.2],
            "big_float": [123456789.123456789],
            "real_date": [datetime.date(2026, 9, 3)],
            "real_datetime": [datetime.datetime(2026, 9, 3, 9, 25, 13)],
            "a_string": ["09:25:13"],
            "a_null": pandas.Series([None], dtype=object),
        }
    )
    back, meta = _roundtrip(frame, tmp_path / f"t.{fmt}", fmt)

    assert back["an_int"].iloc[0] == 42.0
    assert meta.readstat_variable_types["an_int"] == "double"
    # Full double precision survives, so a decimal answer loses nothing.
    assert back["a_float"].iloc[0] == 0.1 + 0.2
    assert back["big_float"].iloc[0] == 123456789.123456789
    assert back["real_date"].iloc[0] == datetime.date(2026, 9, 3)
    assert back["real_datetime"].iloc[0] == pandas.Timestamp("2026-09-03 09:25:13")
    assert back["a_string"].iloc[0] == "09:25:13"
    assert back["a_null"].iloc[0] == ""


# --- long strings: what the file declares, not what the library returns ------

#: `<variable_types>` in a .dta 117/118 is one uint16 per variable:
#: 1..2045 is `str#N`, 32768 is `strL`, 65526 is `double`.
DTA_STRL = 32768


def _dta_type_code(path: Path, index: int = 0) -> int:
    raw = path.read_bytes()
    start = raw.index(b"<variable_types>") + len(b"<variable_types>")
    return int.from_bytes(raw[start + index * 2 : start + index * 2 + 2], "little")


@pytest.mark.parametrize(
    "text, expected, why",
    [
        ("s" * 2044, 2044, "under the limit: a fixed-width str#"),
        ("s" * 2045, DTA_STRL, "at the limit: promoted to strL"),
        ("s" * 40000, DTA_STRL, "far over: still a strL, still whole"),
        # 2,044 Arabic characters are 4,088 bytes. A character-counted check
        # would call this "under the limit" and be wrong by half.
        ("ش" * 2044, DTA_STRL, "counted in BYTES, not characters"),
        ("ش" * 1000, 2000, "2,000 bytes of Arabic is still a str#"),
    ],
)
def test_a_dta_promotes_a_long_string_to_strl_by_byte_length(
    tmp_path: Path, text: str, expected: int, why: str
) -> None:
    """Answer 5, and the reason `.dta` needs no limit of ours.

    This is read out of the file's own type table rather than inferred from what
    `read_dta` hands back — pyreadstat agreeing with itself proves nothing about
    what Stata will accept. `strL` is Stata 13+ and holds 2 GB, and the writer
    pins version 15, so a long answer is genuinely not a problem here.

    The Arabic rows are the ones that matter for this product: both formats size
    a string in bytes, and 2,044 Arabic characters are 4,088 of them.
    """
    path = tmp_path / "l.dta"
    _roundtrip(pandas.DataFrame({"v": [text]}), path, "dta", version=15)

    assert _dta_type_code(path) == expected, why
    back, _ = pyreadstat.read_dta(str(path))
    assert back["v"].iloc[0] == text, "the value must survive whole either way"


def test_a_sav_accepts_a_string_past_spsss_own_maximum(tmp_path: Path) -> None:
    """The other half of answer 5, and why the `.sav` limit is ours to enforce.

    SPSS's documented maximum for a string variable is 32,767 bytes. readstat
    writes past it without complaint — exactly as it writes a `.dta` variable
    name Stata refuses. The library implements the format it can and leaves the
    application's rules to the caller, so `statistical.check_string_lengths` is
    the caller doing that.

    If a future readstat starts refusing this, that is good news and this test
    should fail so somebody notices the guard has a second layer under it.
    """
    over = "s" * 40000
    back, _ = _roundtrip(pandas.DataFrame({"v": [over]}), tmp_path / "l.sav", "sav")
    assert len(back["v"].iloc[0]) == 40000, (
        "readstat refused an over-length .sav string; check whether "
        "MAX_STRING_BYTES['sav'] is still the only thing enforcing SPSS's limit"
    )
