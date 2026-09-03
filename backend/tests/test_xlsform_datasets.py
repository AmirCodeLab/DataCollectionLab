"""Companion CSVs: reading them, and refusing to lose one in silence.

The workbook's coverage ledger makes it impossible to drop a *cell* quietly.
This is the same argument one level out, and the failure it guards is worse: a
`select_one_from_file` whose file did not arrive is a question with **no
options**, in a form that is otherwise perfectly valid. It compiles, both
engines agree, the vectors pass, it publishes and deploys, and an enumerator
gets a label with empty space under it.

So the tests here are mostly about what is *refused* and what is *said*, not
about the happy path — the happy path is the easy half, and it is covered by
the UCL form at the bottom, which is the acceptance for item 4 part 2.

The adversarial inputs are not invented here. They come from
`scripts/generate_ucl_datasets.py`, which builds the five files the real UCL
biomass form names and does it hostile on purpose — Tanzanian scale, Swahili
diacritics, embedded commas and quotes, blank cells, unused columns, and keys
differing only by case or whitespace (Form IR §3.1).
"""

from __future__ import annotations

import io
import pathlib
import subprocess
import sys

import pytest

from app.modules.forms.xlsform.datasets import CsvUnreadable, read_companion_csv
from app.modules.forms.xlsform.importer import import_workbook

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "xlsform"
UCL = FIXTURES / "ucl-biomass.xlsx"

#: Small enough to run in a test, large enough that "tens of thousands" is not
#: the untested case. The full-scale generation is what the acceptance run uses.
TEST_VILLAGES = 2_000


@pytest.fixture(scope="session")
def ucl_companions(tmp_path_factory: pytest.TempPathFactory) -> dict[str, bytes]:
    """The five UCL companion files, generated.

    Generated rather than committed: they are three megabytes at real scale and
    the generator is the honest artefact anyway — you can read what "adversarial"
    means in it, which you cannot read out of a CSV.
    """
    out = tmp_path_factory.mktemp("ucl-datasets")
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/generate_ucl_datasets.py"),
            "--out", str(out),
            "--villages", str(TEST_VILLAGES),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    files = {path.name: path.read_bytes() for path in sorted(out.glob("*.csv"))}
    assert len(files) == 5, f"the generator produced {sorted(files)}"
    return files


def csv_bytes(text: str) -> bytes:
    return text.encode("utf-8")


# --------------------------------------------------------------------------
# Reading a file
# --------------------------------------------------------------------------


def test_a_quoted_comma_stays_inside_its_value() -> None:
    """The commonest real breakage, and the reason `split(",")` is not enough.

    "Dar es Salaam, Ilala" is a council name. Split naively it becomes two
    columns, every later row is ragged, and the dataset is silently wrong.
    """
    parsed = read_companion_csv(
        "d.csv", csv_bytes('name,label\nD01,"Dar es Salaam, Ilala"\n')
    )
    assert parsed.rows == [{"name": "D01", "label": "Dar es Salaam, Ilala"}]


def test_a_quote_inside_a_value_survives() -> None:
    parsed = read_companion_csv(
        "v.csv", csv_bytes('name,label\nV01,"""Mtakuja"" settlement"\n')
    )
    assert parsed.rows[0]["label"] == '"Mtakuja" settlement'


def test_a_utf8_bom_is_not_part_of_the_first_column_name() -> None:
    """Excel writes one. Left in place it makes the `name` column `\\ufeffname`,
    which is not `name`, so the file arrives with no value column at all."""
    parsed = read_companion_csv("v.csv", b"\xef\xbb\xbfname,label\nV01,Mtakuja\n")
    assert parsed.columns == ["name", "label"]


def test_windows_1252_is_read_and_said_so_rather_than_guessed_at() -> None:
    """The asymmetry that decides this: cp1252 read as UTF-8 raises, so the
    wrong guess in that direction is loud. UTF-8 read as cp1252 succeeds and
    gives mojibake with no error anywhere — an enumerator simply sees a mangled
    village name. So the fallback happens and is *named*."""
    parsed = read_companion_csv("v.csv", "name,label\nV01,Kilimanjaro café\n".encode("cp1252"))
    assert parsed.encoding == "cp1252"
    assert parsed.rows[0]["label"] == "Kilimanjaro café"
    assert any("Windows-1252" in w for w in parsed.warnings)


def test_a_semicolon_separated_file_is_refused_rather_than_read_as_one_column() -> None:
    """Excel writes this on a European locale, and it parses perfectly as a
    one-column CSV whose column is named `name;label`. Guessing would produce a
    dataset with no key; refusing names the fix."""
    with pytest.raises(CsvUnreadable, match="semicolon"):
        read_companion_csv("v.csv", csv_bytes("name;label\nV01;Mtakuja\n"))


def test_a_row_with_more_values_than_columns_is_refused() -> None:
    # A value with no column to go in would be dropped. That is the silent loss
    # this whole module exists to make impossible.
    with pytest.raises(CsvUnreadable, match="row 2"):
        read_companion_csv("v.csv", csv_bytes("name,label\nV01,Mtakuja,extra\n"))


def test_a_short_row_is_padded_and_counted() -> None:
    """Different from the case above on purpose: Excel writes short rows when
    the trailing cells were never filled in, and refusing a file over that
    would refuse most real exports."""
    parsed = read_companion_csv("v.csv", csv_bytes("name,label,ward\nV01,Mtakuja\n"))
    assert parsed.rows[0] == {"name": "V01", "label": "Mtakuja", "ward": ""}
    assert any("fewer values" in w for w in parsed.warnings)


def test_two_columns_with_one_name_are_refused() -> None:
    with pytest.raises(CsvUnreadable, match="ambiguous"):
        read_companion_csv("v.csv", csv_bytes("name,label,Label\nV01,a,b\n"))


def test_a_column_with_no_name_is_refused() -> None:
    with pytest.raises(CsvUnreadable, match="no name"):
        read_companion_csv("v.csv", csv_bytes("name,,label\nV01,x,Mtakuja\n"))


def test_a_header_with_no_rows_under_it_is_refused() -> None:
    """Almost always a failed export rather than a deliberate empty list, and
    an empty list offers nothing to choose from either way."""
    with pytest.raises(CsvUnreadable, match="header row and no data"):
        read_companion_csv("v.csv", csv_bytes("name,label\n"))


def test_blank_rows_are_skipped_and_counted() -> None:
    parsed = read_companion_csv("v.csv", csv_bytes("name,label\nV01,a\n\n,\nV02,b\n"))
    assert len(parsed.rows) == 2
    assert any("blank row" in w for w in parsed.warnings)


def test_label_columns_are_read_the_way_the_choices_sheet_reads_them() -> None:
    parsed = read_companion_csv(
        "v.csv", csv_bytes("name,label::Swahili (sw),label::English (en)\nV01,Kijiji,Village\n")
    )
    assert parsed.label_columns() == {
        "sw": "label::Swahili (sw)",
        "en": "label::English (en)",
    }


def test_a_plain_label_column_has_no_language_of_its_own() -> None:
    """A Latin binomial is not English. The importer pairs it with the form's
    default language rather than inventing one."""
    parsed = read_companion_csv("s.csv", csv_bytes("name,label\nSP1,Brachystegia\n"))
    assert parsed.label_columns() == {}


# --------------------------------------------------------------------------
# What the importer does with them
# --------------------------------------------------------------------------


def build_workbook(rows: list[list[str | None]]) -> bytes:
    import openpyxl

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "survey"
    for row in rows:
        sheet.append(row)
    book.create_sheet("choices").append(["list_name", "name", "label"])
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


SIMPLE = [
    ["type", "name", "label"],
    ["select_one_from_file villages.csv", "village", "Village"],
]


def test_a_dataset_backed_select_becomes_a_dataset_choices_block() -> None:
    result = import_workbook(
        build_workbook(SIMPLE),
        companions={"villages.csv": csv_bytes("name,label\nV01,Mtakuja\nV02,Mbuyuni\n")},
    )
    node = result.form["children"][0]
    assert node["dataType"] == "select_one"
    assert node["choices"]["kind"] == "dataset"
    assert node["choices"]["dataset"] == "villages"
    assert node["choices"]["valueColumn"] == "name"
    assert list(node["choices"]["labelColumn"].values()) == ["label"]

    assert len(result.datasets) == 1
    assert result.datasets[0].row_count == 2
    assert result.datasets[0].used_by == ["village"]


def test_a_missing_companion_file_is_an_error_naming_the_file() -> None:
    """Not a warning. The question has no options — not fewer, none — and a
    form with an unanswerable question looks exactly like one without."""
    result = import_workbook(build_workbook(SIMPLE), companions={})
    missing = [d for d in result.diagnostics if d.code == "companion_file_missing"]
    assert len(missing) == 1
    assert missing[0].severity == "error"
    assert "villages.csv" in missing[0].message
    assert not result.publishable
    # And the question is dropped rather than published with an empty list.
    assert result.questions == 0


def test_importing_with_no_companions_at_all_still_names_every_file() -> None:
    """Supplying none is not the same as there being none, and a caller that
    forgot the argument must not get a quietly emptier form."""
    result = import_workbook(build_workbook(SIMPLE))
    codes = [d.code for d in result.diagnostics if d.severity == "error"]
    assert "companion_file_missing" in codes
    # `no_questions` follows, because dropping the only question leaves nothing
    # to collect. Both are true and both are said.
    assert codes == ["companion_file_missing", "no_questions"]


def test_a_second_question_on_the_same_missing_file_is_not_a_second_problem() -> None:
    """One explanation per file, and a located knock-on per question.

    Both halves matter. Four copies of "this file is missing" is three too many
    — but reporting only the first would leave three questions dropped with
    nothing pointing at their rows, which the coverage ledger caught when this
    was written the naive way.
    """
    result = import_workbook(
        build_workbook(
            [
                ["type", "name", "label"],
                ["select_one_from_file villages.csv", "a", "A"],
                ["select_one_from_file villages.csv", "b", "B"],
                ["select_one_from_file villages.csv", "c", "C"],
            ]
        ),
        companions={},
    )
    roots = [
        d
        for d in result.diagnostics
        if d.severity == "error" and d.caused_by is None and d.code != "no_questions"
    ]
    assert [d.code for d in roots] == ["companion_file_missing"]
    knock_ons = [d for d in result.diagnostics if d.code == "question_without_its_dataset"]
    assert len(knock_ons) == 2
    assert all(d.caused_by == roots[0].key for d in knock_ons)
    assert all(d.ref is not None for d in knock_ons), "every dropped row must be locatable"


def test_a_file_supplied_that_nothing_asks_for_is_reported() -> None:
    """Otherwise a rename on one side shows up as a missing list while the list
    is sitting in the upload."""
    result = import_workbook(
        build_workbook(SIMPLE),
        companions={
            "villages.csv": csv_bytes("name,label\nV01,Mtakuja\n"),
            "vilages.csv": csv_bytes("name,label\nV01,Mtakuja\n"),
        },
    )
    unused = [d for d in result.diagnostics if d.code == "companion_file_unused"]
    assert len(unused) == 1
    assert "vilages.csv" in unused[0].message


def test_a_file_name_is_matched_case_insensitively() -> None:
    """The survey sheet was written on Windows; the server is not."""
    result = import_workbook(
        build_workbook(SIMPLE),
        companions={"Villages.CSV": csv_bytes("name,label\nV01,Mtakuja\n")},
    )
    assert not [d for d in result.diagnostics if d.code == "companion_file_missing"]
    assert result.datasets[0].key == "villages"


def test_a_file_with_no_name_column_is_refused_and_the_question_dropped() -> None:
    result = import_workbook(
        build_workbook(SIMPLE),
        companions={"villages.csv": csv_bytes("code,label\nV01,Mtakuja\n")},
    )
    refused = [d for d in result.diagnostics if d.code == "dataset_has_no_value_column"]
    assert refused and refused[0].severity == "error"
    assert "`code`" in refused[0].message, "name the columns it does have"
    assert result.questions == 0


def test_two_files_that_normalise_to_one_key_are_refused() -> None:
    """One key cannot name two lists, and picking between them automatically
    would give a question the wrong options with nothing saying so."""
    result = import_workbook(
        build_workbook(
            [
                ["type", "name", "label"],
                ["select_one_from_file UCL-villages.csv", "a", "A"],
                ["select_one_from_file UCL_villages.csv", "b", "B"],
            ]
        ),
        companions={
            "UCL-villages.csv": csv_bytes("name,label\nV01,a\n"),
            "UCL_villages.csv": csv_bytes("name,label\nV01,b\n"),
        },
    )
    collision = [d for d in result.diagnostics if d.code == "dataset_key_collision"]
    assert collision and collision[0].severity == "error"


def test_a_dataset_backed_select_is_not_publishable_while_no_client_can_show_one() -> None:
    """Defect 7, one axis over — and the reason the registry has two lists.

    `select_one` is a collectable dataType. A *dataset-backed* `select_one` is
    not a collectable question: `CollectionViewModel` reads `choices.items`,
    which a dataset-backed list has none of, so the question would deploy and
    arrive with nothing under its label. Reporting it as fine because
    `select_one` is in the type list is exactly the conflation the registry
    exists to prevent.

    When item 4 parts 3 and 4 land, `dataset` joins `choiceSources` in
    `specs/collectable-types-v0.1.json` and this test is what says so.
    """
    result = import_workbook(
        build_workbook(SIMPLE),
        companions={"villages.csv": csv_bytes("name,label\nV01,Mtakuja\n")},
    )
    blocked = [d for d in result.diagnostics if d.code == "choice_source_not_collectable"]
    assert blocked and blocked[0].severity == "error"
    assert blocked[0].blame == "platform", "our gap, not the author's"
    assert not result.publishable
    # The data was still read and will still be published — the report has to
    # be able to say that the reference half worked.
    assert result.datasets[0].row_count == 1


# --------------------------------------------------------------------------
# Choice filters
# --------------------------------------------------------------------------

CASCADE = [
    ["type", "name", "label", "choice_filter"],
    ["select_one_from_file regions.csv", "region", "Region", None],
    ["select_one_from_file villages.csv", "village", "Village", "region_id=${region}"],
]
CASCADE_FILES = {
    "regions.csv": csv_bytes("name,label\nTZ01,Arusha\n"),
    "villages.csv": csv_bytes("name,label,region_id\nV01,Mtakuja,TZ01\n"),
}


def test_a_choice_filter_becomes_a_row_scoped_expression() -> None:
    """Form IR §3 addresses a candidate row's columns as `$row.column`, and the
    engine's evaluator already resolves those — this is the only context in
    XLSForm where a bare name means anything at all."""
    result = import_workbook(build_workbook(CASCADE), companions=CASCADE_FILES)
    village = result.form["children"][1]
    assert village["choices"]["filter"] == {
        "op": "eq",
        "args": [
            {"op": "ref", "path": "$row.region_id"},
            {"op": "ref", "path": "region"},
        ],
    }


def test_a_filter_column_the_file_has_not_got_is_refused() -> None:
    """It would match no rows, which on a phone is a list that is simply
    empty — indistinguishable from a list that has not loaded."""
    files = dict(CASCADE_FILES)
    files["villages.csv"] = csv_bytes("name,label,district_id\nV01,Mtakuja,D01\n")
    result = import_workbook(build_workbook(CASCADE), companions=files)
    bad = [d for d in result.diagnostics if d.code == "filter_column_not_in_dataset"]
    assert bad and bad[0].severity == "error"
    assert "`region_id`" in bad[0].message
    assert "`district_id`" in bad[0].message, "name the columns the file does have"
    # Refused, not attached: half a filter is worse than none.
    assert "filter" not in result.form["children"][1]["choices"]


def test_a_filter_referring_to_no_question_is_still_caught() -> None:
    """`$row.x` is excluded from the reference check because it is a column,
    not a question. The rest of the expression must not be excluded with it."""
    rows = [
        ["type", "name", "label", "choice_filter"],
        ["select_one_from_file villages.csv", "village", "Village", "region_id=${nowhere}"],
    ]
    result = import_workbook(
        build_workbook(rows),
        companions={"villages.csv": csv_bytes("name,label,region_id\nV01,a,TZ01\n")},
    )
    unknown = [d for d in result.diagnostics if d.code == "unknown_reference"]
    assert unknown and "nowhere" in unknown[0].message


def test_the_filter_columns_count_as_columns_the_form_reads() -> None:
    """What a delta is computed over (item 4 part 5). A column the form never
    reads must not cost a device a transfer when it changes, and this is the
    list that decides which those are."""
    result = import_workbook(build_workbook(CASCADE), companions=CASCADE_FILES)
    villages = next(d for d in result.datasets if d.key == "villages")
    assert set(villages.columns_used) == {"name", "label", "region_id"}


def test_a_filter_on_an_inline_list_is_still_only_reported() -> None:
    """Form IR §3 defines `filter` for dataset-backed lists; an inline item is
    `{value, label}` and carries no columns to filter on. So the cascading
    `choice_filter_test.xlsx` keeps saying its filter was not imported."""
    result = import_workbook((FIXTURES / "choice_filter_test.xlsx").read_bytes())
    ignored = [
        d
        for d in result.diagnostics
        if d.code == "column_ignored" and d.ref and d.ref.column == "choice_filter"
    ]
    assert ignored, "an inline choice_filter must still be reported"
    assert all(d.severity == "warning" for d in ignored)


# --------------------------------------------------------------------------
# The UCL form, end to end — the acceptance for item 4 part 2
# --------------------------------------------------------------------------


def test_the_ucl_form_reads_all_five_of_its_companion_files(
    ucl_companions: dict[str, bytes],
) -> None:
    """The acceptance: a real third-party form, its five lists, adversarial data.

    Not "it imported" — what it imported. Five files, eight questions fed from
    them, four cascading filters translated, and every one of them pinned to a
    key the publish endpoint will resolve.
    """
    result = import_workbook(UCL.read_bytes(), companions=ucl_companions)

    assert {d.key for d in result.datasets} == {
        "ucl_regions",
        "ucl_districts",
        "ucl_villages",
        "ulc_biomass_plots",
        "species_names",
    }, "the form's own spelling, including its `ULC` typo, normalised per §2.4"

    assert sum(len(d.used_by) for d in result.datasets) == 8
    assert not [d for d in result.diagnostics if d.code == "companion_file_missing"]
    assert not [d for d in result.diagnostics if d.code == "companion_file_unreadable"]

    # The cascade the acceptance is written around: region -> district ->
    # village, and plot filtered on village and planting phase.
    filters = {
        node["id"]: node["choices"]["filter"]
        for node in _walk(result.form["children"])
        if isinstance(node.get("choices"), dict) and "filter" in node["choices"]
    }
    assert set(filters) == {"district_id", "village", "plot_id"}


def test_the_ucl_species_list_keeps_its_other_row(
    ucl_companions: dict[str, bytes],
) -> None:
    """`${latin_name_id}='other'` is a relevant in the real form, so a species
    list without an `other` row makes a whole branch unreachable. Exactly the
    row a generated fixture forgets, which is why it is asserted rather than
    trusted."""
    result = import_workbook(UCL.read_bytes(), companions=ucl_companions)
    species = next(d for d in result.datasets if d.key == "species_names")
    assert any(row["name"] == "other" for row in species.rows)


def test_the_ucl_plot_list_reports_its_confusable_keys_and_merges_nothing(
    ucl_companions: dict[str, bytes],
) -> None:
    """Form IR §3.1: keys differing only by case or surrounding whitespace are
    different rows, reported and not merged. Merging them would be the platform
    deciding two of a customer's rows are one."""
    result = import_workbook(UCL.read_bytes(), companions=ucl_companions)
    confusable = [d for d in result.diagnostics if d.code == "dataset_keys_confusable"]
    assert confusable, "the generated plot list plants these deliberately"
    assert confusable[0].severity == "warning", "reported, not refused"
    assert "not merged" in confusable[0].message

    plots = next(d for d in result.datasets if d.key == "ulc_biomass_plots")
    keys = [row["name"] for row in plots.rows]
    assert len(keys) == len(set(keys)), "exact keys, so none of them collided"
    assert any(k != k.strip() for k in keys), "a trailing space survived the read"


def test_the_ucl_import_says_what_worked_and_not_only_what_did_not(
    ucl_companions: dict[str, bytes],
) -> None:
    """The report has to read as a partial success, because that is what it is.

    A report that itemises only failure cannot tell an author whether the half
    they care about survived, and a form with one unsupported question reads
    like a form that did not import at all.
    """
    from app.modules.forms.xlsform.report import render_markdown

    result = import_workbook(UCL.read_bytes(), companions=ucl_companions)
    markdown = render_markdown(
        result, source_name=UCL.name, form_id=result.form["formId"]
    )

    assert "**What worked**" in markdown
    assert "## Reference data" in markdown
    for dataset in result.datasets:
        assert dataset.file_name in markdown
        assert dataset.checksum in markdown
    assert "cascading filter(s)** were translated" in markdown


def test_every_ucl_dataset_would_publish_under_a_stable_content_address(
    ucl_companions: dict[str, bytes],
) -> None:
    """The checksum in the report is the one the server would store.

    Not a nicety: it is what tells "already published" from "a new version",
    and a device that cannot tell those apart re-downloads a 38,000-row list
    every sync.
    """
    from app.modules.entities.rows import content_address

    result = import_workbook(UCL.read_bytes(), companions=ucl_companions)
    for dataset in result.datasets:
        assert dataset.checksum == content_address(
            [dict(r) for r in dataset.rows], dataset.value_column
        )
    # And twice through the reader gives the same answer, or every delta is
    # spurious and every sync is a full transfer.
    again = import_workbook(UCL.read_bytes(), companions=ucl_companions)
    assert [d.checksum for d in again.datasets] == [d.checksum for d in result.datasets]


def _walk(nodes: list[dict]) -> list[dict]:
    found: list[dict] = []
    for node in nodes:
        found.append(node)
        found.extend(_walk(node.get("children", [])))
    return found


def test_what_still_blocks_the_ucl_form_is_no_longer_about_functions(
    ucl_companions: dict[str, bytes],
) -> None:
    """The blockers, named, so that "not done" stays specific.

    `atan` was one of them and is built — and behind it were `cos` and `sqrt`,
    which no count could see because the importer reports the first function it
    cannot translate per cell and `atan` is the innermost.

    What is left is two things, neither of them dataset work and neither of them
    a function: `${...}` inserted into six labels and constraint messages (§7
    carries plain text, and whether it should is a spec question), and a repeat
    inside a repeat (§2.3 defers nested repeats to IR v0.2).
    """
    result = import_workbook(UCL.read_bytes(), companions=ucl_companions)

    assert result.instrumentation.unsupported_functions == {}
    assert not result.publishable

    codes = sorted({d.code for d in result.diagnostics if d.severity == "error"})
    assert codes == [
        # A dataset-backed select cannot be presented yet — parts 3 and 4 built
        # the engine and the store; the collection screen is next.
        "choice_source_not_collectable",
        "does_not_compile",
        "nested_repeat_not_supported",
        "output_in_label",
    ], f"the blockers changed: {codes}"
