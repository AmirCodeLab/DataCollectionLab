"""A repeat's instance list is in creation order.

No conformance vector can reach this. A vector fixes the inputs and compares the
outputs; this is an assertion about the engine's own internal state, and the way
to violate it is to reorder `FormInstance.instances` directly — which the vector
format has no step for and never will. So it is watched here and in
`shared/form-engine/.../InstanceOrderTest.kt`, one per engine.

Why it matters takes two of spec 2.3's sentences together, and neither says it
on its own: shrinking a `countExpr` repeat "discards the trailing instances",
and the shrink implements that by popping the END of the list. That is only the
trailing instance while the list is in creation order. Break 75 is what the
other outcome looks like — the count stays right and somebody else's answers are
destroyed, with nothing on any screen to see.

The `restore` cases are Python-only on purpose: the Kotlin engine has no
restore, because rebuilding a submission from the op log is something only the
server does.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.modules.form_engine.runtime import (
    SERIAL_ID,
    CompiledForm,
    CompileError,
    FormInstance,
)

IR = {
    "irVersion": "0.1",
    "formId": "order",
    "version": 1,
    "title": {"en": "order"},
    "defaultLanguage": "en",
    "languages": ["en"],
    "children": [
        {"type": "question", "id": "n", "dataType": "integer", "label": {"en": "How many"}},
        {
            "type": "repeat",
            "id": "members",
            "label": {"en": "Members"},
            "countExpr": {"op": "ref", "path": "n"},
            "children": [
                {"type": "question", "id": "name", "dataType": "text", "label": {"en": "Name"}}
            ],
        },
    ],
}

PLAIN_IR = {
    **IR,
    "formId": "order_plain",
    "children": [
        {"type": "question", "id": "n", "dataType": "integer", "label": {"en": "How many"}},
        {
            "type": "repeat",
            "id": "members",
            "label": {"en": "Members"},
            "children": [
                {"type": "question", "id": "name", "dataType": "text", "label": {"en": "Name"}}
            ],
        },
    ],
}


def three_members() -> FormInstance:
    instance = FormInstance(CompiledForm(IR), today=date(2026, 8, 28))
    instance.set_many({"n": 3})
    instance.set_many(
        {"members[0].name": "A", "members[1].name": "B", "members[2].name": "C"}
    )
    return instance


def test_a_reordered_instance_list_is_refused_rather_than_silently_shrunk() -> None:
    instance = three_members()
    assert len(instance.instances["members"]) == 3

    instance.instances["members"].reverse()

    with pytest.raises(CompileError) as raised:
        instance.set_many({"n": 2})

    assert "not in creation order" in str(raised.value)
    assert "members" in str(raised.value)


def test_the_same_shrink_discards_the_trailing_member_when_the_order_holds() -> None:
    """The control. Without the reorder the shrink is ordinary and correct."""
    instance = three_members()
    first, second, _third = instance.instances["members"]

    instance.set_many({"n": 2})

    assert instance.instances["members"] == [first, second]
    answers = instance.answers()
    assert answers[f"members[{first}].name"] == "A"
    assert answers[f"members[{second}].name"] == "B"


def test_a_swap_of_two_adjacent_instances_is_caught_not_only_a_full_reversal() -> None:
    instance = three_members()
    ordered = instance.instances["members"]
    ordered[0], ordered[1] = ordered[1], ordered[0]

    with pytest.raises(CompileError):
        instance.set_many({"n": 2})


def test_restore_refuses_minted_ids_handed_back_out_of_order() -> None:
    """The case that can actually happen.

    `restore` takes its order from a caller — `fold_ops` reads the op log in
    `(counter, device_id)` order precisely because JSONB does not preserve key
    order. A caller that loses that order hands a roster back shuffled, and the
    export then reports the wrong person against every stable id.
    """
    instance = FormInstance(CompiledForm(PLAIN_IR), today=date(2026, 8, 28))

    with pytest.raises(CompileError) as raised:
        instance.restore(instances={"members": ["i3", "i1", "i2"]}, answers={})

    assert "not in creation order" in str(raised.value)


def test_restore_in_creation_order_is_accepted() -> None:
    """The control for the one above."""
    instance = FormInstance(CompiledForm(PLAIN_IR), today=date(2026, 8, 28))

    unplaced = instance.restore(
        instances={"members": ["i1", "i2", "i3"]},
        answers={"members[i2].name": "B"},
    )

    assert unplaced == ()
    assert instance.instances["members"] == ["i1", "i2", "i3"]
    assert instance.answers()["members[i2].name"] == "B"


def test_ids_from_another_minter_are_left_alone() -> None:
    """The caller boundary, stated as a test rather than a comment.

    An id this engine did not mint carries no readable ordinal, so the caller's
    order is all there is and the assertion must not invent a violation. That is
    the boundary docs/project-conventions.md describes: what a caller chose is
    not something an assertion inside the engine can check.
    """
    instance = FormInstance(CompiledForm(PLAIN_IR), today=date(2026, 8, 28))

    unplaced = instance.restore(
        instances={"members": ["uuid-c", "uuid-a", "uuid-b"]}, answers={}
    )

    assert unplaced == ()
    assert instance.instances["members"] == ["uuid-c", "uuid-a", "uuid-b"]


def test_every_id_this_engine_mints_is_one_the_order_assertion_can_read() -> None:
    """The guard against the guard going dark.

    `_assert_creation_order` reads its ordinal off the id and returns **silently**
    for an id it cannot parse. That is correct — an id from another minter has no
    ordinal to read, and the caller's order is the only claim there is — but it
    is also a state in which the assertion sees nothing at all. If this engine's
    own id scheme ever stopped being `i<n>`, every list would become unreadable
    to it and the ordering invariant would keep passing while checking nothing.

    So this asserts the **link** rather than the format: every id the engine
    mints must be one the assertion can read an ordinal from. The check belongs
    here, on the minter, and not inside the assertion — an assertion cannot tell
    "this id is foreign, stand down" from "every id is foreign because the scheme
    changed", because from inside it those are the same observation.

    Break 78 is the asymmetry: change the id scheme and this fails while every
    ordering test above stays green.
    """
    instance = FormInstance(CompiledForm(PLAIN_IR), today=date(2026, 8, 28))

    minted = [instance.add_instance("members") for _ in range(3)]

    for instance_id in minted:
        assert SERIAL_ID.fullmatch(instance_id) is not None, (
            f"the engine minted {instance_id!r}, which _assert_creation_order "
            "cannot read an ordinal from. The ordering invariant would go dark: "
            "it would return early on every list and never raise again."
        )
    assert minted == ["i1", "i2", "i3"], (
        "ids are minted sequentially from 1; the serial IS the creation ordinal"
    )
