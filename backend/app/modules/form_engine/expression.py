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
    # Where `pulldata` reads reference data from (§4.3). None when the caller
    # built no source — `pulldata` is then null, like every other argument that
    # is not what §4.3 declares (§4.7), rather than an exception on a device
    # that has not finished syncing.
    datasets: Any = None


# --------------------------------------------------------------------------
# Null-aware primitives (spec 4.4)
# --------------------------------------------------------------------------


def _is_null(v: Any) -> bool:
    return v is None


def _arith(op: Callable[[Any, Any], Any], a: Any, b: Any) -> Any:
    """Arithmetic over two numbers, or null (spec 4.4.2, 4.7).

    A null operand yields null; so does one that is not a number. `"800" + 1`
    is null, not "8001" and not an error — `add` is arithmetic and `+` never
    concatenates in this IR. `int("800") + 1` is 801, and that is the whole
    difference between a form that says what it means and one that does not.
    """
    x, y = _number(a), _number(b)
    if x is None or y is None:
        return None
    result = op(x, y)
    if isinstance(result, int) and not isinstance(result, bool):
        if result < INT_MIN or result > INT_MAX:
            raise EvaluationError("integer overflow")
    return result


def _ordered(op: Callable[[Any, Any], bool], a: Any, b: Any) -> Any:
    """`<`, `<=`, `>`, `>=` — null unless both sides are the same kind (4.4.3, 4.7).

    There is no ordering *between* types to appeal to, so a comparison across
    them cannot say anything and returns null rather than raising. Text orders
    against text lexicographically and numbers against numbers; a boolean has
    no ordering at all.
    """
    if _is_null(a) or _is_null(b):
        return None
    x, y = _number(a), _number(b)
    if x is not None and y is not None:
        return op(x, y)
    s, t = _text(a), _text(b)
    if s is not None and t is not None:
        return op(s, t)
    return None


def _equal(a: Any, b: Any) -> Any:
    """`eq` — total across types (spec 4.7).

    The one place "no implicit coercion" produces an answer rather than an
    absence. `"800" == 800` is a question with a correct answer under a
    no-coercion rule, and the answer is no. Null is still null: §4.4.9 says
    null is never equal to anything, including itself.

    The reach is longer than it looks. A dataset cell is always text (§3.2), so
    a filter written `$row.population = ${count}` against an integer answer
    matches nothing — correctly, and silently. `str(${count})` is the fix.
    """
    if _is_null(a) or _is_null(b):
        return None
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    x, y = _number(a), _number(b)
    if x is not None and y is not None:
        return x == y
    if type(a) is not type(b) and not (isinstance(a, str) and isinstance(b, str)):
        return False
    return bool(a == b)


def _text1(op: Callable[[str], str], a: Any) -> Any:
    """`upper` / `lower` / `trim` — the argument must be text (§4.3, §4.7)."""
    text = _text(a)
    return None if text is None else op(text)


def _text2(op: Callable[[str, str], bool], a: Any, b: Any) -> Any:
    """`contains` / `starts_with` / `ends_with` — both sides must be text (§4.7).

    `contains(800, "0")` is null, not true: `len`, `substr` and these three all
    take text, and a number is not text until `str()` makes it one.
    """
    x, y = _text(a), _text(b)
    return None if x is None or y is None else op(x, y)


def _mod(a: Any, b: Any) -> Any:
    """`mod` over two numbers; a zero divisor is null, like `div` (4.4.8)."""
    x, y = _number(a), _number(b)
    if x is None or y is None or y == 0:
        return None
    return x % y


def _boolean(value: Any) -> bool | None:
    """The value as a boolean, or None when it is not one (§4.7)."""
    return value if isinstance(value, bool) else None


def _and(args: Sequence[Any]) -> Any:
    """False dominates null; otherwise null propagates (spec 4.4.5, 4.7).

    A non-boolean operand is null, so it neither makes the result false nor is
    quietly treated as true.
    """
    values = [_boolean(a) for a in args]
    if any(v is False for v in values):
        return False
    if any(v is None for v in values):
        return None
    return True


def _or(args: Sequence[Any]) -> Any:
    """True dominates null; otherwise null propagates (spec 4.4.6, 4.7)."""
    values = [_boolean(a) for a in args]
    if any(v is True for v in values):
        return True
    if any(v is None for v in values):
        return None
    return False


def _not(a: Any) -> Any:
    """`not` takes a boolean; anything else is null (4.4.4, 4.7).

    `not("yes")` used to be `False`, because a non-empty string is truthy in
    Python and this IR has no truthiness. It is null.
    """
    return not a if isinstance(a, bool) else None


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


# --------------------------------------------------------------------------
# Typed argument access (spec 4.7)
# --------------------------------------------------------------------------
#
# §4.3 declares a signature for every function. §4.7 says an argument that is
# not of its declared type is null, and that a function with such an argument
# yields null rather than raising. These four accessors are that rule, applied
# once each instead of at every call site — which is how the two engines came
# to disagree in 762 of 1,395 probes without anybody noticing (break 46).
#
# Evaluation therefore raises for exactly one reason: integer overflow (§4.5).


def _text(value: Any) -> str | None:
    """The value as text, or None when it is not text.

    Deliberately narrow. A number is not text — `len(800)` is null, not 3 —
    because §4.5 has no implicit coercion and `str()` is how a form asks for
    one. `concat` is the single exception and renders instead; it is the only
    function whose job is to produce text out of whatever it is given.
    """
    return value if isinstance(value, str) else None


def _number(value: Any) -> float | int | None:
    """The value as a number, or None when it is not one.

    A boolean is not a number (§4.3.1): `true + true` is null, not 2. Text is
    not a number either — `"800" + 1` is null, and `int("800") + 1` is 801.
    """
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int | float) else None


def _integer(value: Any) -> int | None:
    """The value as an integer, for arguments §4.3 declares `integer`.

    A whole-valued decimal counts: `date_add_days(d, 3.0)` is the same question
    as `date_add_days(d, 3)`, and refusing one of them would make the answer
    depend on how the number was arrived at.
    """
    number = _number(value)
    if number is None:
        return None
    if isinstance(number, float):
        return int(number) if number.is_integer() else None
    return number


def _date_or_none(value: Any) -> date | None:
    """The value as a date, or None when it is not one — never raising.

    `date.fromisoformat` on "8a" raises, and that reached the API as a 500 for
    as long as this engine has existed. §4.7 makes it null: a half-typed date
    is the ordinary state of a date field mid-interview.
    """
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _geopoint(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict) and isinstance(value.get("lat"), int | float):
        if isinstance(value.get("lon"), int | float):
            return value
    return None


def _fn_count(ctx: EvalContext, args: list[Any]) -> Any:
    return len(_non_null(_seq(args[0])))


def _numbers(values: Any) -> list[float | int]:
    """The numeric members of a sequence, in order.

    §4.3 declares `sum`/`min`/`max` over a sequence of numbers, and §4.7 makes
    a non-number null — so a text member is ignored exactly as a null one is,
    rather than making the whole aggregate null. A repeat where one instance
    was left unanswered must still total the others; a repeat where one holds
    text is the same situation.
    """
    return [n for n in (_number(v) for v in _seq(values)) if n is not None]


def _fn_sum(ctx: EvalContext, args: list[Any]) -> Any:
    values = _numbers(args[0])
    return sum(values) if values else 0


def _fn_min(ctx: EvalContext, args: list[Any]) -> Any:
    values = _numbers(args[0])
    return min(values) if values else None


def _fn_max(ctx: EvalContext, args: list[Any]) -> Any:
    values = _numbers(args[0])
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
    born = _date_or_none(args[0])
    if born is None:
        return None
    if len(args) > 1 and not _is_null(args[1]):
        ref = _date_or_none(args[1])
        if ref is None:
            return None
    else:
        ref = ctx.today
    years = ref.year - born.year
    if (ref.month, ref.day) < (born.month, born.day):
        years -= 1
    return years


def _fn_date_diff_days(ctx: EvalContext, args: list[Any]) -> Any:
    a, b = _date_or_none(args[0]), _date_or_none(args[1])
    if a is None or b is None:
        return None
    return (a - b).days


def _fn_date_add_days(ctx: EvalContext, args: list[Any]) -> Any:
    a = _date_or_none(args[0])
    days = _integer(args[1])
    if a is None or days is None:
        return None
    try:
        return (a + timedelta(days=days)).isoformat()
    except (OverflowError, ValueError):
        # A date outside what a calendar can express is not a date. Null,
        # like every other argument that is not what §4.3 declares.
        return None


def _fn_len(ctx: EvalContext, args: list[Any]) -> Any:
    text = _text(args[0])
    return None if text is None else len(text)


def _fn_concat(ctx: EvalContext, args: list[Any]) -> Any:
    """The one function that renders rather than refuses (§4.7).

    Its job is to build text out of whatever it is given, so each argument is
    rendered the way `str` renders it and a null contributes the empty string.
    `concat("n=", 3)` is "n=3", which is what anybody writing it meant.
    """
    return "".join("" if _is_null(a) else (_cast_str(ctx, [a]) or "") for a in args)


def _fn_substr(ctx: EvalContext, args: list[Any]) -> Any:
    text = _text(args[0])
    start = _integer(args[1])
    if text is None or start is None:
        return None
    if len(args) > 2 and not _is_null(args[2]):
        length = _integer(args[2])
        if length is None:
            return None
        return text[start : start + length]
    return text[start:]


#: Regex features §4.6 forbids, because RE2 cannot express them — and the
#: reason RE2 is the rule is that backtracking on a respondent's answer is a
#: way to hang a phone.
FORBIDDEN_REGEX_FEATURES = ("(?=", "(?!", "(?<=", "(?<!", "\\1", "\\2")


def forbidden_regex_feature(pattern: str) -> str | None:
    """The first §4.6-forbidden construct in this pattern, or None.

    Shared with the publish gate deliberately. Evaluation returns null for such
    a pattern (§4.7), which means the constraint silently passes — so something
    has to refuse the form, and one implementation of "which features are
    forbidden" is what stops the two answers drifting.
    """
    return next((f for f in FORBIDDEN_REGEX_FEATURES if f in pattern), None)


def _fn_regex(ctx: EvalContext, args: list[Any]) -> Any:
    subject, pattern = _text(args[0]), _text(args[1])
    if subject is None or pattern is None:
        return None
    if forbidden_regex_feature(pattern) is not None:
        # Null, not an exception: §4.7 permits evaluation to raise only on
        # integer overflow, and the pattern is not executed either way. A form
        # carrying one is refused at publish (`forms.service.check_publishable`),
        # which is where somebody is reading.
        return None
    try:
        return re.search(pattern, subject) is not None
    except re.error:
        # A pattern that is not a pattern is not text this can match against.
        # §4.6's forbidden features stay an error above; a syntax error in the
        # author's own regex is null, like every other unusable argument.
        return None


#: Beyond this many digits a decimal has no more information to give, so a
#: request for them is not a question about this number. Bounded rather than
#: clamped: 10**digits with an unbounded exponent was an OverflowError, which
#: §4.7 does not permit evaluation to raise.
_MAX_ROUND_DIGITS = 15


def _fn_round(ctx: EvalContext, args: list[Any]) -> Any:
    number = _number(args[0])
    if number is None:
        return None
    if len(args) > 1 and not _is_null(args[1]):
        digits = _integer(args[1])
        if digits is None or abs(digits) > _MAX_ROUND_DIGITS:
            return None
    else:
        digits = 0
    factor = 10**digits
    scaled = number * factor
    # half away from zero, not banker's rounding (spec 4.5)
    rounded = math.floor(scaled + 0.5) if scaled >= 0 else math.ceil(scaled - 0.5)
    return rounded / factor if digits > 0 else int(rounded)


def _fn_sqrt(ctx: EvalContext, args: list[Any]) -> Any:
    """`(number) → decimal`. Negative is null, never NaN (§4.3, §4.7).

    A NaN is neither a number nor an absence: it compares false to everything
    including itself, so it would make a constraint pass and a relevance hide,
    both silently. Null has defined behaviour at every boundary (§4.4.7).
    """
    value = _number(args[0])
    if value is None or value < 0:
        return None
    return math.sqrt(value)


def _trig(fn: Callable[[float], float]) -> Callable[[EvalContext, list[Any]], Any]:
    """`(number) → decimal`, in radians (§4.3).

    Here because a real form needed them: the UCL biomass survey corrects a plot
    radius for slope with `round(15 div (sqrt(cos(atan(slope div 100)))), 2)`.
    """

    def call(ctx: EvalContext, args: list[Any]) -> Any:
        value = _number(args[0])
        return None if value is None else fn(float(value))

    return call


def _fn_pulldata(ctx: EvalContext, args: list[Any]) -> Any:
    """`(dataset, column, keyColumn, keyValue) → any` — a dataset lookup (§4.3).

    The value of `column` on the first row whose `keyColumn` equals `keyValue`,
    or null when there is no such row. Null rather than an error, like every
    other unusable argument (§4.7): on a device the commonest reason for no
    match is that the reference data has not finished syncing, and stopping the
    form is not an improvement on that.

    Goes through the same [DatasetSource] the choice filters use, so it obeys
    the same rule: on a client the source is bound to a form version, and this
    reads the list that form version was **published against** rather than
    whatever is newest (§3.2). A `pulldata` that resolved a key freely would be
    breaks 30/40/42 with a lookup instead of a list.
    """
    dataset, column, key_column = (_text(a) for a in args[:3])
    if dataset is None or column is None or key_column is None:
        return None
    if ctx.datasets is None or _is_null(args[3]):
        return None
    rows = ctx.datasets.rows(dataset, {key_column: args[3]})
    # The first match, in dataset order, which is the file's own order (§3.2).
    # A dataset key is unique per version, so "first" is a formality for the
    # ordinary case and a defined answer for a lookup on a non-key column.
    return next((row.get(column) for row in rows), None)


def _fn_distance(ctx: EvalContext, args: list[Any]) -> Any:
    a, b = _geopoint(args[0]), _geopoint(args[1])
    if a is None or b is None:
        return None
    radius = 6371008.8  # WGS-84 mean radius, metres
    lat1, lon1 = math.radians(a["lat"]), math.radians(a["lon"])
    lat2, lon2 = math.radians(b["lat"]), math.radians(b["lon"])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    # Rounded to millimetres, deliberately (§4.3). Four transcendental calls
    # deep, `sin`/`cos`/`asin`/`sqrt` are each permitted one ulp of error by
    # both platforms' libraries, so two engines computing this formula over the
    # same inputs legitimately differ in the last bit — and did, by 1e-10 m. A
    # millimetre is four orders of magnitude below any GPS fix this platform
    # accepts, so nothing real is lost and a whole class of divergence goes.
    return round(2 * radius * math.asin(math.sqrt(h)), 3)


def _as_number(value: Any) -> float | None:
    """A value as a number for `int`/`dec` (§4.3.1), or None if it is not one.

    Text is parsed after trimming surrounding whitespace and nothing else:
    a thousands separator or a currency symbol makes it unparseable rather than
    being stripped, because stripping one would be a coercion this IR does not
    have (§4.5).

    Booleans are deliberately not numbers. `int(true)` would be 1 in Python and
    null in a typed engine, and §4.4 keeps booleans and numbers apart
    everywhere else.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            # Unparseable text is null, never an error. A cast is evaluated on
            # every keystroke over whatever has been typed so far, and
            # `int("8a")` on the way to `int("81")` must not stop the form.
            return None
    return None


def _cast_int(ctx: EvalContext, args: list[Any]) -> Any:
    if _is_null(args[0]):
        return None
    number = _as_number(args[0])
    # Truncated toward zero, and via int() on the float so that `int("800.7")`
    # and `int(800.7)` are the same 800 — a cast whose result depended on where
    # the value came from would be worse than no cast.
    return None if number is None else int(number)


def _cast_dec(ctx: EvalContext, args: list[Any]) -> Any:
    if _is_null(args[0]):
        return None
    return _as_number(args[0])


def cast_str(ctx: EvalContext, args: list[Any]) -> Any:
    """`str()` (§4.3.1), public because §7.1 renders interpolated values with it.

    One implementation, so a value shown in a label is spelled exactly as the
    same value compared in an expression — `800` and not `800.0`.
    """
    return _cast_str(ctx, args)


def _cast_str(ctx: EvalContext, args: list[Any]) -> Any:
    if _is_null(args[0]):
        return None
    value = args[0]
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        # `str(dec("800"))` is "800", so it can be compared against a text
        # column. A trailing `.0` is an artefact of the float, not the value.
        return str(int(value))
    if isinstance(value, (dict, list)):
        return None
    return str(value)


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
    # `_text`, not a null check: these take text (§4.3) and a number is not
    # text until `str()` makes it one (§4.7). `upper(800)` raised AttributeError
    # for as long as this engine existed.
    "upper": (lambda c, a: _text1(str.upper, a[0]), 1, 1),
    "lower": (lambda c, a: _text1(str.lower, a[0]), 1, 1),
    "trim": (lambda c, a: _text1(str.strip, a[0]), 1, 1),
    "concat": (_fn_concat, 1, 99),
    "substr": (_fn_substr, 2, 3),
    "contains": (lambda c, a: _text2(lambda x, y: y in x, a[0], a[1]), 2, 2),
    "starts_with": (lambda c, a: _text2(lambda x, y: x.startswith(y), a[0], a[1]), 2, 2),
    "ends_with": (lambda c, a: _text2(lambda x, y: x.endswith(y), a[0], a[1]), 2, 2),
    "regex": (_fn_regex, 2, 2),
    "round": (_fn_round, 1, 2),
    "int": (_cast_int, 1, 1),
    "dec": (_cast_dec, 1, 1),
    "str": (_cast_str, 1, 1),
    "distance": (_fn_distance, 2, 2),
    "pulldata": (_fn_pulldata, 4, 4),
    "sqrt": (_fn_sqrt, 1, 1),
    "sin": (_trig(math.sin), 1, 1),
    "cos": (_trig(math.cos), 1, 1),
    "tan": (_trig(math.tan), 1, 1),
    "atan": (_trig(math.atan), 1, 1),
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
    "mod": _mod,
    "eq": _equal,
    "ne": lambda a, b: None if _equal(a, b) is None else not _equal(a, b),
    "lt": lambda a, b: _ordered(lambda x, y: x < y, a, b),
    "lte": lambda a, b: _ordered(lambda x, y: x <= y, a, b),
    "gt": lambda a, b: _ordered(lambda x, y: x > y, a, b),
    "gte": lambda a, b: _ordered(lambda x, y: x >= y, a, b),
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
        # lazy in both branches (spec 4.3); the condition takes a boolean and
        # anything else — including a non-empty string — is null (§4.7).
        cond = _boolean(evaluate(expr["args"][0], ctx))
        if cond is None:
            return None
        return evaluate(expr["args"][1] if cond else expr["args"][2], ctx)

    if op == "and":
        return _and([evaluate(a, ctx) for a in expr["args"]])

    if op == "or":
        return _or([evaluate(a, ctx) for a in expr["args"]])

    if op == "not":
        return _not(evaluate(expr["args"][0], ctx))

    if op == "neg":
        v = _number(evaluate(expr["args"][0], ctx))
        return None if v is None else -v

    if op == "div":
        a = _number(evaluate(expr["args"][0], ctx))
        b = _number(evaluate(expr["args"][1], ctx))
        if a is None or b is None or b == 0:
            return None  # division by zero yields null (spec 4.4.8)
        return a / b

    if op == "idiv":
        a = _number(evaluate(expr["args"][0], ctx))
        b = _number(evaluate(expr["args"][1], ctx))
        if a is None or b is None or b == 0:
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
        # Membership by `eq`'s rule, not Python's `in`: `selected(["1"], 1)`
        # must be false on both engines, and `in` would make it depend on how
        # each language happens to compare a string with a number.
        return any(_equal(item, needle) is True for item in _seq(haystack))

    if op == "in":
        needle = evaluate(expr["args"][0], ctx)
        haystack = evaluate(expr["args"][1], ctx)
        if _is_null(needle) or _is_null(haystack):
            return None
        return any(_equal(item, needle) is True for item in _seq(haystack))

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
