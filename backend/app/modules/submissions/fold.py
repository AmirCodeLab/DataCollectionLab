"""Folding the op log into current state — one implementation, two callers.

`submission_state` is a fold of the op log (sync §6), and until export existed
there was one place that computed it. Export needs the same fold and needs two
things more from it: which paths are ciphertext, and which repeat instances the
log says exist. Writing a second fold beside the first would be two answers to
"what does this submission currently say", and they would drift the way any two
hand-maintained copies in this repository have drifted — so the fold moved here
and `sync.service` calls it.

**Ordering is the caller's job and it is not negotiable**: `(counter, device_id)`,
never wall clock, never `server_seq` (sync §6, break 4). This function folds in
the order it is handed and says so rather than sorting, because a sort here
would silently paper over a query that forgot the ORDER BY.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

#: `members[i3].age` -> repeat `members`, instance `i3`, field `age`.
#: `members[i3]` -> the instance itself, which is what `repeat_delete` names.
INSTANCE_PATH = re.compile(
    r"^(?P<repeat>[a-z][a-z0-9_]*)\[(?P<instance>[^\]]+)\](?:\.(?P<field>.+))?$"
)


class FoldOp(Protocol):
    """The columns a fold reads. `SubmissionOp` satisfies it structurally."""

    op_kind: str
    path: str | None
    value: Any
    value_ciphertext: bytes | None
    content_key_id: str | None
    wall_clock: datetime
    server_seq: int


@dataclass(frozen=True)
class Fold:
    """What the log currently says, and what it declines to say."""

    #: Path -> current plaintext value. A path whose current value is
    #: ciphertext is **absent**, exactly as `submission_state.data` has always
    #: had it: a value the server cannot read has no place in a queryable fold.
    data: Mapping[str, Any] = field(default_factory=dict)
    #: Paths whose current value is ciphertext. Absence from `data` is not the
    #: same question — an unanswered field is absent too — and an export that
    #: cannot tell them apart writes a blank cell where an unreadable answer is,
    #: which every statistical tool reads as missing.
    unreadable: Mapping[str, str] = field(default_factory=dict)  # path -> content_key_id
    #: Repeat id -> stable instance ids, in the order the log created them.
    #: Never positions: §2.3 resolves a position against the current list, so a
    #: position means a different instance before and after a delete.
    instances: Mapping[str, Sequence[str]] = field(default_factory=dict)
    status: str | None = None
    finalized_at: datetime | None = None
    op_high_water: int = 0


def fold_ops(ops: Iterable[FoldOp]) -> Fold:
    """Fold ops **already ordered by `(counter, device_id)`** into current state."""
    data: dict[str, Any] = {}
    unreadable: dict[str, str] = {}
    instances: dict[str, list[str]] = {}
    status: str | None = None
    finalized_at: datetime | None = None
    high_water = 0

    def note_instance(path: str) -> None:
        found = INSTANCE_PATH.match(path)
        if found is None:
            return
        ordered = instances.setdefault(found["repeat"], [])
        if found["instance"] not in ordered:
            ordered.append(found["instance"])

    def forget(prefix: str) -> None:
        dot, bracket = prefix + ".", prefix + "["
        for store in (data, unreadable):
            for key in [
                k
                for k in store
                if k == prefix or k.startswith(dot) or k.startswith(bracket)
            ]:
                del store[key]

    for op in ops:
        high_water = max(high_water, op.server_seq)

        if op.op_kind == "set" and op.path is not None:
            note_instance(op.path)
            if op.value_ciphertext is not None:
                # Removing rather than skipping: in `field_level` mode a field
                # can be answered in plaintext and later re-answered under
                # encryption, and leaving the old plaintext behind would report
                # a superseded answer as current — and disclose the very value
                # the newer op was encrypted to protect.
                data.pop(op.path, None)
                if op.content_key_id is not None:
                    unreadable[op.path] = op.content_key_id
                continue
            data[op.path] = op.value
            # The other direction of the same rule: a later plaintext answer
            # makes the path readable again, so it stops being unreadable.
            unreadable.pop(op.path, None)
        elif op.op_kind == "unset" and op.path is not None:
            data.pop(op.path, None)
            unreadable.pop(op.path, None)
        elif op.op_kind == "repeat_add" and op.path is not None:
            # An instance with no answered field still exists, and a roster row
            # of blanks is a different fact from a member nobody recorded.
            note_instance(op.path)
        elif op.op_kind == "repeat_delete" and op.path is not None:
            forget(op.path)
            found = INSTANCE_PATH.match(op.path)
            if found is None:
                instances.pop(op.path, None)  # the whole repeat
            elif found["repeat"] in instances:
                ordered = instances[found["repeat"]]
                if found["instance"] in ordered:
                    ordered.remove(found["instance"])
        elif op.op_kind == "finalize":
            status, finalized_at = "finalized", op.wall_clock
        elif op.op_kind == "reopen":
            status, finalized_at = "draft", None

    return Fold(
        data=data,
        unreadable=unreadable,
        instances={rid: tuple(ordered) for rid, ordered in instances.items()},
        status=status,
        finalized_at=finalized_at,
        op_high_water=high_water,
    )
