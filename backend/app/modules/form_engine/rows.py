"""Choice lists made of a repeat's instances: Form IR §3.3.

The identity half of the roster problem. `docs/proposal-answer-indexed-rows.md`
§3 is the argument for why this exists rather than `members[${line}]`: a
position is not stable, so deleting a row renumbers every row below it and an
answer that was correct becomes wrong retroactively, naming a different person,
with nothing in an error state. An instance id does not renumber — `restore()`
exists so that a server adopts the device's ids rather than minting fresh ones
— so an answer holding one means the same member for the life of the
submission.

## Why this is not `datasets.py` with a different source

A dataset-backed list is decomposed into a **selector** a store can answer from
an index and a **residual** evaluated per candidate row (§3.2), because the
alternative is a scan over 37,852 villages on a handset. None of that applies
here and pretending it did would be worse than useless:

- there is no store and no index. The candidates are `instances[repeat]`, a
  list the engine is already holding, and one pass over a household's members
  is the whole cost (§3.3's contract is O(instances), and a roster large enough
  for the difference to show is not a roster);
- a selector term is `$row.column = <expr>`, and `$row.field` here is an
  *answer* of the candidate instance, which no source could look up anyway.

So the filter stays whole and is evaluated per candidate, and this module is
small on purpose: the decomposition is the interesting part of §3.2 and there
is nothing to decompose in §3.3.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RowsQuery:
    """A `choices.kind = "rows"` block, compiled (§3.3).

    Immutable and computed once per field, for the same reason `ChoiceQuery`
    is: the same document must mean the same thing on every engine.
    """

    #: The repeat whose instances are the options.
    repeat: str
    #: Omit the instance the field is being answered in. A §10.2 semantic error
    #: on a field that is not inside `repeat` — there is nothing to exclude
    #: there, and a flag that silently did nothing would be a control that does
    #: nothing. `docs/decision-rows-self-exclusion.md` is why it is a flag and
    #: not an identity comparison an author writes.
    exclude_self: bool = False
    #: Evaluated per candidate instance, whole. `$row.field` is that instance's
    #: value of that field; every other reference resolves from the scope the
    #: field is being answered in, which is what lets a filter compare the two.
    filter: Any | None = None


def compile_rows_choices(choices: Mapping[str, Any]) -> RowsQuery | None:
    """Compile a `choices.kind = "rows"` block, or None if it is another kind."""
    if choices.get("kind") != "rows":
        return None
    return RowsQuery(
        repeat=str(choices.get("repeat", "")),
        exclude_self=choices.get("excludeSelf") is True,
        filter=choices.get("filter"),
    )
