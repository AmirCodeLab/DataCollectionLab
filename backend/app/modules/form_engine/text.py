"""Interpolated labels and constraint messages (Form IR §7.1).

A label may carry positional slots — `{0}`, `{1}` — filled from expressions, so
a form can say what it computed. `label` itself is still `{lang: string}`; the
expressions live beside it in `labelArgs`.

## The isolates are not cosmetic

Every non-empty value is wrapped in U+2068 FIRST STRONG ISOLATE and U+2069 POP
DIRECTIONAL ISOLATE, and **this is the part of the file most likely to be
deleted by somebody tidying up**, because two invisible codepoints look like
noise. They are the whole reason interpolation is safe to offer at all.

A run of Latin digits inside Arabic text is directionally *neutral at its
edges*. The Unicode bidirectional algorithm therefore resolves it against the
surrounding paragraph rather than on its own, and can move it: `الشعاع 15 م`
renders with the number in the wrong place, and a string holding two numbers
reorders outright. That is precisely the bug that produced `25 / 5` for a page
indicator that read `5 / 25` — the same class, in the same product, already once.

An isolate makes the inserted run opaque to the paragraph's resolution. It is
the only fix that works for every value rather than for the ones somebody
happened to test with, and it belongs in the engine so that two engines produce
the same string and one vector can assert it.

`conformance/vectors/label-004` asserts the codepoints by number. Removing this
fails loudly, which is the point.
"""

from __future__ import annotations

import re
from typing import Any

from .expression import EvalContext, evaluate

#: U+2068 / U+2069. Named rather than inlined so a search for either name finds
#: the reason above.
FIRST_STRONG_ISOLATE = "⁨"
POP_DIRECTIONAL_ISOLATE = "⁩"

#: `{0}`, with `{{` and `}}` for literal braces. Both halves, because `{{x}}`
#: with only the opening escape handled renders `{x}}` — which is the kind of
#: half-right that survives review.
_SLOT = re.compile(r"\{\{|\}\}|\{(\d+)\}")


def slot_indices(template: str) -> set[int]:
    """Every `{n}` the template refers to. `{{` is a literal and is not one."""
    return {
        int(match.group(1))
        for match in _SLOT.finditer(template)
        if match.group(1) is not None
    }


def isolate(text: str) -> str:
    """Wrap an interpolated value so bidi cannot drag it out of position.

    Empty stays empty: an isolate protects a run of text, and there is no run.
    """
    return text if not text else FIRST_STRONG_ISOLATE + text + POP_DIRECTIONAL_ISOLATE


def render(template: str, values: list[str]) -> str:
    """Fill `{n}` slots, isolating each value, and unescape `{{`."""

    def fill(match: re.Match[str]) -> str:
        if match.group(1) is None:
            return "{" if match.group(0) == "{{" else "}"
        index = int(match.group(1))
        # Out of range is a compile error (§7.1); by here it cannot happen, and
        # an empty string is the only thing left that is not a crash.
        return isolate(values[index]) if index < len(values) else ""

    return _SLOT.sub(fill, template)


def render_field_text(
    node: dict[str, Any],
    key: str,
    args_key: str,
    language: str,
    ctx: EvalContext,
    cast_str: Any,
) -> str | None:
    """One label or message in one language, interpolated (§7.1).

    Returns None when the node has no such text at all. A node with text and no
    arguments is returned verbatim — a document that predates §7.1 is
    substituted not at all, which is what keeps `{0}` in an old label safe.
    """
    strings = node.get(key)
    if not isinstance(strings, dict):
        return None
    template = strings.get(language)
    if not isinstance(template, str):
        return None

    args = node.get(args_key)
    if not args:
        return template

    values: list[str] = []
    for expression in args:
        value = evaluate(expression, ctx)
        rendered = cast_str(ctx, [value])
        # `str()` of null is null (§4.3.1); in text that is the empty string,
        # the same rule `concat` has and for the same reason.
        values.append("" if rendered is None else str(rendered))
    return render(template, values)
