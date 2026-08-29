"""Read queries behind the console's submission views.

Read-only: nothing here writes, and nothing here re-folds. `submission_state`
is the fold that push already committed (`app/modules/sync/service.py`); the
op log is the source of truth behind it and is returned beside it so a
discrepancy is visible rather than hidden.
"""

from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.forms.models import Form, FormVersion
from app.modules.submissions.models import Submission, SubmissionOp, SubmissionState
from app.modules.submissions.schemas import (
    MAX_DETAIL_OPS,
    SubmissionDetail,
    SubmissionListResponse,
    SubmissionOpView,
    SubmissionStateView,
    SubmissionSummary,
)


def _op_counts() -> Any:
    """Per-submission op totals, as a subquery to join once instead of N times."""
    return (
        select(
            SubmissionOp.submission_id.label("submission_id"),
            func.count().label("op_count"),
        )
        .group_by(SubmissionOp.submission_id)
        .subquery()
    )


def _filtered(statement: Select[Any], form_id: str | None, status: str | None) -> Select[Any]:
    """Apply the console filters. `form_id` matches the wire key, not the row id."""
    if form_id is not None:
        statement = statement.where(Form.form_key == form_id)
    if status is not None:
        statement = statement.where(Submission.status == status)
    return statement


async def list_submissions(
    session: AsyncSession,
    *,
    form_id: str | None,
    status: str | None,
    limit: int,
    offset: int,
) -> SubmissionListResponse:
    """One page of submissions, newest arrival first.

    `received_at` alone is not a total order — a push commits many submissions
    with the same `now()` — so the ULID id breaks ties and paging never skips
    or repeats a row.
    """
    counts = _op_counts()

    total = (
        await session.execute(
            _filtered(
                select(func.count())
                .select_from(Submission)
                .join(FormVersion, FormVersion.id == Submission.form_version_id)
                .join(Form, Form.id == FormVersion.form_id),
                form_id,
                status,
            )
        )
    ).scalar_one()

    rows = await session.execute(
        _filtered(
            select(
                Submission,
                Form.form_key,
                Form.title,
                FormVersion.version,
                func.coalesce(counts.c.op_count, 0).label("op_count"),
            )
            .join(FormVersion, FormVersion.id == Submission.form_version_id)
            .join(Form, Form.id == FormVersion.form_id)
            .outerjoin(counts, counts.c.submission_id == Submission.id),
            form_id,
            status,
        )
        .order_by(Submission.received_at.desc(), Submission.id.desc())
        .limit(limit)
        .offset(offset)
    )

    return SubmissionListResponse(
        submissions=[
            SubmissionSummary(
                id=row.Submission.id,
                form_id=row.form_key,
                form_title=row.title,
                form_version=row.version,
                status=row.Submission.status,
                origin_device_id=row.Submission.origin_device_id,
                op_count=row.op_count,
                received_at=row.Submission.received_at,
            )
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


async def get_submission(session: AsyncSession, submission_id: str) -> SubmissionDetail | None:
    """Folded state plus the raw op log, or None when there is no such submission."""
    row = (
        await session.execute(
            select(Submission, Form.form_key, Form.title, FormVersion.version)
            .join(FormVersion, FormVersion.id == Submission.form_version_id)
            .join(Form, Form.id == FormVersion.form_id)
            .where(Submission.id == submission_id)
        )
    ).one_or_none()
    if row is None:
        return None
    submission = row.Submission

    op_count = (
        await session.execute(
            select(func.count())
            .select_from(SubmissionOp)
            .where(SubmissionOp.submission_id == submission_id)
        )
    ).scalar_one()

    # (counter, device_id): the order the fold replays in, so what the console
    # shows and what produced the state beside it are the same sequence.
    ops = (
        (
            await session.execute(
                select(SubmissionOp)
                .where(SubmissionOp.submission_id == submission_id)
                .order_by(SubmissionOp.counter, SubmissionOp.device_id)
                .limit(MAX_DETAIL_OPS)
            )
        )
        .scalars()
        .all()
    )

    state = (
        await session.execute(
            select(SubmissionState).where(SubmissionState.submission_id == submission_id)
        )
    ).scalar_one_or_none()

    return SubmissionDetail(
        id=submission.id,
        project_id=submission.project_id,
        form_id=row.form_key,
        form_title=row.title,
        form_version=row.version,
        status=submission.status,
        origin_device_id=submission.origin_device_id,
        created_by=submission.created_by,
        started_at=submission.started_at,
        finalized_at=submission.finalized_at,
        received_at=submission.received_at,
        op_count=op_count,
        state=(
            None
            if state is None
            else SubmissionStateView(
                data=state.data,
                op_high_water=state.op_high_water,
                computed_at=state.computed_at,
            )
        ),
        ops=[
            SubmissionOpView(
                id=op.id,
                kind=op.op_kind,
                path=op.path,
                # Ciphertext stays server-side; the console holds no keys.
                value=op.value,
                encrypted=op.value_ciphertext is not None,
                device_id=op.device_id,
                actor_id=op.actor_id,
                counter=op.counter,
                wall_clock=op.wall_clock,
                received_at=op.received_at,
                server_seq=op.server_seq,
            )
            for op in ops
        ],
        ops_truncated=op_count > len(ops),
    )
