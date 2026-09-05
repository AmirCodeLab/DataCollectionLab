"""A repeat inside a field-list group is refused, on both engines (§10.2).

**No vector reaches this.** Every case in `conformance/vectors` is a form plus
an ordered list of steps, and every step assumes a form that compiled — the
format cannot say "this document must be refused". `conformance/malformed`
covers §10.1 and `conformance/sensitivity` covers exactly one §10.2 rule; the
rest of §10.2, this refusal and the nested-repeat refusal included, is held by a
test in each engine and nothing else.

That is a real exposure and it is named here rather than left to be discovered:
two engines that disagree about which forms compile is a form author meeting a
refusal their builder told them was not there. The Kotlin half is
`ScreensRepeatTest` in `shared/form-engine/src/jvmTest`, and the two must be
changed together.
"""

from __future__ import annotations

import pytest

from app.modules.form_engine.runtime import CompiledForm, CompileError
from app.modules.form_engine.screens import build_screen_plan


def _form(children: list[dict]) -> dict:
    return {
        "irVersion": "0.1",
        "formId": "fl_repeat",
        "version": 1,
        "title": {"en": "field-list and repeat"},
        "defaultLanguage": "en",
        "languages": ["en"],
        "children": children,
    }


ROSTER = {
    "type": "repeat",
    "id": "members",
    "label": {"en": "Members"},
    "children": [{"type": "question", "id": "nm", "dataType": "text",
                  "label": {"en": "Name"}}],
}


def test_a_repeat_inside_a_field_list_group_is_refused() -> None:
    """Not a trade — a contradiction.

    `field-list` means these questions appear together on one screen; a repeat
    means a separate screen you enter and leave (§11.3). Both cannot be true of
    the same subtree, so the refusal states what is already the case rather than
    choosing between two workable behaviours.
    """
    ir = _form([
        {"type": "group", "id": "fl", "label": {"en": "Field list"},
         "appearance": "field-list",
         "children": [
             {"type": "question", "id": "a", "dataType": "text", "label": {"en": "A"}},
             ROSTER,
         ]},
    ])
    with pytest.raises(CompileError) as raised:
        CompiledForm(ir)
    assert "field-list" in str(raised.value)
    # Names both ends, so an author can find it in a workbook of any size.
    assert "members" in str(raised.value) and "fl" in str(raised.value)


def test_the_refusal_reaches_through_a_nested_plain_group() -> None:
    """The half a shallow check would miss.

    §11.1 flattens nested plain groups into the field-list screen, so a repeat
    two levels down is inside the field-list exactly as much as one directly in
    it. A check that looked only at the immediate parent would let this through
    and drop the roster's questions silently, which is defect 14 again.
    """
    ir = _form([
        {"type": "group", "id": "fl", "label": {"en": "Field list"},
         "appearance": "field-list",
         "children": [
             {"type": "group", "id": "inner", "label": {"en": "Inner"},
              "children": [ROSTER]},
         ]},
    ])
    with pytest.raises(CompileError, match="field-list"):
        CompiledForm(ir)


def test_a_repeat_beside_a_field_list_group_is_fine() -> None:
    """The refusal is about containment and nothing wider.

    Without this, a check that refused any form holding both would pass the two
    above and be wrong about every real questionnaire — RCons's has 95 sections
    and a roster.
    """
    ir = _form([
        {"type": "group", "id": "fl", "label": {"en": "Field list"},
         "appearance": "field-list",
         "children": [{"type": "question", "id": "a", "dataType": "text",
                       "label": {"en": "A"}}]},
        ROSTER,
    ])
    compiled = CompiledForm(ir)
    plan = build_screen_plan(ir)

    assert "members" in compiled.repeats
    assert [s.kind for s in plan.screens] == ["questions", "repeat"]
    assert plan.askable_question_ids() == {"a", "nm"}


def test_a_repeat_inside_a_plain_group_is_fine() -> None:
    """A plain group contributes no screen of its own (§11.1), so it makes no
    promise a repeat can contradict."""
    ir = _form([
        {"type": "group", "id": "plain", "label": {"en": "Plain"},
         "children": [ROSTER]},
    ])
    plan = build_screen_plan(ir)
    assert [s.kind for s in plan.screens] == ["repeat"]
    assert plan.screens[0].section_id == "plain"
