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


def _generated() -> list[dict[str, Any]]:
    """Every operator against every other, nested both ways.

    The corpus is real forms, and real forms do not contain `${a} - (${b} -
    ${c})` or `(${a} + ${b}) div 2`. Two breaks proved it: printing `div` at
    multiplicative precedence, and rendering a right operand at its parent's
    level instead of one tighter, both passed the whole corpus. Neither is
    exotic — they are the two mistakes a precedence table invites — and a
    property test that cannot see them is testing the forms rather than the
    ladder.

    So this is a cross product rather than a selection, for the same reason
    `conformance/functions` is (break 46): the shapes nobody wrote down are
    exactly the ones a hand-picked list is missing.
    """
    from app.modules.forms.expression_text import _BINARY

    ref_a = {"op": "ref", "path": "a"}
    ref_b = {"op": "ref", "path": "b"}
    ref_c = {"op": "ref", "path": "c"}

    out: list[dict[str, Any]] = []
    for outer in _BINARY:
        for inner in _BINARY:
            # Left-nested and right-nested. The right-nested case is the one
            # that needs the parentheses a left-associative parser would
            # otherwise drop.
            out.append({"op": outer, "args": [{"op": inner, "args": [ref_a, ref_b]}, ref_c]})
            out.append({"op": outer, "args": [ref_a, {"op": inner, "args": [ref_b, ref_c]}]})
        # Unary under a binary, and a binary under a unary.
        out.append({"op": outer, "args": [{"op": "neg", "args": [ref_a]}, ref_b]})
        out.append({"op": "neg", "args": [{"op": outer, "args": [ref_a, ref_b]}]})
        out.append({"op": "not", "args": [{"op": outer, "args": [ref_a, ref_b]}]})
        # A call's arguments are always parenthesised by the call itself, so a
        # binary inside one must survive without extra parens.
        out.append({"op": "call", "fn": "round", "args": [{"op": outer, "args": [ref_a, ref_b]}]})
    return out


CORPUS = _corpus() + _generated()


def test_the_corpus_has_expressions_to_check() -> None:
    """A property test over an empty corpus passes and proves nothing."""
    assert len(CORPUS) > 200, f"only {len(CORPUS)} expressions found"
    # The generated half must actually be there: a cross product that silently
    # produced nothing would leave this test passing on the corpus alone,
    # which is the state two breaks already walked through.
    assert len(_generated()) > 300, "the generated ladder is missing"


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
