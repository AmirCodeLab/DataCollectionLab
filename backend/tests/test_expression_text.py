"""`parse(render(node)) == node`, over every expression in the corpus.

Form IR Appendix A is a **surface**, not a second definition of what an
expression means, and this is the property that keeps it one. There is no
conformance vector for it and there should not be: both engines consume AST,
neither parses text, so there is nothing to compare between two
implementations — only one exists by construction.

What replaces the vector is this. Examples chosen by hand test the shapes
somebody thought of, which is the limitation the function matrix exists to work
around one layer up (break 46). The corpus is every expression the engine is
actually asked to evaluate, so the ladder is exercised by the forms rather than
by a list.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from app.modules.forms.expression_text import RenderError, parse, render

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: The keys of a node whose value is an expression, per §4.1 and §7.1.
_EXPRESSION_KEYS = (
    "relevant",
    "constraint",
    "calculate",
    "required",
    "readOnly",
    "default",
    "countExpr",
    "filter",
)
_EXPRESSION_LISTS = ("labelArgs", "constraintMessageArgs", "summaryLabelArgs")


def _expressions(node: Any, found: list[dict[str, Any]]) -> None:
    if isinstance(node, dict):
        for key in _EXPRESSION_KEYS:
            value = node.get(key)
            if isinstance(value, dict) and "op" in value:
                found.append(value)
        for key in _EXPRESSION_LISTS:
            for value in node.get(key) or []:
                if isinstance(value, dict) and "op" in value:
                    found.append(value)
        for value in node.values():
            _expressions(value, found)
    elif isinstance(node, list):
        for value in node:
            _expressions(value, found)


def _subexpressions(node: dict[str, Any]) -> list[dict[str, Any]]:
    """Every node in the tree, so the ladder is tested at depth, not only at the root."""
    out = [node]
    for arg in node.get("args") or []:
        if isinstance(arg, dict) and "op" in arg:
            out.extend(_subexpressions(arg))
    return out


def _corpus() -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for directory in ("vectors", "sensitivity", "malformed"):
        for path in sorted((ROOT / "conformance" / directory).glob("*.json")):
            try:
                document = json.loads(path.read_text())
            except json.JSONDecodeError:
                continue  # malformed/ holds documents that are not JSON on purpose
            _expressions(document.get("form"), found)
    deep: list[dict[str, Any]] = []
    for node in found:
        deep.extend(_subexpressions(node))
    return deep


CORPUS = _corpus()


def test_the_corpus_has_expressions_to_check() -> None:
    """A property test over an empty corpus passes and proves nothing."""
    assert len(CORPUS) > 200, f"only {len(CORPUS)} expressions found"


@pytest.mark.parametrize("node", CORPUS, ids=lambda n: n.get("op", "?"))
def test_every_expression_survives_a_round_trip(node: dict[str, Any]) -> None:
    try:
        text = render(node)
    except RenderError as exc:
        # `in` has no surface spelling, deliberately — the printer says so
        # rather than inventing one. Anything else is a gap.
        assert "no surface syntax" in str(exc) or "no surface form" in str(exc), exc
        return
    # A `$row.` reference is a candidate row's column and is spelled as a bare
    # name — the one place XLSForm gives a bare name a meaning (§3.2). It has a
    # surface only inside a choice filter, so it is parsed back in that scope.
    row_scope = "$row." in json.dumps(node)
    assert parse(text, row_scope=row_scope) == node, (
        f"{node!r} rendered as {text!r} and came back different"
    )
