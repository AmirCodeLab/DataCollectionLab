"""The exporter cannot reach a non-relevant field's retained value.

Form IR §4.4 keeps a non-relevant answer in storage and excludes it from export,
and `FormInstance` holds both halves: `values` is the retained one, `answers()`
is the exported one. Reaching for the wrong one produces a file in which every
count is right, every type is right, every test passes, and a household that
said "no children" reports the three it had typed before changing its mind.

Item 5 says it would bet on this mistake, and the reason is that `values` is the
obvious thing to reach for while `answers()` is the correct one, and nothing
about the wrong choice looks wrong. So it is made unexpressible rather than
tested for, the same way `compiledFormForSubmission` takes no version and
`dataset_rows_for` takes none either:

  - `form_engine/projection.py` is the only door. It builds the `FormInstance`,
    reads `answers()`, and returns a frozen value object; the instance is a
    local and never escapes, so nothing downstream has a `values` to reach for.
  - This file is the lint that keeps the door shut. There are three ways back
    through it — naming `values` or `states` or `snapshot()`, constructing a
    `FormInstance` of your own, and asking `answers(include_irrelevant=True)`,
    which is `values` spelled differently — and all three are refused here.

`test_no_session_generator_loops.py` is the same kind of guard for the same kind
of reason: a rule that only holds while everyone remembers it is not a rule.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]

#: Every module on the export path, including the engine's own door. The door
#: is in the list deliberately: it is the one place allowed to hold a
#: `FormInstance`, and it is also the easiest place to widen by accident.
WATCHED = [
    *sorted((BACKEND / "app" / "modules" / "export").rglob("*.py")),
    BACKEND / "app" / "modules" / "form_engine" / "projection.py",
]

#: Attribute names that hand back retained answers. `values` is the direct
#: route; `states` carries the same values with their flags; `snapshot` is
#: `states` serialised.
FORBIDDEN_ATTRIBUTES = {"values", "states", "snapshot"}

#: `answers(include_irrelevant=True)` is `values` under another name, and it is
#: the one a reader would not think twice about.
FORBIDDEN_KEYWORD = "include_irrelevant"

#: `projection.py` is the door and constructs one. Nothing else may.
MAY_CONSTRUCT_A_FORM_INSTANCE = {"projection.py"}


def _watched() -> list[tuple[Path, ast.Module]]:
    return [(path, ast.parse(path.read_text())) for path in WATCHED if path.is_file()]


def test_there_is_something_to_check() -> None:
    """A guard over an empty list is green paperwork over nothing."""
    names = {path.name for path in WATCHED if path.is_file()}
    assert "projection.py" in names
    assert len(names) >= 6, f"only found {sorted(names)}"


def test_nothing_on_the_export_path_names_a_retained_value() -> None:
    """`x.values` as an expression. `d.values()` — a call — is a plain dict."""
    found: list[str] = []
    for path, tree in _watched():
        calls = {
            id(node.func)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            if node.attr not in FORBIDDEN_ATTRIBUTES or id(node) in calls:
                continue
            found.append(f"{path.name}:{node.lineno} reads .{node.attr}")

    assert not found, (
        "the export path must read `answers()` and nothing else (Form IR §4.4): "
        + "; ".join(found)
    )


def test_nothing_asks_for_the_irrelevant_answers_by_keyword() -> None:
    found: list[str] = []
    for path, tree in _watched():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg == FORBIDDEN_KEYWORD:
                    found.append(f"{path.name}:{node.lineno}")

    assert not found, (
        f"`{FORBIDDEN_KEYWORD}=True` is `values` spelled differently, and it is "
        "the one that would not look wrong: " + "; ".join(found)
    )


def test_only_the_projection_may_build_a_form_instance() -> None:
    """One door. A second `FormInstance` is a second answer about relevance."""
    found: list[str] = []
    for path, tree in _watched():
        if path.name in MAY_CONSTRUCT_A_FORM_INSTANCE:
            continue
        for node in ast.walk(tree):
            named = (
                isinstance(node, ast.Name) and node.id == "FormInstance"
            ) or (isinstance(node, ast.Attribute) and node.attr == "FormInstance")
            if named:
                found.append(f"{path.name}:{node.lineno}")

    assert not found, (
        "only `form_engine/projection.py` may hold a `FormInstance`; everything "
        "else takes the projection it returns: " + "; ".join(found)
    )


@pytest.mark.parametrize(
    "source",
    [
        "x = instance.values",
        "x = instance.states",
        "x = instance.snapshot",
        "x = form.answers(include_irrelevant=True)",
    ],
)
def test_the_lint_would_notice(source: str) -> None:
    """The instrument, checked before the negative it reports is believed.

    A guard that says "nothing was found" passes just as cheerfully when it is
    looking at nothing. `docs/known-breaks.md` has a note on exactly this: break
    6 nearly reported a leak-free console about a channel it could not observe.
    """
    tree = ast.parse(source)
    calls = {
        id(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    attributes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr in FORBIDDEN_ATTRIBUTES
        and id(node) not in calls
    ]
    keywords = [
        keyword
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == FORBIDDEN_KEYWORD
    ]
    assert attributes or keywords, f"the lint cannot see {source!r}"


def test_a_plain_dict_values_call_is_not_flagged() -> None:
    """The other direction: the guard must not forbid ordinary Python.

    A guard that fires on `mapping.values()` gets worked around, and a worked-
    around guard is worse than none.
    """
    tree = ast.parse("for v in mapping.values():\n    pass\n")
    calls = {
        id(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    flagged = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr in FORBIDDEN_ATTRIBUTES
        and id(node) not in calls
    ]
    assert not flagged
