"""Recording a review decision (item 6).

The only writer of a review state. Three things happen together, in one
transaction, or none of them do: the decision is appended to `review`, the
submission's status moves through the machine, and — when the decision sends
work back — the submission is marked as owed to the enumerator.

**Why a decision is not an op.** `submission_op.device_id` is `NOT NULL` and
`UNIQUE (device_id, counter)` is per device, so a server-authored op has no
device to be authored by and no counter it can safely take: allocating one on
the enumerator's device collides with whatever that device is about to push,
and the collision refuses the enumerator's own work. The analysis (item 6, A6)
proposed the server emit the `reopen`; building it showed that it cannot,
which is the part A6 flagged as owing a solution.

So the refinement, and it keeps everything A6 was for. The decision reaches
the device **in the ordinary pull**, as a statement of work owed back — the
same shape item 2's assignments statement already uses, and for the same
reason: a release is an absence, and only a statement can say "this one is
yours again". The `reopen` op is then authored by **the device that holds the
work**, when the enumerator opens it. The op log stays what it has always
been, a record of what devices did, and both folds handle the op identically.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ulid import new_ulid
from app.modules.submissions import status as machine

#: A decision that returns the work. `review_decision_check` admits four
#: values; these two are the ones that hand the submission back.
RETURNS_WORK = frozenset({"rejected", "correction_required"})

#: `review.decision` -> the machine's event.
_EVENT = {
    "approved": "approve",
    "rejected": "reject",
    "correction_required": "request_correction",
    "comment": "comment",
}


class ReviewRefused(Exception):
    """A decision the submission cannot take, with a sentence a person reads."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


@dataclass(frozen=True)
class Recorded:
    review_id: str
    status: str
    returns_work: bool


async def decide(
    session: AsyncSession,
    submission_id: str,
    *,
    reviewer_id: str,
    decision: str,
    comment: str | None,
) -> Recorded:
    """Record one decision, or refuse it by name.

    A comment with no decision is still a `review` row and moves nothing,
    which is what `review_decision_check`'s fourth value is for.
    """
    if decision not in _EVENT:
        raise ReviewRefused("unknown_decision", f"{decision!r} is not a review decision.")

    current = (
        await session.execute(
            text("SELECT status FROM submission WHERE id = :s"), {"s": submission_id}
        )
    ).scalar_one_or_none()
    if current is None:
        # Invisible under this principal is the same answer as absent: a
        # reviewer is told what they may know, which is nothing about it.
        raise ReviewRefused("not_found", "No such submission, or not one you may review.")

    if decision in RETURNS_WORK and not (comment or "").strip():
        # The reason is the whole feature. Work sent back without one puts the
        # enumerator in front of the same household with nothing to change.
        raise ReviewRefused(
            "reason_required",
            "Say what needs correcting. Work sent back without a reason arrives "
            "as a repeat of the same visit.",
        )

    try:
        moved = machine.next_status(str(current), _EVENT[decision])
    except machine.Refused as refusal:
        raise ReviewRefused("not_allowed", refusal.message) from refusal

    review_id = new_ulid()
    await session.execute(
        text(
            "INSERT INTO review (id, submission_id, reviewer_id, decision, comment) "
            "VALUES (:id, :s, :r, :d, :c)"
        ),
        {
            "id": review_id,
            "s": submission_id,
            "r": reviewer_id,
            "d": decision,
            "c": comment,
        },
    )
    if moved != current:
        await session.execute(
            text("UPDATE submission SET status = :v WHERE id = :s"),
            {"v": moved, "s": submission_id},
        )
    return Recorded(
        review_id=review_id, status=moved, returns_work=decision in RETURNS_WORK
    )


_RETURNED_SQL = """
    SELECT s.id AS submission_id,
           s.status,
           s.case_id,
           fv.form_id,
           fv.version AS form_version,
           r.comment AS reason,
           r.created_at AS decided_at,
           u.display_name AS decided_by
    FROM submission s
    JOIN form_version fv ON fv.id = s.form_version_id
    JOIN LATERAL (
        SELECT rv.comment, rv.created_at, rv.reviewer_id
        FROM review rv
        WHERE rv.submission_id = s.id AND rv.decision IN ('rejected', 'correction_required')
        ORDER BY rv.created_at DESC, rv.id DESC
        LIMIT 1
    ) r ON true
    LEFT JOIN platform_user u ON u.id = r.reviewer_id
    WHERE s.created_by = :user_id
      AND s.status IN ('rejected', 'correction_required')
    ORDER BY r.created_at DESC, s.id
"""


@dataclass(frozen=True)
class Returned:
    submission_id: str
    status: str
    case_id: str | None
    form_id: str
    form_version: int
    reason: str | None
    decided_at: datetime
    decided_by: str | None


async def returned_to(session: AsyncSession, user_id: str) -> list[Returned]:
    """The work a reviewer has handed back to this person, with the reason.

    A **complete statement**, like item 2's assignments: everything currently
    owed back, not a delta. A device that has been offline for a week gets the
    same answer as one that syncs every hour, and a submission that has since
    been resubmitted is simply absent — which is the only way an absence can
    mean "no longer owed" rather than "nothing new".

    Scoped to `created_by` on purpose: work goes back to the person who did
    it. Row-level security narrows this further to what the caller may see;
    the `WHERE` says whose statement it is.
    """
    rows = (
        (await session.execute(text(_RETURNED_SQL), {"user_id": user_id})).mappings().all()
    )
    return [
        Returned(
            submission_id=row["submission_id"],
            status=row["status"],
            case_id=row["case_id"],
            form_id=row["form_id"],
            form_version=row["form_version"],
            reason=row["reason"],
            decided_at=row["decided_at"],
            decided_by=row["decided_by"],
        )
        for row in rows
    ]
