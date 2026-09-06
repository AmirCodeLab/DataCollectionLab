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
import math
import pathlib
import random
import struct
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
    back = parse(text, row_scope=row_scope)
    assert _same(back, node), f"{node!r} rendered as {text!r} and came back as {back!r}"


def _same(a: Any, b: Any) -> bool:
    """Structural equality that keeps `800` and `800.0` apart.

    `==` does not: `{"value": 800.0} == {"value": 800}` is true in Python, so a
    printer that dropped the `.0` — as §4.3.1's `str()` does, on purpose, for
    labels — would pass a round trip that compared with `==` while turning a
    decimal literal into an integer on every save. Appendix A.4 says the two
    are different renderings for different purposes; this is the assertion
    that keeps them so.
    """
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, int | float) or isinstance(b, int | float):
        return type(a) is type(b) and a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b, strict=True))
    return a == b


#: A number, and the text A.4 says it is written as. The shortest digits that
#: read back as the same value, positionally — the grammar has no exponent —
#: and with the `.0` a decimal needs to stay a decimal.
_NUMBERS = [
    (0.30000000000000004, "0.30000000000000004"),
    (0.1 + 0.2, "0.30000000000000004"),
    (800.0, "800.0"),
    (1.0, "1.0"),
    (0.5, "0.5"),
    (3.14, "3.14"),
    (1e-7, "0.0000001"),
    (2.5e-5, "0.000025"),
    (1e16, "10000000000000000.0"),
    (1.2345678901234568e17, "123456789012345680.0"),
    (9999999999999998.0, "9999999999999998.0"),
    (5, "5"),
    (0, "0"),
    (10**15, "1000000000000000"),
    (2**62, "4611686018427387904"),
]


@pytest.mark.parametrize(("value", "text"), _NUMBERS, ids=lambda v: repr(v))
def test_a_number_is_written_as_exactly_itself(value: int | float, text: str) -> None:
    """A.4: the code field is not `str()`. `800.0` stays `800.0`, and
    `0.30000000000000004` keeps every digit, because the text an author saves
    back is the value the form runs on."""
    node = {"op": "lit", "value": value}
    assert render(node) == text
    back = parse(text)
    assert _same(back, node), f"{text!r} came back as {back!r}"


@pytest.mark.parametrize("value", [-5, -17, -0.0075, -0.0, -1e-7], ids=repr)
def test_a_negative_number_reads_back_as_the_negation(value: int | float) -> None:
    """A.4: the surface has no negative literal. `-5` is `neg` of `5`, which is
    what the importer produces and what §4.4 evaluates to the same value, so
    this is the one node whose round trip keeps the value and not the shape."""
    node = {"op": "lit", "value": value}
    text = render(node)
    assert not text.startswith("(")
    back = parse(text)
    assert _same(back, {"op": "neg", "args": [{"op": "lit", "value": -value}]}), back
    # And it keeps that shape from then on.
    assert _same(parse(render(back)), back)


def test_a_negative_number_under_an_operator_keeps_its_place() -> None:
    a = {"op": "ref", "path": "a"}
    minus_five = {"op": "lit", "value": -5}
    expected = {"op": "neg", "args": [{"op": "lit", "value": 5}]}
    for node, want in (
        ({"op": "sub", "args": [a, minus_five]}, {"op": "sub", "args": [a, expected]}),
        ({"op": "mul", "args": [minus_five, a]}, {"op": "mul", "args": [expected, a]}),
        ({"op": "neg", "args": [minus_five]}, {"op": "neg", "args": [expected]}),
    ):
        text = render(node)
        assert _same(parse(text), want), f"{node!r} rendered as {text!r}"


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")], ids=repr)
def test_a_number_that_is_not_finite_has_no_surface_form(value: float) -> None:
    with pytest.raises(RenderError, match="no surface form"):
        render({"op": "lit", "value": value})


# --- Properties over generated values --------------------------------------
#
# A.4 is normative about the round trip, and a normative rule needs a property
# test rather than the cases somebody thought of. Seven hand-picked numbers is
# what this file had when the printer looked correct; a generator is what would
# have found `1e+16` without anyone thinking of it first. No hypothesis
# dependency — a seeded `random` is enough, and the seed is in the failure
# message so a case can be replayed.

_SEED = 20260906
_INT64 = 2**63


def _random_numbers(rng: random.Random, count: int) -> list[int | float]:
    """Numbers from every region a float or a 64-bit integer has.

    Random bit patterns reach the subnormals and the huge magnitudes that a
    uniform draw never touches; log-uniform draws cover the middle; the
    boundaries — the float mantissa edge, the ends of the integer range — are
    where an int and a float stop being interchangeable.
    """
    out: list[int | float] = [
        0,
        0.0,
        -0.0,
        5e-324,
        -5e-324,
        2.2250738585072014e-308,
        1.7976931348623157e308,
        -1.7976931348623157e308,
        2**53 - 1,
        2**53,
        2**53 + 1,
        float(2**53),
        float(2**53) + 2,
        _INT64 - 1,
        -_INT64,
        float(_INT64),
        0.1 + 0.2,
        1 / 3,
        1e20,
        -1e20,
        1e-20,
    ]
    while len(out) < count:
        kind = rng.random()
        if kind < 0.35:
            (value,) = struct.unpack("<d", struct.pack("<Q", rng.getrandbits(64)))
            if not math.isfinite(value):
                continue
            out.append(value)
        elif kind < 0.6:
            magnitude = 10 ** rng.uniform(-30, 30)
            out.append(rng.choice((1, -1)) * magnitude * rng.random())
        elif kind < 0.8:
            out.append(rng.randint(-_INT64, _INT64 - 1))
        else:
            out.append(rng.randint(-1000, 1000))
    return out


def _round_trip_number(value: int | float) -> None:
    node = {"op": "lit", "value": value}
    text = render(node)
    assert "e" not in text.lower(), f"{value!r} rendered with an exponent: {text!r}"
    back = parse(text)
    negative = value < 0 or (isinstance(value, float) and math.copysign(1.0, value) < 0)
    if negative:
        # A.4: no negative literal. `neg` over the positive one, same type.
        expected = {"op": "neg", "args": [{"op": "lit", "value": -value}]}
        assert _same(back, expected), f"{value!r} -> {text!r} -> {back!r}"
        literal = back["args"][0]["value"]
        assert type(literal) is type(value)
        assert -literal == value
    else:
        assert _same(back, node), f"{value!r} -> {text!r} -> {back!r}"
    # And the text is stable: a second trip changes nothing.
    assert render(back) == text


def test_every_generated_number_reads_back_as_itself() -> None:
    rng = random.Random(_SEED)
    numbers = _random_numbers(rng, 4000)
    for value in numbers:
        try:
            _round_trip_number(value)
        except AssertionError as exc:
            raise AssertionError(f"seed {_SEED}: {exc}") from exc


# The parser proper: generated trees at depth, over every node kind.

_REF_PATHS = (
    "a",
    "b",
    "age",
    "members[.].name",
    "members[0].name",
    "members[].income",
    "_metadata.start_time",
    "$row.code",
)
_STRING_ALPHABET = "abcxyz XYZ 019 +-*/(),.=<>!${}\t\n_\u2018\u2019\u201c\u201d"
_FUNCTIONS = {
    "count": (1, 1),
    "sum": (1, 1),
    "coalesce": (1, 4),
    "today": (0, 0),
    "age_years": (1, 2),
    "date_add_days": (2, 2),
    "len": (1, 1),
    "concat": (1, 4),
    "substr": (2, 3),
    "regex": (2, 2),
    "round": (1, 2),
    "int": (1, 1),
    "dec": (1, 1),
    "str": (1, 1),
    "pulldata": (4, 4),
    "is_null": (1, 1),
}


def _random_literal(rng: random.Random, numbers: list[int | float]) -> dict[str, Any]:
    kind = rng.random()
    if kind < 0.4:
        value = rng.choice(numbers)
        # A negative number is `neg` over a positive literal (A.4), so a
        # literal here is non-negative and the tree grows the `neg` itself.
        return {"op": "lit", "value": abs(value) if value != 0 else 0}
    if kind < 0.7:
        length = rng.randint(0, 12)
        text = "".join(rng.choice(_STRING_ALPHABET) for _ in range(length))
        # Straight quotes: one kind at most, since a string holding both has no
        # surface form and the printer says so.
        if rng.random() < 0.3:
            text += rng.choice(("'", '"'))
        return {"op": "lit", "value": text}
    return {"op": "lit", "value": rng.choice((True, False, None))}


def _random_tree(rng: random.Random, depth: int, numbers: list[int | float]) -> dict[str, Any]:
    from app.modules.forms.expression_text import _BINARY, _NARY

    if depth <= 0 or rng.random() < 0.2:
        if rng.random() < 0.4:
            return {"op": "ref", "path": rng.choice(_REF_PATHS)}
        return _random_literal(rng, numbers)

    def sub() -> dict[str, Any]:
        return _random_tree(rng, depth - 1, numbers)

    kind = rng.random()
    if kind < 0.45:
        op = rng.choice(list(_BINARY))
        arity = rng.randint(2, 4) if op in _NARY else 2
        return {"op": op, "args": [sub() for _ in range(arity)]}
    if kind < 0.55:
        return {"op": "neg", "args": [sub()]}
    if kind < 0.65:
        return {"op": "not", "args": [sub()]}
    if kind < 0.72:
        return {"op": "selected", "args": [sub(), sub()]}
    if kind < 0.8:
        return {"op": "if", "args": [sub(), sub(), sub()]}
    name = rng.choice(list(_FUNCTIONS))
    low, high = _FUNCTIONS[name]
    return {"op": "call", "fn": name, "args": [sub() for _ in range(rng.randint(low, high))]}


def test_every_generated_tree_survives_a_round_trip() -> None:
    """`parse(render(tree)) == tree` over trees nobody wrote: every operator
    and function, nested to depth, with literals from the number generator.
    The cross product above is depth two by construction; this is the rest."""
    rng = random.Random(_SEED)
    numbers = _random_numbers(rng, 500)
    for index in range(1500):
        tree = _random_tree(rng, depth=rng.randint(1, 6), numbers=numbers)
        try:
            text = render(tree)
        except RenderError as exc:
            raise AssertionError(f"seed {_SEED} tree {index}: {tree!r} refused: {exc}") from exc
        assert "e+" not in text and "e-" not in text.replace("date_", ""), text
        row_scope = "$row." in json.dumps(tree)
        try:
            back = parse(text, row_scope=row_scope)
        except Exception as exc:
            raise AssertionError(
                f"seed {_SEED} tree {index}: {text!r} does not parse: {exc}\n{tree!r}"
            ) from exc
        assert _same(back, tree), (
            f"seed {_SEED} tree {index}: {tree!r}\nrendered {text!r}\ncame back {back!r}"
        )
        assert render(back) == text
