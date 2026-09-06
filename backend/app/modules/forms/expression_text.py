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
        return _literal(node.get("value"))
    if op == "ref":
        path = str(node.get("path", ""))
        # `$row.col` is a candidate row's column (§3.2), and it is spelled as a
        # bare name in a choice filter — the one place XLSForm gives a bare name
        # a meaning.
        return path.removeprefix("$row.") if path.startswith("$row.") else "${" + path + "}"

    if op in _BINARY:
        precedence, symbol = _BINARY[op]
        if len(args) != 2:
            raise RenderError(f"{op} takes two arguments, got {len(args)}")
        left = _render(args[0], precedence)
        # The right operand is rendered one level tighter, so a right-nested
        # tree of the same operator keeps its shape: `a - (b - c)` must not
        # print as `a - b - c`, which parses back left-associated.
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
            "`in` has no surface syntax. Edit this expression as IR, or use "
            "selected()."
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
        return str(value)
    text = str(value)
    # Single quotes, and a value containing one goes in double. Neither is
    # escaped, because the tokenizer has no escape sequence to read back — a
    # string holding both quote kinds has no surface form and says so.
    if "'" not in text:
        return f"'{text}'"
    if '"' not in text:
        return f'"{text}"'
    raise RenderError(
        "a string containing both quote characters has no surface form; "
        "edit this expression as IR"
    )


def parse(source: str, *, self_path: str | None = None, row_scope: bool = False) -> dict[str, Any]:
    """Surface text into a §4.1 node, with the builder's function surface on.

    Raises [ExpressionError], which carries the offset a code field puts a
    caret under.
    """
    return translate(source, self_path=self_path, row_scope=row_scope, ir_functions=True)


__all__ = ["ExpressionError", "RenderError", "parse", "render"]
