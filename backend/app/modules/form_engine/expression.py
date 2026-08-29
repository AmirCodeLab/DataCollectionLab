"""Reference implementation of the DCP Form IR expression evaluator.

This is the normative reference for expression semantics. The Kotlin engine in
shared/form-engine must produce identical results for every conformance vector
in conformance/vectors.

Spec: specs/form-ir-v0.1.md sections 4 and 5.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

INT_MIN = -(2**63)
INT_MAX = 2**63 - 1


class EvaluationError(Exception):
    """Raised for conditions the spec defines as errors rather than null."""


class CompileError(Exception):
    """Raised for structurally invalid expressions or unresolvable references."""


@dataclass(frozen=True)
class EvalContext:
    """State available to a single evaluation pass.

    ``today`` and ``now`` are frozen for the whole pass so that one pass is
    internally consistent (spec 5.2).
    """

    values: Mapping[str, Any]
    today: date
    now: datetime
    row: Mapping[str, Any] | None = None
    metadata: Mapping[str, Any] | None = None
    # (repeat_id, instance_id) when evaluating inside a repeat instance.
    scope: tuple[str, str] | None = None
    # repeat_id -> ordered instance ids, for positional addressing.
    instances: Mapping[str, list[str]] | None = None


# --------------------------------------------------------------------------
# Null-aware primitives (spec 4.4)
# --------------------------------------------------------------------------


def _is_null(v: Any) -> bool:
    return v is None


def _arith(op: Callable[[Any, Any], Any], a: Any, b: Any) -> Any:
    """Any arithmetic operation with a null operand yields null (spec 4.4.2)."""
    if _is_null(a) or _is_null(b):
        return None
    result = op(a, b)
    if isinstance(result, int) and not isinstance(result, bool):
        if result < INT_MIN or result > INT_MAX:
            raise EvaluationError("integer overflow")
    return result


def _compare(op: Callable[[Any, Any], bool], a: Any, b: Any) -> Any:
    """Any comparison with a null operand yields null, not false (spec 4.4.3)."""
    if _is_null(a) or _is_null(b):
        return None
    if isinstance(a, str) != isinstance(b, str):
        raise EvaluationError(f"cannot compare {type(a).__name__} with {type(b).__name__}")
    return op(a, b)


def _and(args: Sequence[Any]) -> Any:
    """False dominates null; otherwise null propagates (spec 4.4.5)."""
    if any(a is False for a in args):
        return False
    if any(_is_null(a) for a in args):
        return None
    return True


def _or(args: Sequence[Any]) -> Any:
    """True dominates null; otherwise null propagates (spec 4.4.6)."""
    if any(a is True for a in args):
        return True
    if any(_is_null(a) for a in args):
        return None
    return False


def _not(a: Any) -> Any:
    return None if _is_null(a) else not a


def coerce_boolean(value: Any, *, null_is: bool) -> bool:
    """Boundary coercion (spec 4.4.7). Null becomes the given default."""
    if _is_null(value):
        return null_is
    if isinstance(value, bool):
        return value
    raise EvaluationError(f"expected boolean at boundary, got {type(value).__name__}")


# --------------------------------------------------------------------------
# Functions (spec 4.3)
# --------------------------------------------------------------------------


def _seq(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _non_null(values: Sequence[Any]) -> list[Any]:
    return [v for v in values if not _is_null(v)]


def _parse_date(value: Any) -> date | None:
    if _is_null(value):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise EvaluationError(f"expected date, got {type(value).__name__}")


def _parse_date_required(value: Any) -> date:
    """`_parse_date` for a value the caller has already excluded null for.

    `_parse_date` returns None for null and *only* for null — anything else
    that is not a date raises. Callers that have tested `_is_null` first are
    therefore guaranteed a date, but the type does not say so. This says it,
    and keeps the impossible case an error rather than a None that would
    surface three frames later as an AttributeError. The Kotlin engine spells
    the same invariant `isoDate(args[1])!!` (Functions.kt, ageYears).
    """
    parsed = _parse_date(value)
    if parsed is None:
        raise EvaluationError("expected date, got null")
    return parsed


def _fn_count(ctx: EvalContext, args: list[Any]) -> Any:
    return len(_non_null(_seq(args[0])))


def _fn_sum(ctx: EvalContext, args: list[Any]) -> Any:
    values = _non_null(_seq(args[0]))
    return sum(values) if values else 0


def _fn_min(ctx: EvalContext, args: list[Any]) -> Any:
    values = _non_null(_seq(args[0]))
    return min(values) if values else None


def _fn_max(ctx: EvalContext, args: list[Any]) -> Any:
    values = _non_null(_seq(args[0]))
    return max(values) if values else None


def _fn_count_selected(ctx: EvalContext, args: list[Any]) -> Any:
    value = args[0]
    return 0 if _is_null(value) else len(_seq(value))


def _fn_coalesce(ctx: EvalContext, args: list[Any]) -> Any:
    for a in args:
        if not _is_null(a):
            return a
    return None


def _fn_today(ctx: EvalContext, args: list[Any]) -> Any:
    return ctx.today.isoformat()


def _fn_now(ctx: EvalContext, args: list[Any]) -> Any:
    return ctx.now.isoformat()


def _fn_age_years(ctx: EvalContext, args: list[Any]) -> Any:
    born = _parse_date(args[0])
    if born is None:
        return None
    ref = _parse_date_required(args[1]) if len(args) > 1 and not _is_null(args[1]) else ctx.today
    years = ref.year - born.year
    if (ref.month, ref.day) < (born.month, born.day):
        years -= 1
    return years


def _fn_date_diff_days(ctx: EvalContext, args: list[Any]) -> Any:
    a, b = _parse_date(args[0]), _parse_date(args[1])
    if a is None or b is None:
        return None
    return (a - b).days


def _fn_date_add_days(ctx: EvalContext, args: list[Any]) -> Any:
    a = _parse_date(args[0])
    if a is None or _is_null(args[1]):
        return None
    return (a + timedelta(days=int(args[1]))).isoformat()


def _fn_len(ctx: EvalContext, args: list[Any]) -> Any:
    return None if _is_null(args[0]) else len(args[0])


def _fn_concat(ctx: EvalContext, args: list[Any]) -> Any:
    return "".join("" if _is_null(a) else str(a) for a in args)


def _fn_substr(ctx: EvalContext, args: list[Any]) -> Any:
    if _is_null(args[0]):
        return None
    start = int(args[1])
    if len(args) > 2 and not _is_null(args[2]):
        return args[0][start : start + int(args[2])]
    return args[0][start:]


def _fn_regex(ctx: EvalContext, args: list[Any]) -> Any:
    if _is_null(args[0]) or _is_null(args[1]):
        return None
    pattern = args[1]
    for forbidden in ("(?=", "(?!", "(?<=", "(?<!", "\\1", "\\2"):
        if forbidden in pattern:
            raise EvaluationError(
                f"regex feature {forbidden!r} not permitted; RE2 syntax only (spec 4.6)"
            )
    return re.search(pattern, args[0]) is not None


def _fn_round(ctx: EvalContext, args: list[Any]) -> Any:
    if _is_null(args[0]):
        return None
    digits = int(args[1]) if len(args) > 1 and not _is_null(args[1]) else 0
    factor = 10**digits
    scaled = args[0] * factor
    # half away from zero, not banker's rounding (spec 4.5)
    rounded = math.floor(scaled + 0.5) if scaled >= 0 else math.ceil(scaled - 0.5)
    return rounded / factor if digits > 0 else int(rounded)


def _fn_distance(ctx: EvalContext, args: list[Any]) -> Any:
    a, b = args[0], args[1]
    if _is_null(a) or _is_null(b):
        return None
    radius = 6371008.8  # WGS-84 mean radius, metres
    lat1, lon1 = math.radians(a["lat"]), math.radians(a["lon"])
    lat2, lon2 = math.radians(b["lat"]), math.radians(b["lon"])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(h))


def _cast_int(ctx: EvalContext, args: list[Any]) -> Any:
    return None if _is_null(args[0]) else int(args[0])


def _cast_dec(ctx: EvalContext, args: list[Any]) -> Any:
    return None if _is_null(args[0]) else float(args[0])


def _cast_str(ctx: EvalContext, args: list[Any]) -> Any:
    return None if _is_null(args[0]) else str(args[0])


FUNCTIONS: dict[str, tuple[Callable[[EvalContext, list[Any]], Any], int, int]] = {
    # name: (impl, min_arity, max_arity)
    "count": (_fn_count, 1, 1),
    "sum": (_fn_sum, 1, 1),
    "min": (_fn_min, 1, 1),
    "max": (_fn_max, 1, 1),
    "count_selected": (_fn_count_selected, 1, 1),
    "coalesce": (_fn_coalesce, 1, 99),
    "today": (_fn_today, 0, 0),
    "now": (_fn_now, 0, 0),
    "age_years": (_fn_age_years, 1, 2),
    "date_diff_days": (_fn_date_diff_days, 2, 2),
    "date_add_days": (_fn_date_add_days, 2, 2),
    "len": (_fn_len, 1, 1),
    "upper": (lambda c, a: None if _is_null(a[0]) else a[0].upper(), 1, 1),
    "lower": (lambda c, a: None if _is_null(a[0]) else a[0].lower(), 1, 1),
    "trim": (lambda c, a: None if _is_null(a[0]) else a[0].strip(), 1, 1),
    "concat": (_fn_concat, 1, 99),
    "substr": (_fn_substr, 2, 3),
    "contains": (lambda c, a: _compare(lambda x, y: y in x, a[0], a[1]), 2, 2),
    "starts_with": (lambda c, a: _compare(lambda x, y: x.startswith(y), a[0], a[1]), 2, 2),
    "ends_with": (lambda c, a: _compare(lambda x, y: x.endswith(y), a[0], a[1]), 2, 2),
    "regex": (_fn_regex, 2, 2),
    "round": (_fn_round, 1, 2),
    "int": (_cast_int, 1, 1),
    "dec": (_cast_dec, 1, 1),
    "str": (_cast_str, 1, 1),
    "distance": (_fn_distance, 2, 2),
    "is_null": (lambda c, a: _is_null(a[0]), 1, 1),
    "is_not_null": (lambda c, a: not _is_null(a[0]), 1, 1),
}


# --------------------------------------------------------------------------
# Evaluator
# --------------------------------------------------------------------------


def _resolve(path: str, ctx: EvalContext) -> Any:
    if path.startswith("$row."):
        if ctx.row is None:
            raise CompileError(f"$row reference outside a choice filter: {path}")
        return ctx.row.get(path[5:])

    if path.startswith("_metadata."):
        return (ctx.metadata or {}).get(path[10:])

    instances = ctx.instances or {}

    # members[].age -> sequence across every instance, in order (spec 4.2)
    if "[]." in path:
        repeat_id, suffix = path.split("[].", 1)
        return [
            ctx.values.get(f"{repeat_id}[{iid}].{suffix}")
            for iid in instances.get(repeat_id, [])
        ]

    # members[0].age -> a specific instance by position
    if "[" in path and "]." in path:
        repeat_id, rest = path.split("[", 1)
        index_text, suffix = rest.split("].", 1)
        if index_text == ".":
            # members[.].age -> the current instance
            if ctx.scope is None or ctx.scope[0] != repeat_id:
                raise CompileError(f"[.] reference outside its repeat: {path}")
            return ctx.values.get(f"{repeat_id}[{ctx.scope[1]}].{suffix}")
        ordered = instances.get(repeat_id, [])
        index = int(index_text)
        if index < 0 or index >= len(ordered):
            return None  # out-of-range instance reads as null, not an error
        return ctx.values.get(f"{repeat_id}[{ordered[index]}].{suffix}")

    # bare reference: current instance first, then outward to the form root
    if ctx.scope is not None:
        scoped = f"{ctx.scope[0]}[{ctx.scope[1]}].{path}"
        if scoped in ctx.values:
            return ctx.values[scoped]

    if path not in ctx.values:
        raise CompileError(f"unresolvable reference: {path}")
    return ctx.values[path]


_BINARY: dict[str, Callable[[Any, Any], Any]] = {
    "add": lambda a, b: _arith(lambda x, y: x + y, a, b),
    "sub": lambda a, b: _arith(lambda x, y: x - y, a, b),
    "mul": lambda a, b: _arith(lambda x, y: x * y, a, b),
    "mod": lambda a, b: None if (_is_null(a) or _is_null(b) or b == 0) else a % b,
    "eq": lambda a, b: _compare(lambda x, y: x == y, a, b),
    "ne": lambda a, b: _compare(lambda x, y: x != y, a, b),
    "lt": lambda a, b: _compare(lambda x, y: x < y, a, b),
    "lte": lambda a, b: _compare(lambda x, y: x <= y, a, b),
    "gt": lambda a, b: _compare(lambda x, y: x > y, a, b),
    "gte": lambda a, b: _compare(lambda x, y: x >= y, a, b),
}


def evaluate(expr: Any, ctx: EvalContext) -> Any:
    """Evaluate an expression AST node against a context."""
    if not isinstance(expr, dict) or "op" not in expr:
        raise CompileError(f"malformed expression node: {expr!r}")

    op = expr["op"]

    if op == "lit":
        return expr["value"]

    if op == "ref":
        return _resolve(expr["path"], ctx)

    if op == "if":
        # lazy in both branches (spec 4.3)
        cond = evaluate(expr["args"][0], ctx)
        if _is_null(cond):
            return None
        return evaluate(expr["args"][1] if cond else expr["args"][2], ctx)

    if op == "and":
        return _and([evaluate(a, ctx) for a in expr["args"]])

    if op == "or":
        return _or([evaluate(a, ctx) for a in expr["args"]])

    if op == "not":
        return _not(evaluate(expr["args"][0], ctx))

    if op == "neg":
        v = evaluate(expr["args"][0], ctx)
        return None if _is_null(v) else -v

    if op == "div":
        a = evaluate(expr["args"][0], ctx)
        b = evaluate(expr["args"][1], ctx)
        if _is_null(a) or _is_null(b) or b == 0:
            return None  # division by zero yields null (spec 4.4.8)
        return a / b

    if op == "idiv":
        a = evaluate(expr["args"][0], ctx)
        b = evaluate(expr["args"][1], ctx)
        if _is_null(a) or _is_null(b) or b == 0:
            return None
        return int(a // b)

    if op in _BINARY:
        a = evaluate(expr["args"][0], ctx)
        b = evaluate(expr["args"][1], ctx)
        return _BINARY[op](a, b)

    if op == "selected":
        haystack = evaluate(expr["args"][0], ctx)
        needle = evaluate(expr["args"][1], ctx)
        if _is_null(haystack) or _is_null(needle):
            return None
        return needle in _seq(haystack)

    if op == "in":
        needle = evaluate(expr["args"][0], ctx)
        haystack = evaluate(expr["args"][1], ctx)
        if _is_null(needle) or _is_null(haystack):
            return None
        return needle in _seq(haystack)

    if op == "call":
        fn = expr["fn"]
        if fn not in FUNCTIONS:
            raise CompileError(f"unknown function: {fn}")
        impl, min_arity, max_arity = FUNCTIONS[fn]
        args = [evaluate(a, ctx) for a in expr.get("args", [])]
        if not (min_arity <= len(args) <= max_arity):
            raise CompileError(
                f"function {fn} expects {min_arity}..{max_arity} args, got {len(args)}"
            )
        return impl(ctx, args)

    raise CompileError(f"unknown operator: {op}")


def collect_refs(expr: Any, out: set[str] | None = None) -> set[str]:
    """Collect every field path an expression depends on. Used to build the
    dependency graph (spec 5.1)."""
    if out is None:
        out = set()
    if not isinstance(expr, dict):
        return out
    if expr.get("op") == "ref":
        path = expr["path"]
        if not path.startswith(("$row.", "_metadata.")):
            # members[].age / members[0].age / members[.].age all depend on `age`
            if "]." in path:
                out.add(path.split("].", 1)[1])
            else:
                out.add(path)
    for arg in expr.get("args", []):
        collect_refs(arg, out)
    return out
