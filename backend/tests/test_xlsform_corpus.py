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

    The type half of that has been built (item 4 part 2), and this asserts the
    change rather than the old state: `select_one_from_file` is no longer an
    unsupported *type*. What replaced it is a narrower and more honest claim —
    the questions import and no client can present a dataset-backed list yet —
    and that is counted separately, because "we cannot read this" and "we can
    read it and cannot show it" are different items on a roadmap.
    """
    result = import_workbook((FIXTURES / "ucl-biomass.xlsx").read_bytes())
    assert "select_one_from_file" not in result.instrumentation.unsupported_types, (
        "the importer still reports this as a type it cannot read; it imports now"
    )
    assert result.instrumentation.unsupported_functions == {}, (
        f"the roadmap should be empty for this form and says {result.instrumentation}. "
        "`atan` was on it, and behind atan were `cos` and `sqrt` — the importer "
        "reports the first function it cannot translate per cell and atan is the "
        "innermost, so a count could not see the other two. All three are built."
    )
    # Still not publishable, and now for nothing to do with functions: `${...}`
    # in six labels (§7, the author's) and a repeat inside a repeat (§2.3, IR
    # v0.2). Neither is dataset work and neither is a function.
    assert not result.publishable
    # Imported with no companion files, so the missing-list errors are here
    # too — `test_xlsform_datasets.py` is where it is imported with them.
    codes = {d.code for d in result.diagnostics if d.severity == "error"}
    # `output_in_label` is gone: §7.1 carries interpolation now, and the six
    # UCL labels that inserted an answer are labels rather than errors.
    assert codes == {
        "companion_file_missing",
        "question_without_its_dataset",
        "unknown_reference",
        "nested_repeat_not_supported",
        "does_not_compile",
    }, f"the blockers changed: {sorted(codes)}"


def test_the_clean_form_is_clean_all_the_way_through() -> None:
    """One real form that goes end to end, so 'importable' is not theoretical."""
    result = import_workbook((FIXTURES / "choice_filter_test.xlsx").read_bytes())

    assert result.publishable, [d.message for d in result.diagnostics if d.severity == "error"]
    assert result.questions == 3
    compiled = check_publishable(result.form)
    assert len(compiled.fields) == 3


def test_an_output_in_a_choice_label_is_refused_like_one_in_a_question_label() -> None:
    """A choice label is read out loud to somebody, so it gets the same check.

    It did not, and a handset found it. `xl_date_ambiguous_v1.xlsx` labels its
    choices `${name1}`, `${name2}`, `${name3}`; the form imported as
    publishable, was deployed, reached a Pixel, and offered a respondent three
    options reading literally "${name1}". Every check passed — the label was
    valid IR, it compiled, both engines agreed.

    The check existed for question labels and hints the whole time. It was
    simply not applied to the choices sheet, which is the kind of gap that
    survives review because the code that has it looks complete.
    """
    result = import_workbook((FIXTURES / "xl_date_ambiguous_v1.xlsx").read_bytes())

    outputs = [d for d in result.diagnostics if d.code == "output_in_label"]
    assert len(outputs) == 3, "one per choice label carrying a ${...}"
    for diagnostic in outputs:
        assert diagnostic.severity == "error"
        assert diagnostic.ref is not None
        assert diagnostic.ref.sheet == "choices"
    assert not result.publishable


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

    # 54 with no companion files supplied — the eight `select_one_from_file`
    # questions are dropped because their CSVs did not arrive, which is the
    # right answer to "the list has no options" and is what this call asks for.
    # `test_xlsform_datasets.py` is where the same form is imported *with* them.
    assert result.questions == 54, "the fixture changed; re-check what this is measuring"
    assert elapsed < 5, (
        f"reading an 81-row form took {elapsed:.1f}s. The sheet declares "
        "1,048,576 rows; the reader must size itself from the cells that exist."
    )


def test_a_version_imported_with_errors_is_refused_by_the_server() -> None:
    """The block lives on the publish path, not only in the report.

    `publishable: false` and the CLI's exit 1 are advice to whoever ran them.
    This is the server refusing — the difference between a report somebody may
    not have read and a version that cannot reach a phone.

    Every error here is something that changes what the form asks or collects,
    so shipping one is not a smaller version of shipping a good form; it is
    collecting the wrong data with everything looking healthy.
    """
    from app.modules.forms.schemas import ImportDiagnostic, ImportRecord

    result = import_workbook((FIXTURES / "ucl-biomass.xlsx").read_bytes())
    assert not result.publishable, "the fixture must have errors for this to mean anything"

    record = ImportRecord(
        sourceName="ucl-biomass.xlsx",
        sourceSha256="0" * 64,
        importerVersion="0.1.0",
        diagnostics=[
            ImportDiagnostic(
                severity=d.severity,
                code=d.code,
                message=d.message,
                sheet=d.ref.sheet if d.ref else None,
                row=d.ref.row if d.ref else None,
                column=d.ref.column if d.ref else None,
                cellValue=d.cell_value,
                nodeId=d.node_id,
                remedy=d.remedy,
            )
            for d in result.diagnostics
        ],
    )

    # A clean form with the same record still refuses: it is the record that
    # blocks, not the IR, because the IR is the part that survived.
    clean = import_workbook((FIXTURES / "choice_filter_test.xlsx").read_bytes())
    check_publishable(clean.form)  # fine on its own

    import asyncio

    from app.modules.forms import service

    async def attempt() -> None:
        await service.publish_version(
            session=None,  # never reached: the refusal precedes any database work
            project_id="p",
            ir=clean.form,
            import_record=record,
        )

    with pytest.raises(PublishRefused) as refusal:
        asyncio.run(attempt())
    assert len(refusal.value.violations) == len(
        [d for d in result.diagnostics if d.severity == "error"]
    )
    assert any("row" in v for v in refusal.value.violations), (
        "the refusal should say where, not just what"
    )


def test_a_version_that_was_not_imported_writes_sql_null_not_json_null() -> None:
    """SQL NULL and JSON null are different, and they print the same.

    `import_report` is JSONB. SQLAlchemy writes Python None into a JSONB column
    as the JSON value `null` unless told otherwise, and JSON null is NOT NULL in
    SQL — so a version published from hand-written IR failed
    `form_version_import_complete_check`, which asks for all five import columns
    NULL or all five set. The error printed the offending value as "null",
    identical to the SQL NULL it was supposed to be.

    Caught by the `db` suite — 12 errors — and by nothing else: every check that
    does not talk to Postgres passed. This asserts the column's configuration so
    the reason survives, since the db suite says only that something is wrong.
    """
    from app.modules.forms.models import FormVersion

    column = FormVersion.__table__.c.import_report
    assert column.type.none_as_null is True, (
        "import_report must map Python None to SQL NULL. Without it a version "
        "that was never imported stores JSON null, which is NOT NULL, and the "
        "all-or-nothing CHECK refuses it."
    )


def test_the_ucl_report_separates_our_gaps_from_the_author_s() -> None:
    """An author must be able to tell what they can fix from what they cannot.

    Read as an author, the first version of this report said "22 problems" for
    a form whose real content is nine things to change and eight instances of
    one feature we have not built. Six of the twenty-two were knock-ons of
    those, and one — `select_one_from_file` — was reported with "check the
    spelling" for a correctly spelled, real XLSForm type.

    Somebody acting on that spends an evening failing to fix our gap.
    """
    result = import_workbook((FIXTURES / "ucl-biomass.xlsx").read_bytes())
    errors = [d for d in result.diagnostics if d.severity == "error"]
    roots = [d for d in errors if d.caused_by is None]
    cascades = [d for d in errors if d.caused_by is not None]

    assert cascades, "the references to dropped questions should hang off their cause"
    for cascade in cascades:
        assert any(r.key == cascade.caused_by for r in roots), (
            f"{cascade.code} points at {cascade.caused_by}, which is not a root"
        )

    ours = [d for d in roots if d.blame == "platform"]
    theirs = [d for d in roots if d.blame == "author"]
    assert ours and theirs, "this form has both kinds; a report that says otherwise is wrong"

    # The specific misdirection that prompted this: a real type, spelled right.
    for diagnostic in result.diagnostics:
        if diagnostic.code == "type_not_implemented":
            assert diagnostic.blame == "platform"
            assert "spelling" not in (diagnostic.remedy or "").lower()
            assert "Nothing is wrong with your spreadsheet" in (diagnostic.remedy or "")

    # Nested repeats are deferred by our own spec (§2.3), so they are ours.
    nested = [d for d in roots if d.code == "nested_repeat_not_supported"]
    assert nested and nested[0].blame == "platform"
    assert nested[0].ref is not None, "the author should not have to hunt for the row"


def test_every_error_can_be_located_or_is_deliberately_global() -> None:
    """"Where: —" makes an author hunt. Give a row wherever one exists."""
    for path in WORKBOOKS:
        result = import_workbook(path.read_bytes())
        for diagnostic in result.diagnostics:
            if diagnostic.severity != "error":
                continue
            # `no_questions` is the only finding about a whole workbook.
            if diagnostic.code == "no_questions":
                continue
            assert diagnostic.ref is not None, (
                f"{path.name}: {diagnostic.code} has no location — {diagnostic.message}"
            )


def test_a_report_leads_with_whose_problem_it_is() -> None:
    result = import_workbook((FIXTURES / "ucl-biomass.xlsx").read_bytes())
    markdown = render_markdown(result, source_name="ucl-biomass.xlsx", form_id="ucl")

    assert "Things this platform cannot do yet" in markdown
    assert "These are not mistakes in your spreadsheet" in markdown
    assert "Things to change in your form" in markdown
    assert "knock-on effects" in markdown
    # The old headline counted consequences as problems.
    assert "22 problem" not in markdown


def test_a_regex_the_engine_cannot_run_is_refused_at_publish() -> None:
    """§4.6 forbids lookahead; §4.7 made evaluation stop reporting it.

    The two together are what makes this a publish check and not a runtime one.
    An expression is evaluated on every keystroke and has no channel to explain
    itself, so §4.7 makes it null — and a null constraint passes (§4.4.7). The
    validation the author wrote then silently does not happen, for everybody,
    forever. This is the only place left that can say so.
    """
    form = {
        "irVersion": "0.1",
        "formId": "lookahead",
        "version": 1,
        "title": {"en": "Lookahead"},
        "defaultLanguage": "en",
        "languages": ["en"],
        "children": [
            {
                "type": "question",
                "id": "password",
                "dataType": "text",
                "label": {"en": "Password"},
                "constraint": {
                    "op": "call",
                    "fn": "regex",
                    "args": [
                        {"op": "ref", "path": "password"},
                        {"op": "lit", "value": "^(?=.*[0-9]).{8,}$"},
                    ],
                },
            }
        ],
    }
    # It compiles and evaluates perfectly happily. That is the point.
    CompiledForm(form)

    with pytest.raises(PublishRefused) as refusal:
        check_publishable(form)
    assert any("(?=" in v for v in refusal.value.violations)
    assert any("pass for everybody" in v for v in refusal.value.violations)


def test_an_ordinary_regex_still_publishes() -> None:
    """The control. A rule that refused every pattern would also pass the test
    above, and the UCL form's phone-number constraint is a real one."""
    result = import_workbook((FIXTURES / "ucl-biomass.xlsx").read_bytes())
    patterns = [
        d for d in result.diagnostics if d.code == "untranslatable_expression"
        and "regex" in (d.cell_value or "")
    ]
    assert not patterns, "the phone-number regex must still translate"
