"""XLSForm's XPath, compiled into the Form IR's typed AST (§4).

The IR has no strings in it — "expressions are a typed AST, never XPath" is a
locked decision, and §4 says in as many words that importers compile XPath into
it. This module is that compiler, for a defined subset.

## What "a defined subset" has to mean here

Everything outside the subset is an **error naming the cell**, never a silent
drop and never a best guess. That is not caution, it is the difference between
two failure modes:

  reported   the author sees "survey!H27 uses count-selected, which this
             importer cannot translate", fixes or simplifies it, and the form
             works
  dropped    `relevant` disappears, the question is asked of everybody, and
             nobody finds out until the data comes back wrong

Both produce a form that compiles. Only one of them produces a form that asks
what its author intended.

Every unsupported function is also counted (`Instrumentation`), because the
list of what real forms reach for is a far better roadmap than the list of what
the XPath specification contains.

## Grammar

Recursive descent over a small precedence ladder — `or`, `and`, comparison,
additive, multiplicative, unary, primary. Small enough to read in one sitting,
which matters more than generality: the failure mode of a clever parser here is
translating something into the wrong AST, and a wrong `relevant` is worse than
an absent one because nothing reports it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# XLSForm writes references as ${name}. Inside a constraint or a
# constraint_message, `.` means "the value of this question".
_REFERENCE = re.compile(r"\$\{\s*([A-Za-z_][\w.\-]*)\s*\}")

#: XPath function -> Form IR function (§4.3). Only where the semantics match;
#: a near-miss belongs in the unsupported list, not here, because an author
#: cannot see that we quietly changed what their form computes.
_FUNCTIONS = {
    "count": "count",
    "sum": "sum",
    "min": "min",
    "max": "max",
    "count-selected": "count_selected",
    "coalesce": "coalesce",
    "today": "today",
    "now": "now",
    "string-length": "len",
    "upper-case": "upper",
    "lower-case": "lower",
    "normalize-space": "trim",
    "concat": "concat",
    "substr": "substr",
    "contains": "contains",
    "starts-with": "starts_with",
    "ends-with": "ends_with",
    "regex": "regex",
    "round": "round",
    "int": "int",
    "number": "dec",
    "string": "str",
    "distance": "distance",
    "pulldata": "pulldata",
    # The slope correction a field protocol writes:
    #   round(15 div (sqrt(cos(atan(${slope} div 100)))), 2)
    # Three at once, and the roadmap had recorded only `atan` — the importer
    # reports the first function it cannot translate per cell, and `atan` is the
    # innermost. `cos` and `sqrt` were behind it and no count could see them.
    "sqrt": "sqrt",
    "sin": "sin",
    "cos": "cos",
    "tan": "tan",
    "atan": "atan",
}

#: §4.3 functions that XLSForm has no spelling for, accepted by their IR name.
#:
#: Off for the importer and on for the builder, and the difference is not a
#: preference. An XLSForm author writing `is_null()` has written something
#: XLSForm does not have, and reporting that is right. An author in the
#: builder's code field is writing IR expressions directly, and refusing them
#: would leave six of §4.3's twenty-six functions with no surface at all — in a
#: field that exists precisely for what the visual editor cannot express.
def _ir_function_surface() -> dict[str, str]:
    """Every §4.3 function under its IR name, for the builder's code field.

    Two things at once, and both are needed for a round trip. The six functions
    XLSForm has no spelling for at all — `is_null`, the date arithmetic — and
    the ones it spells differently: `number` is `dec`, `string` is `str`,
    `string-length` is `len`. The importer maps XPath onto IR names, so
    rendering an AST produces IR names, and a surface that could not read its
    own output back would not be a surface.
    """
    from app.modules.form_engine.expression import FUNCTIONS

    return {name: name for name in FUNCTIONS}


_IR_ONLY_FUNCTIONS = _ir_function_surface()

_COMPARISONS = {
    "=": "eq",
    "==": "eq",
    "!=": "ne",
    "<": "lt",
    "<=": "lte",
    ">": "gt",
    ">=": "gte",
}


#: Straight and curly quotes, opening and closing. `'` and `'` pair with each
#: other and with themselves, because a form can contain either or both.
_QUOTES = "'\"\u2018\u2019\u201c\u201d"
_CLOSERS = {
    "'": "'", '"': '"',
    "\u2018": "\u2018\u2019", "\u2019": "\u2018\u2019",
    "\u201c": "\u201c\u201d", "\u201d": "\u201c\u201d",
}


def _closing_quote(source: str, start: int) -> int:
    """Index of the quote closing the one at [start], or -1."""
    closers = _CLOSERS[source[start]]
    for index in range(start + 1, len(source)):
        if source[index] in closers:
            return index
    return -1


class ExpressionError(Exception):
    """This expression cannot be translated.

    [function] names the offending XPath function when that is what stopped
    us, so the caller can count it towards the roadmap rather than only
    reporting it.

    [offset] is the character in the source the failure is about. The importer
    does not need it — it reports against a spreadsheet cell, and "survey!H27"
    is the location an author is looking at. A builder's code field does: the
    author is looking at the expression itself, and "somewhere in this string"
    is not a location. None where the failure is about the whole expression
    rather than a point in it.
    """

    def __init__(
        self, message: str, *, function: str | None = None, offset: int | None = None
    ) -> None:
        super().__init__(message)
        self.function = function
        self.offset = offset


@dataclass
class _Token:
    kind: str
    text: str
    #: Where this token starts in the source, for an error a code field can
    #: put a caret under.
    offset: int = 0


def _tokenize(source: str) -> list[_Token]:
    tokens: list[_Token] = []
    index = 0
    length = len(source)
    while index < length:
        char = source[index]
        if char.isspace():
            index += 1
            continue
        if source.startswith("${", index):
            end = source.find("}", index)
            if end == -1:
                raise ExpressionError(
                    "a ${...} reference is missing its closing brace", offset=index
                )
            tokens.append(_Token("ref", source[index + 2 : end].strip(), index))
            index = end + 1
            continue
        # Straight and curly both. Excel's autocorrect turns a typed
        # apostrophe into U+2018/U+2019 without asking, so real forms are full
        # of them — seven in the UCL biomass form alone — and refusing those is
        # refusing the file for something Excel did to it.
        if char in _QUOTES:
            end = _closing_quote(source, index)
            if end == -1:
                raise ExpressionError(
                    "a quoted string is missing its closing quote", offset=index
                )
            tokens.append(_Token("string", source[index + 1 : end], index))
            index = end + 1
            continue
        if char.isdigit() or (char == "." and index + 1 < length and source[index + 1].isdigit()):
            match = re.match(r"\d+(\.\d+)?", source[index:])
            assert match
            tokens.append(_Token("number", match.group(0), index))
            index += match.end()
            continue
        # `.` on its own is "this question's value" (XForms), and it is a
        # different token from the `.` inside 1.5, handled above.
        if char == "." and not source.startswith("..", index):
            tokens.append(_Token("dot", ".", index))
            index += 1
            continue
        two = source[index : index + 2]
        if two in ("!=", "<=", ">=", "=="):
            tokens.append(_Token("op", two, index))
            index += 2
            continue
        if char in "=<>+-*(),":
            tokens.append(_Token("op", char, index))
            index += 1
            continue
        match = re.match(r"[A-Za-z_][\w.\-]*", source[index:])
        if match:
            tokens.append(_Token("name", match.group(0), index))
            index += match.end()
            continue
        raise ExpressionError(f"unexpected character {char!r}", offset=index)
    return tokens


class _Parser:
    def __init__(
        self,
        tokens: list[_Token],
        self_path: str | None,
        row_scope: bool = False,
        end: int = 0,
        ir_functions: bool = False,
    ) -> None:
        self.tokens = tokens
        self.position = 0
        #: Where the source ends. An expression that stops early is the most
        #: common state a code field is ever in — the author is mid-typing —
        #: and "at the end" is the only honest place to point.
        self.end = end
        self.self_path = self_path
        #: Inside a `choice_filter` a bare name is a *column of the candidate
        #: row*, which is the one place in XLSForm where a bare name means
        #: something. Everywhere else it is an error, and deliberately so.
        self.row_scope = row_scope
        self.ir_functions = ir_functions
        self.functions = {**_FUNCTIONS, **_IR_ONLY_FUNCTIONS} if ir_functions else _FUNCTIONS

    def peek(self) -> _Token | None:
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def take(self) -> _Token:
        token = self.peek()
        if token is None:
            raise ExpressionError(
                "the expression ends sooner than expected", offset=self.end
            )
        self.position += 1
        return token

    def accept(self, kind: str, text: str | None = None) -> _Token | None:
        token = self.peek()
        if token and token.kind == kind and (text is None or token.text.lower() == text):
            self.position += 1
            return token
        return None

    def expect_op(self, text: str) -> None:
        if not self.accept("op", text):
            found = self.peek()
            raise ExpressionError(
                f"expected {text!r} but found {found.text!r}" if found else f"expected {text!r}"
            )

    # -- precedence ladder, loosest first ------------------------------------

    def parse(self) -> dict[str, Any]:
        node = self.parse_or()
        if self.peek() is not None:
            trailing = self.peek()
            assert trailing is not None
            raise ExpressionError(
                f"unexpected trailing {trailing.text!r}", offset=trailing.offset
            )
        return node

    def parse_or(self) -> dict[str, Any]:
        node = self.parse_and()
        args = [node]
        while self.accept("name", "or"):
            args.append(self.parse_and())
        # §4.1: and/or take two or more arguments and evaluate left to right,
        # so a chain is one node rather than a nest. That is not cosmetic — the
        # null rules in §4.4 are defined over the whole operand list.
        return args[0] if len(args) == 1 else {"op": "or", "args": args}

    def parse_and(self) -> dict[str, Any]:
        node = self.parse_comparison()
        args = [node]
        while self.accept("name", "and"):
            args.append(self.parse_comparison())
        return args[0] if len(args) == 1 else {"op": "and", "args": args}

    def parse_comparison(self) -> dict[str, Any]:
        left = self.parse_additive()
        token = self.peek()
        if token and token.kind == "op" and token.text in _COMPARISONS:
            self.take()
            right = self.parse_additive()
            return {"op": _COMPARISONS[token.text], "args": [left, right]}
        return left

    def parse_additive(self) -> dict[str, Any]:
        node = self.parse_multiplicative()
        while True:
            token = self.peek()
            if token and token.kind == "op" and token.text in ("+", "-"):
                self.take()
                right = self.parse_multiplicative()
                node = {"op": "add" if token.text == "+" else "sub", "args": [node, right]}
                continue
            # XPath spells these as words, and `div` is not `/`: §4.5 makes
            # integer division a separate operator, so mapping `div` to `div`
            # is correct and `idiv` has no XPath spelling to map from.
            words = ("div", "mod", "idiv") if self.ir_functions else ("div", "mod")
            if token and token.kind == "name" and token.text.lower() in words:
                self.take()
                right = self.parse_multiplicative()
                node = {"op": token.text.lower(), "args": [node, right]}
                continue
            return node

    def parse_multiplicative(self) -> dict[str, Any]:
        node = self.parse_unary()
        while True:
            token = self.peek()
            if token and token.kind == "op" and token.text == "*":
                self.take()
                node = {"op": "mul", "args": [node, self.parse_unary()]}
                continue
            return node

    def parse_unary(self) -> dict[str, Any]:
        if self.accept("op", "-"):
            return {"op": "neg", "args": [self.parse_unary()]}
        return self.parse_primary()

    def parse_primary(self) -> dict[str, Any]:
        token = self.take()

        if token.kind == "number":
            value: object = float(token.text) if "." in token.text else int(token.text)
            return {"op": "lit", "value": value}
        if token.kind == "string":
            return {"op": "lit", "value": token.text}
        if token.kind == "ref":
            return {"op": "ref", "path": token.text}
        if token.kind == "dot":
            if self.self_path is None:
                raise ExpressionError(
                    "'.' means the value of the current question, and there is no "
                    "current question here"
                )
            return {"op": "ref", "path": self.self_path}
        if token.kind == "op" and token.text == "(":
            node = self.parse_or()
            self.expect_op(")")
            return node
        if token.kind == "name":
            lowered = token.text.lower()
            if lowered in ("true", "false") and self.peek() and self.peek().text == "(":  # type: ignore[union-attr]
                self.take()
                self.expect_op(")")
                return {"op": "lit", "value": lowered == "true"}
            if self.peek() and self.peek().kind == "op" and self.peek().text == "(":  # type: ignore[union-attr]
                return self.parse_call(token.text)
            if self.row_scope:
                # `region_id=${region_id}` on a choice_filter: the left side is
                # the candidate row's column, the right side is an answer. Form
                # IR §3 spells the first `$row.region_id`, which is what the
                # engine's evaluator already resolves and what `collect_refs`
                # already knows not to treat as a field dependency.
                return {"op": "ref", "path": f"$row.{token.text}"}
            raise ExpressionError(
                f"{token.text!r} is not something this importer understands. "
                "A bare name is not a reference — XLSForm writes those as ${name}."
            )
        raise ExpressionError(f"unexpected {token.text!r}", offset=token.offset)

    def parse_call(self, name: str) -> dict[str, Any]:
        self.expect_op("(")
        args: list[dict[str, Any]] = []
        if not (self.peek() and self.peek().kind == "op" and self.peek().text == ")"):  # type: ignore[union-attr]
            args.append(self.parse_or())
            while self.accept("op", ","):
                args.append(self.parse_or())
        self.expect_op(")")

        lowered = name.lower()

        # These are operators in the IR (§4.1), not calls, so they are
        # translated rather than looked up.
        if lowered == "not":
            if len(args) != 1:
                raise ExpressionError("not() takes one argument")
            return {"op": "not", "args": args}
        if lowered == "selected":
            if len(args) != 2:
                raise ExpressionError("selected() takes two arguments")
            return {"op": "selected", "args": args}
        if lowered == "if":
            if len(args) != 3:
                raise ExpressionError("if() takes three arguments")
            return {"op": "if", "args": args}

        # `null()` is the surface spelling of the null *literal*. Reading it
        # back as a call would give one surface two ASTs, and the round trip
        # would pick the wrong one half the time.
        if lowered == "null" and self.ir_functions:
            if args:
                raise ExpressionError("null() takes no arguments")
            return {"op": "lit", "value": None}

        target = self.functions.get(lowered)
        if target is None:
            raise ExpressionError(
                f"{name}() is not a function this importer can translate yet",
                function=lowered,
            )
        return {"op": "call", "fn": target, "args": args}


def translate(
    source: str,
    *,
    self_path: str | None = None,
    row_scope: bool = False,
    ir_functions: bool = False,
) -> dict[str, Any]:
    """Compile one XLSForm expression into a Form IR expression node (§4.1).

    [self_path] is the question the expression belongs to, which is what `.`
    refers to inside a `constraint`. Passing None makes `.` an error rather
    than resolving it to something arbitrary.

    [row_scope] is for a `choice_filter` and nothing else. It is the only
    context in XLSForm where a bare name is meaningful — it names a column of
    the candidate row — and it is deliberately not the default, because
    everywhere else a bare name is a mistake worth reporting rather than a
    reference worth inventing.

    Raises [ExpressionError] with a sentence fit to show an author. The caller
    turns that into a diagnostic against the cell; nothing here decides
    severity, because the same failure is fatal in a `relevant` and merely
    annoying in a `default`.
    """
    text = source.strip()
    if not text:
        raise ExpressionError("the expression is empty")
    # Offsets are counted in `text`, which is stripped; a caller holding
    # `source` needs them counted in that. Shifting here rather than tokenizing
    # the untrimmed string keeps the parser's own arithmetic simple and the
    # reported position honest — a caret one character out is worse than none,
    # because it points confidently at the wrong thing.
    lead = len(source) - len(source.lstrip())
    try:
        return _Parser(
            _tokenize(text),
            self_path,
            row_scope=row_scope,
            end=len(text),
            ir_functions=ir_functions,
        ).parse()
    except ExpressionError as exc:
        if lead and exc.offset is not None:
            raise ExpressionError(
                str(exc), function=exc.function, offset=exc.offset + lead
            ) from exc
        raise


def references(node: dict[str, Any]) -> set[str]:
    """Every field this expression reads, for checking they exist."""
    found: set[str] = set()
    if not isinstance(node, dict):
        return found
    if node.get("op") == "ref":
        found.add(str(node["path"]))
    for argument in node.get("args", []) or []:
        found |= references(argument)
    return found


def substitutions(text: str) -> list[str]:
    """The ${...} names inside a label or hint.

    XLSForm allows output substitution in labels; the IR's i18n strings are
    plain text (§7) and have no way to carry it. The importer reports these
    rather than leaving `${age}` visible to a respondent as literal text.
    """
    return _REFERENCE.findall(text)
