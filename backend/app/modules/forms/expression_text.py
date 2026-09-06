"""Form IR expressions as text, and back (Form IR Appendix A).

The IR's canonical form is a typed AST — "expressions are a typed AST, never
XPath" is a locked decision, and §4.1 says so. This module is the **surface**
for one document: what a builder's code field shows an author, and what it
sends back. It is not a second definition of what an expression means.

## Why there is no second parser

Reading text into an AST already existed:
`app/modules/forms/xlsform/expressions.translate` has compiled XLSForm's XPath
into §4.1 nodes since the importer was written, with a precedence ladder and a
tested corpus behind it. A builder's code field needs the same job done, and a
second parser — in TypeScript in the console, or in Python beside this one — is
the shape this repository keeps paying for. So the surface **is** that syntax,
extended by the six §4.3 functions XLSForm has no spelling for
(`_IR_ONLY_FUNCTIONS`), and this module adds only the direction that was
missing: AST back to text.

## What this is not

**It is not a conformance surface**, and that is worth saying out loud because
"a new grammar" reads like a `conformance/functions` obligation. Both engines
consume AST. Neither parses text, and neither ever will — the IR that reaches a
handset has no strings in it. There is nothing here for a vector to compare
between two engines, because only one implementation exists by construction.

What replaces a vector is a round trip: `parse(render(node)) == node` for every
node the engine can evaluate. That is a property of this module alone, and
`tests/test_expression_text.py` runs it over every expression in the
conformance corpus rather than over examples chosen by hand.
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

from app.modules.forms.xlsform.expressions import ExpressionError, translate

#: Binary operators, by the precedence level the parser reads them at.
#:
#: These mirror `_Parser` exactly and must keep mirroring it. Note `div`, `mod`
#: and `idiv` sit with `+` and `-` rather than with `*`: that is XPath's ladder,
#: which the parser implements, and a printer that assumed the C ladder would
#: emit `a + b div c` for `(a + b) div c`.
_BINARY = {
    "or": (1, "or"),
    "and": (2, "and"),
    "eq": (3, "="),
    "ne": (3, "!="),
    "lt": (3, "<"),
    "lte": (3, "<="),
    "gt": (3, ">"),
    "gte": (3, ">="),
    "add": (4, "+"),
    "sub": (4, "-"),
    "div": (4, "div"),
    "mod": (4, "mod"),
    "idiv": (4, "idiv"),
    "mul": (5, "*"),
}

#: `and` and `or` are n-ary in the IR and the parser flattens chains into one
#: node (§4.1). Everything else here is strictly binary.
_NARY = frozenset({"and", "or"})

#: Operators the parser reads left-associatively, so the left operand may stay
#: at its own precedence. Comparisons are absent deliberately: they are not
#: associative, and `${a} = ${b} = ${c}` is a parse error rather than a chain.
_LEFT_ASSOCIATIVE = frozenset({"add", "sub", "mul", "div", "mod", "idiv"})

_UNARY_PRECEDENCE = 6
_PRIMARY_PRECEDENCE = 7


class RenderError(Exception):
    """This AST cannot be written as text."""


def render(node: Any) -> str:
    """One §4.1 expression node as surface text.

    Parenthesised by precedence rather than everywhere: an author reads this,
    and `((${a}) > (5))` is a worse answer than `${a} > 5` even though both
    parse. Where the tree needs them, they are there.
    """
    return _render(node, 0)


def _render(node: Any, parent_precedence: int) -> str:
    if not isinstance(node, dict) or "op" not in node:
        raise RenderError(f"not an expression node: {node!r}")

    op = node["op"]
    args = node.get("args") or []

    if op == "lit":
        value = node.get("value")
        if isinstance(value, int | float) and _is_negative_number(value):
            # `-5` is the negation of `5`: the surface has no negative literal,
            # and the parser reads the sign as `neg` (A.4). Rendering through
            # the `neg` path gives it the parentheses a unary needs.
            positive = {"op": "lit", "value": -value}
            return _render({"op": "neg", "args": [positive]}, parent_precedence)
        return _literal(value)
    if op == "ref":
        path = str(node.get("path", ""))
        # `$row.col` is a candidate row's column (§3.2), and it is spelled as a
        # bare name in a choice filter — the one place XLSForm gives a bare name
        # a meaning.
        return path.removeprefix("$row.") if path.startswith("$row.") else "${" + path + "}"

    if op in _BINARY:
        precedence, symbol = _BINARY[op]

        if op in _NARY:
            # §4.1: `and` and `or` take two or more arguments and the parser
            # flattens a chain into one node, because §4.4's null rules are
            # defined over the whole operand list. So a *nested* `or` is a
            # different node from a flat one, and rendering it without
            # parentheses would come back flattened — a different expression
            # that happens to look the same.
            if len(args) < 2:
                raise RenderError(f"{op} takes two or more arguments, got {len(args)}")
            rendered = f" {symbol} ".join(_render(a, precedence + 1) for a in args)
            return f"({rendered})" if precedence < parent_precedence else rendered

        if len(args) != 2:
            raise RenderError(f"{op} takes two arguments, got {len(args)}")

        # The left operand keeps its own level only where the parser is
        # left-associative. A comparison is not associative at all — `a = b = c`
        # is a parse error, not a chain — so both sides go one level tighter and
        # a nested comparison gets the parentheses it needs.
        left_precedence = precedence if op in _LEFT_ASSOCIATIVE else precedence + 1
        left = _render(args[0], left_precedence)
        # The right operand is always one level tighter, so a right-nested tree
        # of the same operator keeps its shape: `a - (b - c)` must not print as
        # `a - b - c`, which parses back left-associated.
        right = _render(args[1], precedence + 1)
        text = f"{left} {symbol} {right}"
        return f"({text})" if precedence < parent_precedence else text

    if op == "not":
        return f"not({_render(args[0], 0)})"
    if op == "neg":
        text = f"-{_render(args[0], _UNARY_PRECEDENCE)}"
        return f"({text})" if _UNARY_PRECEDENCE < parent_precedence else text
    if op == "selected":
        return f"selected({_render(args[0], 0)}, {_render(args[1], 0)})"
    if op == "if":
        rendered = ", ".join(_render(a, 0) for a in args)
        return f"if({rendered})"
    if op == "in":
        # `in` has no surface spelling: XLSForm has no such operator, so an
        # author cannot have typed one and this printer must not invent one.
        # An expression carrying it round-trips through the AST and not through
        # text, which the code field reports rather than mangles.
        raise RenderError(
            "`in` has no surface syntax. Edit this expression as IR, or use selected()."
        )
    if op == "call":
        name = str(node.get("fn", ""))
        if name == "null":
            # `null()` is the surface for the null literal, so a `null` call has
            # no distinct spelling. It is the same value by a longer route.
            raise RenderError(
                "the `null` function has no surface form distinct from the null "
                "literal; use a literal null"
            )
        rendered = ", ".join(_render(a, 0) for a in args)
        return f"{name}({rendered})"

    raise RenderError(f"unknown operator: {op}")


def _literal(value: Any) -> str:
    if value is True:
        return "true()"
    if value is False:
        return "false()"
    if value is None:
        return "null()"
    if isinstance(value, int | float):
        return _number(value)
    text = str(value)
    # Single quotes, and a value containing one goes in double. Neither is
    # escaped, because the tokenizer has no escape sequence to read back — a
    # string holding both quote kinds has no surface form and says so.
    if "'" not in text:
        return f"'{text}'"
    if '"' not in text:
        return f'"{text}"'
    raise RenderError(
        "a string containing both quote characters has no surface form; edit this expression as IR"
    )


def _is_negative_number(value: int | float) -> bool:
    if isinstance(value, bool):
        return False
    return value < 0 or (isinstance(value, float) and math.copysign(1.0, value) < 0)


def _number(value: int | float) -> str:
    """A number as the digits that read back as exactly this value (A.4).

    **This is not §4.3.1's `str()`**, and the difference is the point. `str()`
    is what a human reads in a label, and it drops the `.0` from an
    integer-valued decimal so `str(dec("800"))` can match a text column. This
    is what an author edits and saves back, so it has one job: the value that
    goes out is the value that comes in. `800.0` stays a decimal, and
    `0.30000000000000004` is written with all seventeen digits — a code field
    that showed `0.3` and saved `0.3` would have changed the form's behaviour
    without saying so.

    The digits are the shortest that round-trip (Python's `repr`), spelled
    positionally: the grammar has no exponent, so `1e-07` is `0.0000001`.
    """
    if isinstance(value, float) and not math.isfinite(value):
        # JSON cannot carry these, so no form does; and the grammar has no
        # spelling to read back.
        raise RenderError(f"{value!r} is not a number a form can hold; it has no surface form")
    if isinstance(value, int):
        return str(value)
    text = repr(value)
    if "e" in text or "E" in text:
        text = format(Decimal(text), "f")
    if "." not in text:
        text += ".0"
    return text


def parse(source: str, *, self_path: str | None = None, row_scope: bool = False) -> dict[str, Any]:
    """Surface text into a §4.1 node, with the builder's function surface on.

    Raises [ExpressionError], which carries the offset a code field puts a
    caret under.
    """
    return translate(source, self_path=self_path, row_scope=row_scope, ir_functions=True)


__all__ = ["ExpressionError", "RenderError", "parse", "render"]
