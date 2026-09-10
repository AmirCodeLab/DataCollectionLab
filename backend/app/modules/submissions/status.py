"""What a submission's status may become, and who may ask (item 6).

`submission.status` has two kinds of author. The **device** moves it by
appending ops — a `finalize` or a `reopen`, folded out of the log. The
**reviewer** moves it by making a decision. They are not two columns and not
two state machines, and the whole of this module exists because expressing
that as a condition at one call site is what produced defect 27.

The line it replaces read:

    if folded.status is not None and submission.status in ("draft", "finalized"):

which is right about its intent — sync must not overwrite a review decision —
and wrong as a mechanism. It states which states *sync* may leave, and thereby
decides, silently, which states *anything* may leave. A submission a reviewer
moved to `correction_required` could never leave it: the enumerator's ops were
accepted, the fold ran, the data updated, and the status stayed put for the
rest of its life. Nothing errored at any step. See `docs/known-defects.md` 27.

So the table is the object. Both authors go through `next_status`, a refusal is
a value rather than an exception at one of the callers, and adding a state
means adding a row rather than remembering a call site.
"""

from __future__ import annotations

from typing import Literal, get_args

#: Every status `submission_status_check` admits (001).
type Status = Literal[
    "draft", "finalized", "in_review", "approved", "rejected", "correction_required"
]

#: What can be asked of a submission. The first two are folded out of the op
#: log; the rest are a reviewer's decision and match `review_decision_check`.
type Event = Literal[
    "finalize", "reopen", "approve", "reject", "request_correction", "comment"
]

STATUSES: tuple[str, ...] = get_args(Status.__value__)
EVENTS: tuple[str, ...] = get_args(Event.__value__)

#: The whole machine. A missing (status, event) pair is a refusal, so every
#: transition that is allowed is written here and nowhere else.
#:
#: Three rows are worth reading twice.
#:
#: `correction_required` + `finalize` -> `finalized` is defect 27's fix, and
#: the reason this module exists: work that was sent back and redone re-enters
#: the queue and re-covers its case on item 5's dashboard.
#:
#: `correction_required` + `reopen` -> `correction_required` **absorbs**. When
#: a reviewer asks for a correction the submission is reopened, so the log's
#: net status becomes `draft` and stays there while the enumerator works. If
#: that folded `draft` were written through, the submission would lose the one
#: fact that distinguishes "sent back, being redone" from "never finished",
#: and it would vanish from any list of work owed back to a reviewer.
#:
#: `approved` and `rejected` accept nothing. That is what `_CLOSED_STATUSES` in
#: the sync service already says, moved to where it can be read beside the
#: transitions it constrains.
_TABLE: dict[str, dict[str, str]] = {
    "draft": {
        "finalize": "finalized",
        "reopen": "draft",
        "comment": "draft",
    },
    "finalized": {
        "finalize": "finalized",
        "reopen": "draft",
        "approve": "approved",
        "reject": "rejected",
        "request_correction": "correction_required",
        "comment": "finalized",
    },
    "in_review": {
        "finalize": "finalized",
        "reopen": "draft",
        "approve": "approved",
        "reject": "rejected",
        "request_correction": "correction_required",
        "comment": "in_review",
    },
    "correction_required": {
        "finalize": "finalized",
        "reopen": "correction_required",
        "approve": "approved",
        "reject": "rejected",
        "request_correction": "correction_required",
        "comment": "correction_required",
    },
    "approved": {},
    "rejected": {},
}

#: Events a device can cause by pushing ops. Everything else needs a person
#: holding `submission.review`.
DEVICE_EVENTS: frozenset[str] = frozenset({"finalize", "reopen"})

#: The two states that accept nothing at all. The sync service refuses ops on
#: these with `submission_closed` rather than accepting them and discarding
#: the transition, so an enumerator is told rather than left collecting into
#: a submission nobody will read.
CLOSED: frozenset[str] = frozenset(
    status for status, moves in _TABLE.items() if not moves
)


class Refused(Exception):
    """A transition the machine does not admit, with a sentence saying why.

    Carried rather than raised at a call site so both authors refuse the same
    way and a route can turn it into a named reason.
    """

    def __init__(self, current: str, event: str, message: str) -> None:
        super().__init__(message)
        self.current = current
        self.event = event
        self.message = message


_CLOSED_MESSAGE = {
    "approved": "This submission has been approved. Approving, rejecting or "
    "correcting it again would rewrite a decision somebody has already acted on.",
    "rejected": "This submission has been rejected. It is closed, and work on it "
    "cannot continue.",
}


def next_status(current: str, event: str) -> str:
    """The status after `event`, or `Refused`.

    `current` is what the row says now, not what the log says: the log has no
    opinion about review states and never will.
    """
    if current not in _TABLE:
        raise Refused(current, event, f"{current!r} is not a submission status.")
    if event not in EVENTS:
        raise Refused(current, event, f"{event!r} is not something a submission can be asked.")
    moves = _TABLE[current]
    if not moves:
        raise Refused(current, event, _CLOSED_MESSAGE[current])
    if event not in moves:
        raise Refused(
            current,
            event,
            f"A submission in {current!r} cannot be {_ASKED[event]}.",
        )
    return moves[event]


_ASKED = {
    "finalize": "finalised",
    "reopen": "reopened",
    "approve": "approved",
    "reject": "rejected",
    "request_correction": "sent back for correction",
    "comment": "commented on",
}


def event_for_folded(folded_status: str | None) -> str | None:
    """The device's event, read off the fold.

    `fold_ops` reports the net of the whole log: `finalized` when the last
    finalisation-affecting op was a `finalize`, `draft` when it was a `reopen`,
    and `None` when the log holds neither. It is not the submission's status
    and must not be assigned to one — that assignment is defect 27.
    """
    if folded_status is None:
        return None
    return "finalize" if folded_status == "finalized" else "reopen"
