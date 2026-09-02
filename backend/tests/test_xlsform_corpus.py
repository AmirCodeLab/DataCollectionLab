"""The importer against forms other people wrote.

`test_xlsform_import.py` builds workbooks in memory to check that a particular
construct is handled a particular way. Every one of those tests can only fail on
a construct somebody thought of, which is the limitation this whole design is
about.

These run real files instead — see `fixtures/xlsform/PROVENANCE.md`. They are
unmodified, and every one of them turned up something the in-memory tests would
not have: curly quotes Excel inserted, `default` values that are literals rather
than XPath, camelCase names, a repeat nested in a repeat, and a blank template
that imported to a valid form with nothing in it.

What is asserted here is deliberately not "this form produces exactly that IR".
Pinning the output of a 54-question form would make every improvement to the
importer a test edit, and a test edited to match the code has stopped testing
it. What is asserted is the properties that must hold for **any** form:

  - no coverage hole — every cell consumed or reported
  - the IR either compiles or the report says why
  - a form with errors is not publishable
  - a form that imports clean actually compiles
"""

from __future__ import annotations

import pathlib

import pytest

from app.modules.form_engine.runtime import CompiledForm
from app.modules.forms.service import PublishRefused, check_publishable
from app.modules.forms.xlsform.importer import CoverageHole, import_workbook
from app.modules.forms.xlsform.report import render_html, render_markdown

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "xlsform"
WORKBOOKS = sorted(FIXTURES.glob("*.xlsx"))


def test_the_corpus_is_actually_here() -> None:
    # A parametrised suite over an empty glob passes without running anything,
    # which is the shape of green paperwork this repository keeps a script to
    # prevent (scripts/check_ci_runs_every_suite.py).
    assert len(WORKBOOKS) >= 4, f"expected the committed corpus, found {WORKBOOKS}"


@pytest.mark.parametrize("path", WORKBOOKS, ids=lambda p: p.name)
def test_no_real_form_produces_a_coverage_hole(path: pathlib.Path) -> None:
    """The invariant, against files nobody wrote to satisfy it.

    A hole means a cell produced no IR and no diagnostic — the silent drop. It
    raises rather than returning, so this test is the whole assertion.
    """
    try:
        import_workbook(path.read_bytes())
    except CoverageHole as hole:
        pytest.fail(f"{path.name}: {hole}")


@pytest.mark.parametrize("path", WORKBOOKS, ids=lambda p: p.name)
def test_the_ir_compiles_or_the_report_says_why(path: pathlib.Path) -> None:
    """Never IR that the engine refuses without the author being told.

    The UCL form is why: it nests a repeat inside a repeat, which IR v0.1 does
    not allow, and the importer used to return that as publishable.
    """
    result = import_workbook(path.read_bytes())
    try:
        CompiledForm(result.form)
    except Exception as failure:
        codes = {d.code for d in result.diagnostics}
        assert "does_not_compile" in codes, (
            f"{path.name}: the IR does not compile ({failure}) and nothing in the "
            "report says so"
        )
        assert not result.publishable


@pytest.mark.parametrize("path", WORKBOOKS, ids=lambda p: p.name)
def test_publishable_means_the_publish_gate_agrees(path: pathlib.Path) -> None:
    """`publishable` is a claim about what the server will do, so check it does.

    A console greys a button on this flag. If the flag and the gate disagree,
    an author is told their form is fine and the publish then refuses it — or
    worse, the other way round.
    """
    result = import_workbook(path.read_bytes())
    if not result.publishable:
        return
    check_publishable(result.form)  # raises if the gate disagrees


@pytest.mark.parametrize("path", WORKBOOKS, ids=lambda p: p.name)
def test_a_report_can_be_rendered_for_any_of_them(path: pathlib.Path) -> None:
    """The report is what gets emailed, so it must survive every real input.

    Cell values in real forms contain pipes, newlines, quotes and Swahili; a
    renderer that breaks on one of those breaks at the moment somebody needs it.
    """
    result = import_workbook(path.read_bytes())
    markdown = render_markdown(result, source_name=path.name, form_id=result.form["formId"])
    assert path.name in markdown
    assert "Questions imported" in markdown
    # The blind spot is stated in every report, not just when it bites.
    assert "blind to nothing being present" in markdown

    page = render_html(result, source_name=path.name, form_id=result.form["formId"])
    assert page.startswith("<!doctype html>")
    assert page.rstrip().endswith("</html>")


def test_a_form_with_no_questions_is_refused_at_publish() -> None:
    """Not merely reported — refused, by the gate every publish goes through.

    The blank ODK XLSForm Template is the case: a valid, compilable form with
    zero questions that passed every check there was. Reporting it in a file
    somebody may not read is not the same as stopping it.
    """
    empty = {
        "irVersion": "0.1",
        "formId": "empty",
        "version": 1,
        "title": {"en": "Empty"},
        "defaultLanguage": "en",
        "languages": ["en"],
        "children": [],
    }
    # It compiles perfectly well. That is the point.
    CompiledForm(empty)

    with pytest.raises(PublishRefused, match="no questions"):
        check_publishable(empty)


def test_the_widgets_form_reports_types_no_client_can_collect() -> None:
    """The distinction that only exists because defect 7 existed.

    `time`, `barcode`, `audio` and `video` are all in Form IR §2.1 and all
    evaluated by both engines. None can be presented to an enumerator, so a
    form using them would deploy and arrive unanswerable — which is an error,
    not a note.
    """
    result = import_workbook((FIXTURES / "odk-widgets.xlsx").read_bytes())
    uncollectable = result.instrumentation.uncollectable_types
    assert uncollectable, "the ODK widgets form is full of these"
    for diagnostic in result.diagnostics:
        if diagnostic.code == "type_not_collectable":
            assert diagnostic.severity == "error"


def test_the_ucl_form_names_what_it_needed_that_we_lack() -> None:
    """Instrumentation is the roadmap, so it has to actually be populated.

    Counted rather than guessed: across 27 real forms `atan` was the only
    missing function and `select_one_from_file` the top missing type, which is
    not the order anyone would have picked from reading the XLSForm spec.
    """
    result = import_workbook((FIXTURES / "ucl-biomass.xlsx").read_bytes())
    assert "atan" in result.instrumentation.unsupported_functions
    assert "select_one_from_file" in result.instrumentation.unsupported_types
    assert not result.publishable


def test_the_clean_form_is_clean_all_the_way_through() -> None:
    """One real form that goes end to end, so 'importable' is not theoretical."""
    result = import_workbook((FIXTURES / "xl_date_ambiguous_v1.xlsx").read_bytes())

    assert result.publishable, [d.message for d in result.diagnostics if d.severity == "error"]
    assert result.questions == 5
    compiled = check_publishable(result.form)
    assert len(compiled.fields) == 5


def test_a_sheet_that_lies_about_its_size_does_not_hang_the_import() -> None:
    """A workbook declares its own dimensions and openpyxl believes them.

    `ucl-biomass.xlsx` says `A1:AMJ1048576` — 1,048,576 rows by 1,024 columns —
    for 81 rows of content. Read-only mode yielded every one of those rows, so
    reading the sheet made over a billion calls and took 37 seconds. On an
    endpoint that accepts uploads that is not merely slow: it is a way to
    occupy a worker with a 16 KB file.

    The real file is the fixture, deliberately. A synthetic workbook with an
    inflated `<dimension>` does **not** reproduce this — openpyxl yields only
    the rows the XML actually declares, so the first version of this test
    passed with both defences removed and proved nothing. Whatever the real
    file does that a hand-made one does not, the real file is what has to be
    held to a time.
    """
    import time

    data = (FIXTURES / "ucl-biomass.xlsx").read_bytes()

    started = time.monotonic()
    result = import_workbook(data)
    elapsed = time.monotonic() - started

    assert result.questions == 54, "the fixture changed; re-check what this is measuring"
    assert elapsed < 5, (
        f"reading an 81-row form took {elapsed:.1f}s. The sheet declares "
        "1,048,576 rows; the reader must size itself from the cells that exist."
    )
