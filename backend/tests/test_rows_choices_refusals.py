"""§10.2's two refusals for a `rows` choice list (Form IR §3.3).

**No vector reaches these.** Every case in `conformance/vectors` is a form plus
an ordered list of steps, and every step assumes a form that compiled — the
format cannot say "this document must be refused". `conformance/malformed`
covers §10.1 and `conformance/sensitivity` covers exactly one §10.2 rule; the
rest of §10.2, these two included, is held by a test in each engine and nothing
else.

That is a real exposure and it is named here rather than left to be discovered:
two engines that disagree about which forms compile is a form author meeting a
refusal their builder told them was not there. The Kotlin half is
`RowsChoicesRefusalTest` in `shared/form-engine/src/jvmTest`, and the two must
be changed together.
"""

from __future__ import annotations

import pytest

from app.modules.form_engine.runtime import CompiledForm, CompileError

MEMBERS_CHILDREN = [
    {"type": "question", "id": "name", "dataType": "text", "label": {"en": "Name"}},
]


def _form(children: list[dict]) -> dict:
    return {
        "irVersion": "0.1",
        "formId": "rows_refusal",
        "version": 1,
        "title": {"en": "rows"},
        "defaultLanguage": "en",
        "languages": ["en"],
        "children": children,
    }


def _roster(children: list[dict]) -> dict:
    return {
        "type": "repeat",
        "id": "members",
        "label": {"en": "Members"},
        "summaryLabel": {"en": "{0}"},
        "summaryLabelArgs": [{"op": "ref", "path": "name"}],
        "allowAdd": True,
        "allowDelete": True,
        "children": MEMBERS_CHILDREN + children,
    }


def _mother(**choices: object) -> dict:
    return {
        "type": "question",
        "id": "mother",
        "dataType": "select_one",
        "label": {"en": "Mother"},
        "choices": {"kind": "rows", "repeat": "members", **choices},
    }


def test_exclude_self_outside_its_own_repeat_is_refused() -> None:
    """There is no "self" to exclude, so the flag could only be a no-op.

    `docs/project-conventions.md` calls this shape two claims wearing one
    assertion: a control that appears to do something and does nothing is
    indistinguishable, to an author, from one that works. The author either
    named the wrong repeat or put the question in the wrong place, and both are
    worth being told.
    """
    ir = _form([_roster([]), _mother(excludeSelf=True)])

    with pytest.raises(CompileError) as refusal:
        CompiledForm(ir)

    assert "excludeSelf" in str(refusal.value)
    assert "members" in str(refusal.value)


def test_the_same_question_inside_the_repeat_compiles() -> None:
    """The other half of the rule, and the reason it is not simply "no flag".

    MICS6 HL14 is asked **on the member's own row**, which is exactly where the
    flag means something. A test that only proved the refusal would pass on an
    engine that refused `excludeSelf` everywhere.
    """
    ir = _form([_roster([_mother(excludeSelf=True)])])

    compiled = CompiledForm(ir)

    assert compiled.fields["mother"].rows_query is not None
    assert compiled.fields["mother"].rows_query.exclude_self is True


def test_a_rows_list_over_something_that_is_not_a_repeat_is_refused() -> None:
    """An unresolvable reference, and one `_check_references` cannot see.

    That check walks `depends_on`, which holds field ids; a repeat id is not a
    field, so a list naming `household` — a group, or nothing at all — would
    otherwise compile and resolve to an empty list on every device, with
    nothing in an error state.
    """
    ir = _form([
        _roster([]),
        {
            "type": "question",
            "id": "mother",
            "dataType": "select_one",
            "label": {"en": "Mother"},
            "choices": {"kind": "rows", "repeat": "household"},
        },
    ])

    with pytest.raises(CompileError) as refusal:
        CompiledForm(ir)

    assert "household" in str(refusal.value)


def test_a_rows_list_with_no_summary_label_warns_rather_than_refusing() -> None:
    """§10.3: the list is legal, correct, and a row of bare position numbers.

    A warning rather than an error because the spec permits the document — and
    worth making at all because it stopped being a limitation when
    `summaryLabelArgs` got an editor and became an authoring choice.
    """
    roster = _roster([])
    del roster["summaryLabel"]
    del roster["summaryLabelArgs"]

    compiled = CompiledForm(_form([roster, _mother()]))

    assert compiled.warnings == [
        "mother: chooses from the rows of repeat 'members', which has no "
        "summaryLabel, so the options are position numbers"
    ]
