"""The publish gate refuses a question no client can present.

This is the guard for `docs/known-defects.md` 28, closed 12 September 2026. The
defect was not that the check was missing — the XLSForm importer has refused a
`time` question by name since the registry existed — but that it was the
**importer's** and nobody else's. A form authored in the console never runs the
importer, and neither does `POST /forms/versions`, so the identical document
the importer refused published and deployed. It happened on the Sindh-scale run
(`docs/scale-run-2026-09-12-sindh.md` §5.1): 2,128 questions, three of them
unpresentable, 201 Created and live in two environments.

No conformance vector can express this and none should try. §10 is a statement
about a document, true wherever it is read, which is why both engines implement
it. Collectability is a statement about an **app version** — the registry is
`specs/collectable-types-v0.1.json` and is versioned for that reason — so there
is nothing for two engines to agree about and the Kotlin engine has no publish
gate to disagree in. What holds the Android client to the same file is
`CollectableTypesTest`; this holds the server to it.

The first test is the break, and it is the one that matters: it is the document
the run actually published.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.forms.collectability import check_collectability
from app.modules.forms.service import PublishRefused, check_publishable


def _form(*questions: dict[str, Any]) -> dict[str, Any]:
    return {
        "irVersion": "0.1",
        "formId": "collectability",
        "version": 1,
        "title": {"en": "collectability"},
        "defaultLanguage": "en",
        "languages": ["en"],
        "children": list(questions),
    }


def _question(qid: str, data_type: str, **extra: Any) -> dict[str, Any]:
    node: dict[str, Any] = {
        "type": "question",
        "id": qid,
        "dataType": data_type,
        "label": {"en": qid},
    }
    node.update(extra)
    return node


def test_the_gate_refuses_the_three_types_the_scale_run_published() -> None:
    """Two `time` questions and a `geoshape`, which is what actually shipped."""
    form = _form(
        _question("asked_at", "time"),
        _question("head_name", "text"),
        _question("structure_outline", "geoshape"),
        _question("left_at", "time"),
    )

    with pytest.raises(PublishRefused) as refusal:
        check_publishable(form)

    violations = refusal.value.violations
    assert len(violations) == 3
    assert [v.split("`")[1] for v in violations] == [
        "asked_at",
        "structure_outline",
        "left_at",
    ], "document order, so an author fixes them top to bottom"
    assert "no client can present it yet" in violations[0]
    assert "collectable types v" in violations[0], (
        "the registry is versioned; a refusal that does not say which version "
        "refused is unanswerable on a self-hosted install"
    )


def test_a_form_of_collectable_types_publishes() -> None:
    """The other half, because a gate that refuses everything also passes the
    test above."""
    form = _form(
        _question("head_name", "text"),
        _question("hh_size", "integer"),
        _question("interview_date", "date"),
        _question(
            "owns_land",
            "select_one",
            choices={"kind": "inline", "items": [{"value": "yes"}, {"value": "no"}]},
        ),
        _question("dwelling", "geopoint"),
        _question("photo", "image"),
    )
    compiled = check_publishable(form)
    assert len(compiled.fields) == 6


def test_a_calculate_is_not_refused_for_a_type_nobody_would_see() -> None:
    """§11.1: a calculate is computed and never drawn.

    It gets no screen from `build_screen_plan` and is not counted by
    `reachability._answerable`, so refusing a form because a value nobody is
    ever shown has a type nobody can present would be a refusal with no failure
    behind it. The inverse is the live risk and is why this is a test rather
    than a comment: the obvious implementation walks every question node.
    """
    form = _form(
        _question("head_name", "text"),
        _question(
            "recorded_at",
            "datetime",
            calculate={"op": "now", "args": []},
        ),
    )
    assert check_collectability(form) == []
    check_publishable(form)  # must not raise


def test_a_question_inside_a_group_and_a_repeat_is_reached() -> None:
    """Containers are walked through.

    A check that only looked at top-level children would pass a form whose
    unpresentable question is inside the roster — which, on a household
    listing, is where most questions are.
    """
    form = _form(
        _question("hh_size", "integer"),
        {
            "type": "group",
            "id": "section_a",
            "label": {"en": "A"},
            "children": [_question("arrived_at", "time")],
        },
        {
            "type": "repeat",
            "id": "members",
            "label": {"en": "Members"},
            "children": [
                _question("member_name", "text"),
                _question("member_born_at", "datetime"),
            ],
        },
    )
    violations = check_collectability(form)
    assert [v.split("`")[1] for v in violations] == ["arrived_at", "member_born_at"]


def test_the_importer_and_the_gate_say_the_same_sentence() -> None:
    """One definition of the refusal, because two was how they came to differ.

    The importer adds a cell reference and a remedy — a builder has neither —
    but the sentence itself comes from `forms.collectability`. If this fails,
    the two gates have started describing the same refusal differently, which
    is the visible half of them deciding it differently.
    """
    from app.modules.forms.collectability import uncollectable_type_message
    from app.modules.forms.xlsform import datatypes
    from app.modules.forms.xlsform.importer import collectability_message

    version = datatypes.collectable_types_version()
    assert collectability_message("q", "time", version) == uncollectable_type_message(
        "q", "time", version
    )
