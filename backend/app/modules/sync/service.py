"""Sync push and pull (specs/sync-protocol-v0.1.md).

Push is one transaction: validate each op individually, insert the new ones,
write tombstones for repeat deletions, fold the touched submissions into
submission_state, and write one outbox event per changed submission. A
rejected op never blocks the rest of the batch, and replaying an op that was
already accepted — same opId, or same (device_id, counter) — reports it as
accepted without writing anything, so retry is always safe.

Ordering is by (counter, device_id), NEVER by wall clock (spec §3). Device
clocks are wrong often enough in the field that clock-based ordering silently
corrupts data. server_seq is arrival order and only feeds the pull cursor.
"""

from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ulid import new_ulid
from app.modules.audit.models import OutboxEvent
from app.modules.forms.models import Form, FormVersion
from app.modules.projects.models import Device, Environment
from app.modules.submissions.models import Submission, SubmissionOp, SubmissionState
from app.modules.sync.models import Tombstone
from app.modules.sync.schemas import (
    PulledOp,
    PulledTombstone,
    PullResponse,
    PushResponse,
    RejectedOp,
    SyncOp,
)

# A submission in a terminal review state accepts no further ops. finalized is
# NOT terminal: corrections after finalisation are how the review loop works.
_CLOSED_STATUSES = {"approved", "rejected"}

# Environments a submission is implicitly created in, in preference order.
_ENVIRONMENT_PREFERENCE = ["production", "staging", "development"]

DEFAULT_PULL_LIMIT = 200
MAX_PULL_LIMIT = 500


class _Rejection(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason


async def push(
    session: AsyncSession, batch_device_id: str, raw_ops: list[dict[str, Any]]
) -> PushResponse:
    accepted: list[str] = []
    rejected: list[RejectedOp] = []

    ops: list[SyncOp] = []
    seen_op_ids: set[str] = set()
    for raw in raw_ops:
        op_id = raw.get("opId") if isinstance(raw.get("opId"), str) else None
        try:
            op = SyncOp.model_validate(raw)
        except ValidationError:
            rejected.append(RejectedOp(op_id=op_id, reason="malformed"))
            continue
        if op.op_id in seen_op_ids:
            # Duplicate within the batch: the first occurrence decides.
            accepted.append(op.op_id)
            continue
        seen_op_ids.add(op.op_id)
        ops.append(op)

    # Devices. The batch device and every op device must be registered and not
    # revoked. Op devices may differ from the batch device: a peer-to-peer
    # bundle relays another device's ops through the same path (spec §10).
    device_ids = {op.device_id for op in ops} | {batch_device_id}
    devices = {
        d.id: d
        for d in (await session.execute(select(Device).where(Device.id.in_(device_ids)))).scalars()
    }

    # Ops the server has already accepted. Same opId is a straight replay;
    # same (device_id, counter) under a different opId is a device replaying
    # after losing its own log — both are reported accepted, never an error.
    known_ids: set[str] = set()
    known_counters: set[tuple[str, int]] = set()
    if ops:
        rows = await session.execute(
            select(SubmissionOp.id, SubmissionOp.device_id, SubmissionOp.counter).where(
                SubmissionOp.id.in_([op.op_id for op in ops])
                | tuple_(SubmissionOp.device_id, SubmissionOp.counter).in_(
                    [(op.device_id, op.counter) for op in ops]
                )
            )
        )
        for row in rows:
            known_ids.add(row.id)
            known_counters.add((row.device_id, row.counter))

    submissions = {
        s.id: s
        for s in (
            await session.execute(
                select(Submission).where(Submission.id.in_({op.submission_id for op in ops}))
            )
        ).scalars()
    }

    form_version_cache: dict[tuple[str, str, int], str | None] = {}

    async def resolve_form_version(project_id: str, form_key: str, version: int) -> str | None:
        key = (project_id, form_key, version)
        if key not in form_version_cache:
            form_version_cache[key] = (
                await session.execute(
                    select(FormVersion.id)
                    .join(Form, Form.id == FormVersion.form_id)
                    .where(
                        Form.project_id == project_id,
                        Form.form_key == form_key,
                        FormVersion.version == version,
                    )
                )
            ).scalar_one_or_none()
        return form_version_cache[key]

    environment_cache: dict[str, str | None] = {}

    async def resolve_environment(project_id: str) -> str | None:
        if project_id not in environment_cache:
            envs = {
                e.kind: e.id
                for e in (
                    await session.execute(
                        select(Environment).where(Environment.project_id == project_id)
                    )
                ).scalars()
            }
            environment_cache[project_id] = next(
                (envs[k] for k in _ENVIRONMENT_PREFERENCE if k in envs), None
            )
        return environment_cache[project_id]

    to_insert: list[SubmissionOp] = []
    tombstones: list[Tombstone] = []
    touched: dict[str, list[str]] = {}

    for op in ops:
        if op.op_id in known_ids or (op.device_id, op.counter) in known_counters:
            accepted.append(op.op_id)
            continue
        try:
            device = devices.get(op.device_id)
            if device is None or device.revoked_at is not None:
                raise _Rejection("not_authorized")

            form_version_id = await resolve_form_version(
                device.project_id, op.form_id, op.form_version
            )
            if form_version_id is None:
                raise _Rejection("unknown_form_version")

            submission = submissions.get(op.submission_id)
            if submission is None:
                environment_id = await resolve_environment(device.project_id)
                if environment_id is None:
                    # A project with no environment cannot receive data; the
                    # device is effectively not authorised to submit to it.
                    raise _Rejection("not_authorized")
                submission = Submission(
                    id=op.submission_id,
                    project_id=device.project_id,
                    environment_id=environment_id,
                    form_version_id=form_version_id,
                    origin_device_id=op.device_id,
                    created_by=op.actor_id,
                    status="draft",
                    started_at=op.wall_clock,
                )
                session.add(submission)
                submissions[submission.id] = submission
            else:
                if submission.project_id != device.project_id:
                    raise _Rejection("not_authorized")
                if submission.status in _CLOSED_STATUSES:
                    raise _Rejection("submission_closed")
                if submission.form_version_id != form_version_id:
                    # A ciphertext-style relocation of ops across versions;
                    # the op does not match the submission's pinned version.
                    raise _Rejection("unknown_form_version")
        except _Rejection as rejection:
            rejected.append(RejectedOp(op_id=op.op_id, reason=rejection.reason))
            continue

        to_insert.append(
            SubmissionOp(
                id=op.op_id,
                submission_id=op.submission_id,
                op_kind=op.kind,
                path=op.path,
                value=op.value,
                device_id=op.device_id,
                actor_id=op.actor_id,
                counter=op.counter,
                wall_clock=op.wall_clock,
            )
        )
        if op.kind == "repeat_delete":
            tombstones.append(
                Tombstone(
                    id=new_ulid(),
                    project_id=devices[op.device_id].project_id,
                    subject_type="repeat_instance",
                    subject_id=f"{op.submission_id}:{op.path}",
                    submission_id=op.submission_id,
                    path=op.path,
                    device_id=op.device_id,
                    counter=op.counter,
                )
            )
        # These pairs are now taken within this batch too.
        known_counters.add((op.device_id, op.counter))
        touched.setdefault(op.submission_id, []).append(op.op_id)
        accepted.append(op.op_id)

    # Implicitly created submissions must hit the database before the ops
    # that reference them: without relationship()s the unit of work does not
    # order inserts across mappers.
    await session.flush()
    session.add_all(to_insert)
    session.add_all(tombstones)
    await session.flush()

    for submission_id, op_ids in touched.items():
        await _fold_submission(session, submissions[submission_id])
        session.add(
            OutboxEvent(
                id=new_ulid(),
                topic="sync.submission.ops_accepted",
                payload={
                    "submissionId": submission_id,
                    "opIds": op_ids,
                    "pushedBy": batch_device_id,
                },
            )
        )

    # Advance each device's accepted high-water counter (authoritative state).
    for device_id in {o.device_id for o in to_insert}:
        top = max(o.counter for o in to_insert if o.device_id == device_id)
        device = devices[device_id]
        device.last_counter = max(device.last_counter, top)
        device.last_sync_at = datetime.now(tz=UTC)

    await session.flush()
    return PushResponse(
        accepted=accepted, rejected=rejected, server_cursor=await _server_cursor(session)
    )


async def _fold_submission(session: AsyncSession, submission: Submission) -> None:
    """Recompute materialised state from the full op log.

    Field-level last-writer-wins ordered by (counter, device_id) — deviceId is
    the deterministic tiebreak so every replica converges (spec §6). Phase 0
    refolds from scratch; snapshot-bounded folding (spec §8) comes later.
    """
    ops = (
        (
            await session.execute(
                select(SubmissionOp)
                .where(SubmissionOp.submission_id == submission.id)
                .order_by(SubmissionOp.counter, SubmissionOp.device_id)
            )
        )
        .scalars()
        .all()
    )

    data: dict[str, Any] = {}
    status: str | None = None
    finalized_at: datetime | None = None
    for op in ops:
        if op.op_kind == "set" and op.path is not None:
            data[op.path] = op.value
        elif op.op_kind == "unset" and op.path is not None:
            data.pop(op.path, None)
        elif op.op_kind == "repeat_add":
            # Instance existence is carried by the set ops beneath the path.
            pass
        elif op.op_kind == "repeat_delete" and op.path is not None:
            dot, bracket = op.path + ".", op.path + "["
            data = {
                k: v
                for k, v in data.items()
                if k != op.path and not k.startswith(dot) and not k.startswith(bracket)
            }
        elif op.op_kind == "finalize":
            status, finalized_at = "finalized", op.wall_clock
        elif op.op_kind == "reopen":
            status, finalized_at = "draft", None

    # Ops only move a submission between draft and finalized; review states
    # (in_review, approved, ...) belong to the review workflow, not to sync.
    if status is not None and submission.status in ("draft", "finalized"):
        submission.status = status
        submission.finalized_at = finalized_at

    values = {
        "data": data,
        "op_high_water": max(op.server_seq for op in ops) if ops else 0,
        "computed_at": func.now(),
    }
    await session.execute(
        pg_insert(SubmissionState)
        .values(submission_id=submission.id, **values)
        .on_conflict_do_update(index_elements=["submission_id"], set_=values)
    )


async def _server_cursor(session: AsyncSession) -> int:
    op_max = (await session.execute(select(func.max(SubmissionOp.server_seq)))).scalar()
    tomb_max = (await session.execute(select(func.max(Tombstone.server_seq)))).scalar()
    return max(op_max or 0, tomb_max or 0)


async def pull(session: AsyncSession, cursor: int, limit: int) -> PullResponse:
    """Everything accepted after `cursor`, oldest arrival first, bounded.

    Ops and tombstones share one sequence, so one integer resumes both
    streams. The client persists nextCursor only after the batch is durably
    written locally (spec §5).
    """
    ops = (
        (
            await session.execute(
                select(SubmissionOp)
                .where(SubmissionOp.server_seq > cursor)
                .order_by(SubmissionOp.server_seq)
                .limit(limit + 1)
            )
        )
        .scalars()
        .all()
    )
    tombstones = (
        (
            await session.execute(
                select(Tombstone)
                .where(Tombstone.server_seq > cursor)
                .order_by(Tombstone.server_seq)
                .limit(limit + 1)
            )
        )
        .scalars()
        .all()
    )

    merged: list[tuple[int, str, Any]] = sorted(
        [(op.server_seq, "op", op) for op in ops]
        + [(t.server_seq, "tombstone", t) for t in tombstones]
    )
    batch = merged[:limit]
    has_more = len(merged) > len(batch)
    next_cursor = batch[-1][0] if batch else cursor

    # Pulled ops carry formId/formVersion so a fresh device can validate and
    # fold them without extra requests (spec §2 wire shape).
    submission_ids = {op.submission_id for _, kind, op in batch if kind == "op"}
    form_info: dict[str, tuple[str, int]] = {}
    if submission_ids:
        rows = await session.execute(
            select(Submission.id, Form.form_key, FormVersion.version)
            .join(FormVersion, FormVersion.id == Submission.form_version_id)
            .join(Form, Form.id == FormVersion.form_id)
            .where(Submission.id.in_(submission_ids))
        )
        form_info = {row.id: (row.form_key, row.version) for row in rows}

    pulled_ops: list[PulledOp] = []
    pulled_tombstones: list[PulledTombstone] = []
    for _, kind, row in batch:
        if kind == "op":
            form_key, version = form_info[row.submission_id]
            pulled_ops.append(
                PulledOp(
                    op_id=row.id,
                    submission_id=row.submission_id,
                    form_id=form_key,
                    form_version=version,
                    kind=row.op_kind,
                    path=row.path,
                    value=row.value,
                    device_id=row.device_id,
                    actor_id=row.actor_id,
                    counter=row.counter,
                    wall_clock=row.wall_clock,
                    server_seq=row.server_seq,
                )
            )
        else:
            pulled_tombstones.append(
                PulledTombstone(
                    id=row.id,
                    subject_type=row.subject_type,
                    subject_id=row.subject_id,
                    submission_id=row.submission_id,
                    path=row.path,
                    device_id=row.device_id,
                    counter=row.counter,
                    created_at=row.created_at,
                    expires_at=row.expires_at,
                    server_seq=row.server_seq,
                )
            )

    return PullResponse(
        ops=pulled_ops,
        tombstones=pulled_tombstones,
        next_cursor=next_cursor,
        has_more=has_more,
    )
