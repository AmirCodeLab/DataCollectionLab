"""§10.2's four `rowSource` refusals, on both engines (Form IR §2.3).

**No vector reaches these.** Every case in `conformance/vectors` is a form plus
an ordered list of steps, and every step assumes a form that compiled — the
format cannot say "this document must be refused". `conformance/malformed`
covers §10.1 and `conformance/sensitivity` covers exactly one §10.2 rule; the
rest of §10.2 is held by a test in each engine and nothing else.

That is a real exposure and it is named here rather than left to be discovered:
two engines that disagree about which forms compile is a form author meeting a
refusal their builder told them was not there. The Kotlin half is
`RowSourceRefusalTest` in `shared/form-engine/src/jvmTest`, and the two must be
changed together.

**One of these four is expected to be deleted.** `kind: "dataset"` is not
malformed and not ambiguous — it is specified, and two things it depends on do
not exist (§2.3, *What is live*). Its test asserts that its message says so,
because a form author who wrote a valid preloaded roster needs to read "not
built yet" rather than "your form is wrong".
"""

from __future__ import annotations

import pytest

from app.modules.form_engine.runtime import CompiledForm, CompileError

PRACTICES = [
    {"value": "zero_till", "label": {"en": "Zero tillage"}},
    {"value": "laser_lvl", "label": {"en": "Laser levelling"}},
]


def _form(repeat: dict) -> dict:
    return {
        "irVersion": "0.1",
        "formId": "row_source",
        "version": 1,
        "title": {"en": "rowSource"},
        "defaultLanguage": "en",
        "languages": ["en"],
        "children": [
            {"type": "question", "id": "hh", "dataType": "text", "label": {"en": "Hh"}},
            repeat,
        ],
    }


def _repeat(row_source: dict | None = None, **kw) -> dict:
    node = {
        "type": "repeat",
        "id": "practices",
        "label": {"en": "Practices"},
        "children": [
            {"type": "question", "id": "practice", "dataType": "text",
             "label": {"en": "Practice"}},
        ],
    }
    if row_source is not None:
        node["rowSource"] = row_source
    node.update(kw)
    return node


def _inline(**kw) -> dict:
    return {"kind": "inline", "items": PRACTICES, **kw}


def test_a_valid_inline_row_source_compiles() -> None:
    """The control. Without it every assertion below passes on a broken parser.

    Three of the four refusals are about a form that is *nearly* this one, so a
    compiler that refused all `rowSource` nodes would satisfy them and fail a
    customer.
    """
    compiled = CompiledForm(_form(_repeat(_inline(bind={"practice": "value"}))))
    assert "practices" in compiled.repeats


def test_count_expr_and_row_source_together_are_refused() -> None:
    """countExpr says how many, rowSource says which — and nothing arbitrates."""
    with pytest.raises(CompileError) as caught:
        CompiledForm(_form(_repeat(_inline(), countExpr={"op": "lit", "value": 3})))
    assert "countExpr" in str(caught.value) and "rowSource" in str(caught.value)


def test_a_bind_reaching_outside_its_repeat_is_refused() -> None:
    """`hh` is a real question, and it is not per-row. Naming a field that does
    not exist at all would be caught by reference resolution and would prove
    nothing about this rule."""
    with pytest.raises(CompileError) as caught:
        CompiledForm(_form(_repeat(_inline(bind={"hh": "value"}))))
    assert "hh" in str(caught.value)


def test_binding_an_inline_label_is_refused() -> None:
    """A label is §7 i18n and an answer is one value in no language.

    Refused rather than defaulted to the form's default language: two engines
    choosing a language is two forms, and the failure would be invisible until
    somebody opened the form in Urdu.
    """
    with pytest.raises(CompileError) as caught:
        CompiledForm(_form(_repeat(_inline(bind={"practice": "label"}))))
    assert "label" in str(caught.value)


def test_binding_a_column_an_inline_row_does_not_have_is_refused() -> None:
    with pytest.raises(CompileError) as caught:
        CompiledForm(_form(_repeat(_inline(bind={"practice": "age"}))))
    assert "age" in str(caught.value)


def test_a_dataset_row_source_is_refused_and_says_why_it_is_not_built() -> None:
    """The refusal expected to be deleted, and the only one whose *wording* is
    asserted here.

    §10.2 requires this message to read differently from the other three: the
    form is valid and the platform is not ready. An author who wrote a correct
    preloaded roster and read "invalid rowSource" would go and change a form
    that has nothing wrong with it.
    """
    with pytest.raises(CompileError) as caught:
        CompiledForm(_form(_repeat({
            "kind": "dataset",
            "dataset": "hh_members",
            "bind": {"practice": "name"},
        })))
    message = str(caught.value)
    assert "not yet implemented" in message
    assert "case_key" in message, "name the dependency, not just the refusal"
    assert "16" in message, "point at the defect holding the other half"


def test_an_unknown_row_source_kind_is_refused() -> None:
    with pytest.raises(CompileError):
        CompiledForm(_form(_repeat({"kind": "sample", "items": PRACTICES})))
