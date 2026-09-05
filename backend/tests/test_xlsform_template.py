"""The XLSForm template we hand to a customer imports clean, and stays that way.

`docs/xlsform-template/dcp-xlsform-template.xlsx` is a worked example sent to
RCons so their questionnaire tool emits something this importer takes without a
round trip, and `docs/xlsform-template.md` is the guide beside it. Both make
claims about this codebase — which types are collectable, which expressions
survive, that the workbook imports with nothing to report — and a document
making claims about code is a document that goes stale.

The failure this prevents is specific and quiet: somebody narrows the
collectable set or tightens the importer, every test here still passes because
none of them looks at `docs/`, and the file a customer is building their tool
against now describes a platform that no longer exists. They find out when they
send us a form.
"""

from __future__ import annotations

import pathlib

import pytest

from app.modules.form_engine.runtime import CompiledForm
from app.modules.form_engine.screens import build_screen_plan
from app.modules.forms.xlsform.datatypes import collectable_types
from app.modules.forms.xlsform.importer import import_workbook

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "docs" / "xlsform-template" / "dcp-xlsform-template.xlsx"
ROSTER = REPO_ROOT / "docs" / "xlsform-template" / "dcp-xlsform-roster-example.xlsx"
COMPANION = REPO_ROOT / "docs" / "xlsform-template" / "districts.csv"
GUIDE = REPO_ROOT / "docs" / "xlsform-template.md"


@pytest.fixture(scope="module")
def imported():
    assert TEMPLATE.is_file(), f"the template is missing: {TEMPLATE}"
    assert COMPANION.is_file(), f"the companion CSV is missing: {COMPANION}"
    return import_workbook(
        TEMPLATE.read_bytes(),
        companions={COMPANION.name: COMPANION.read_bytes()},
    )


def test_the_template_imports_with_nothing_to_report(imported) -> None:
    """Not merely 'no errors'. A warning is a claim the guide does not make."""
    loud = [d for d in imported.diagnostics if d.severity in ("error", "warning")]
    assert not loud, "the template must import silently, got: " + "; ".join(
        f"{d.severity} {d.code} at {d.ref}: {d.message}" for d in loud
    )
    assert imported.publishable
    assert imported.questions > 0


def test_the_template_demonstrates_every_collectable_type(imported) -> None:
    """The guide says "the template uses every one of them". This is that claim.

    A type added to `collectable-types-v0.1.json` with no row in the workbook
    makes the guide's table wrong for a customer building against it, and
    nothing else in this suite reads `docs/`.
    """
    used = {
        field.data_type
        for field in CompiledForm(imported.form).fields.values()
    }
    missing = set(collectable_types()) - used - {"note"}
    assert not missing, (
        f"collectable types with no row in the template: {sorted(missing)}. "
        "Add a row to docs/xlsform-template/ and its line to the table in "
        "docs/xlsform-template.md §2."
    )


@pytest.fixture(scope="module")
def roster():
    assert ROSTER.is_file(), f"the roster example is missing: {ROSTER}"
    return import_workbook(
        ROSTER.read_bytes(),
        companions={COMPANION.name: COMPANION.read_bytes()},
    )


def test_the_roster_example_publishes_now_that_a_roster_has_a_screen(roster) -> None:
    """Defect 14 closed, from the outside.

    This test asserted the opposite until repeat screen flow landed: a repeat was
    excluded from the screen plan (Form IR §11.1), so a form with a roster would
    have deployed and asked none of it, and the importer refused rather than
    warned. §11.3 gives a repeat a screen, the questions become reachable, and
    the refusal stops firing on its own — it was written against reachability and
    not against repeats, so nothing about it had to change.

    Kept, inverted, rather than deleted: the workbook is the shape RCons will
    emit, and "a roster imports clean" is the claim worth holding.
    """
    refusals = [d for d in roster.diagnostics if d.code == "questions_cannot_be_asked"]
    assert not refusals, [d.message for d in refusals]
    assert roster.publishable

    complaints = [d for d in roster.diagnostics if d.severity in ("error", "warning")]
    assert not complaints, [f"{d.severity} {d.code}" for d in complaints]


def test_a_calculate_is_not_counted_as_a_question_nobody_can_ask(imported) -> None:
    """The exclusion that keeps the refusal from crying wolf.

    A `calculate` is computed and never asked, so having no screen is normal for
    it. If it counted, every form carrying one would be refused — and the
    template carries one.
    """
    compiled = CompiledForm(imported.form)
    calculated = [f for f, c in compiled.fields.items() if c.node.get("calculate")]

    assert calculated, "precondition: the template has a calculate"
    assert imported.publishable


def test_every_roster_question_is_on_a_screen_of_the_instance_plan(roster) -> None:
    """The measurement defect 14 was filed on, run again and come out the other way.

    Before §11.3 this form produced 13 screens and **none** of the roster's four
    questions was on any of them. The count that matters is not the screen count
    — it is that no answerable question is missing from the plan.

    Asserted through `askable_question_ids`, which reads both levels, because a
    walk over the top-level screens alone would still report the roster missing
    and a walk that forgot the instance plan is precisely the mistake this
    guards.
    """
    compiled = CompiledForm(roster.form)
    plan = build_screen_plan(roster.form)

    in_repeat = {f for f, c in compiled.fields.items() if c.repeat is not None}
    assert in_repeat, "precondition: the roster example has a roster"
    assert "members" in compiled.repeats

    # One repeat screen in the plan, and the roster's questions on its instance
    # plan rather than on any top-level screen.
    repeat_screens = [s for s in plan.screens if s.repeat_id == "members"]
    assert len(repeat_screens) == 1, [s.repeat_id for s in plan.screens]
    top_level = {q for screen in plan.screens for q in screen.question_ids}
    assert not (in_repeat & top_level), (
        "a repeat's questions belong to its instance plan, not to a top-level screen"
    )

    missing = in_repeat - plan.askable_question_ids()
    assert not missing, f"roster questions still on no screen: {sorted(missing)}"


def test_the_guide_exists_and_names_both_workbooks_it_documents() -> None:
    text = GUIDE.read_text()
    assert TEMPLATE.name in text
    assert ROSTER.name in text
    assert COMPANION.name in text
