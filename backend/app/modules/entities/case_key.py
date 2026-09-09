"""A composite record key: the parts joined with `|`, escaped (Form IR §3.1).

A sample whose row identity is several columns — RCons's `settlementCode +
structureId + hhId` — is published against one key composed from them, in the
order the publisher names the columns. Each part is the cell's value exactly
(§3.1's rule, unchanged), with `\\` written `\\\\` and `|` written `\\|`, and
the escaped parts joined with a single `|`. Splitting reads left to right: a
backslash takes the next character literally, an unescaped `|` is a boundary.

The escape is the specification's, not this module's choice, and it is a
backslash rather than a doubled pipe because doubling is ambiguous at a part
boundary: `("A|", "B")` and `("A", "|B")` would both read `A|||B`. With the
backslash, `("A|B")` is `A\\|B`, `("A", "B")` is `A|B`, and the two never meet.

An empty or whitespace-only part refuses the row, naming the column — the same
rule §3.1 applies to a single-column key.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

SEPARATOR = "|"
ESCAPE = "\\"


class CaseKeyRefused(ValueError):
    """A part with no identity: the row cannot be keyed."""

    def __init__(self, column: str) -> None:
        super().__init__(
            f"the key column `{column}` is empty in this row; a key part is the cell's "
            "value exactly, and a row with no identity cannot be selected, assigned "
            "or deleted in a later version"
        )
        self.column = column


def escape(part: str) -> str:
    return part.replace(ESCAPE, ESCAPE + ESCAPE).replace(SEPARATOR, ESCAPE + SEPARATOR)


def compose(parts: Sequence[str]) -> str:
    """The key for these parts, in this order."""
    return SEPARATOR.join(escape(part) for part in parts)


def split(key: str) -> list[str]:
    """The parts a key was composed from. `split(compose(p)) == p` for every
    list of strings, including ones with pipes and backslashes."""
    parts: list[str] = []
    current: list[str] = []
    i = 0
    while i < len(key):
        ch = key[i]
        if ch == ESCAPE and i + 1 < len(key):
            current.append(key[i + 1])
            i += 2
            continue
        if ch == SEPARATOR:
            parts.append("".join(current))
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    parts.append("".join(current))
    return parts


def key_of(row: Mapping[str, Any], key_columns: Sequence[str]) -> str:
    """The row's composite key, refusing a part that is not an identity."""
    parts: list[str] = []
    for column in key_columns:
        raw = row.get(column)
        part = "" if raw is None else str(raw)
        if not part.strip():
            raise CaseKeyRefused(column)
        parts.append(part)
    return compose(parts)
