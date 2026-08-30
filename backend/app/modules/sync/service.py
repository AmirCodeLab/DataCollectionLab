"""Sync push and pull (specs/sync-protocol-v0.1.md).

Push is one transaction: validate each op individually, store the content keys
the batch carries, insert the new ops, write tombstones for repeat deletions,
fold the touched submissions into submission_state, and write one outbox event
per changed submission. A rejected op never blocks the rest of the batch, and
replaying an op that was already accepted — same opId, or same
(device_id, counter) — reports it as accepted without writing anything, so
retry is always safe.

Encrypted ops (spec §2.1) pass through untouched: the server stores the
ciphertext, the content key id and the nonce, and holds no key that could open
any of them. Its one cryptographic duty is refusing a repeated
(content_key_id, nonce) — AES-GCM fails catastrophically on nonce reuse
(encryption envelope §4.5) — which it can do without decrypting anything.

Ordering is by (counter, device_id), NEVER by wall clock (spec §3). Device
clocks are wrong often enough in the field that clock-based ordering silently
corrupts data. server_seq is arrival order and only feeds the pull cursor.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, null, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ulid import new_ulid
from app.modules.audit.models import OutboxEvent
from app.modules.crypto.models import ProjectKey
from app.modules.forms.models import Form, FormVersion
from app.modules.media import service as media_service
from app.modules.projects.models import Device, Environment
from app.modules.submissions.models import (
    Submission,
    SubmissionContentKey,
    SubmissionOp,
    SubmissionState,
    SubmissionWrappedKey,
)
from app.modules.sync.models import Tombstone
from app.modules.sync.schemas import (
    ContentKeyIn,
    PulledOp,
    PulledTombstone,
    PullResponse,
    PushResponse,
    RejectedOp,
    RejectReason,
    SyncOp,
)

# A submission in a terminal review state accepts no further ops. finalized is
# NOT terminal: corrections after finalisation are how the review loop works.
_CLOSED_STATUSES = {"approved", "rejected"}

# Environments a submission is implicitly created in, in preference order.
_ENVIRONMENT_PREFERENCE = ["production", "staging", "development"]

DEFAULT_PULL_LIMIT = 200
MAX_PULL_LIMIT = 500

# Postgres names these from the column list. Matched by name so a race that
# reaches the index instead of the pre-check still produces a stated reason
# rather than a 500.
_NONCE_CONSTRAINT = "submission_op_content_key_id_nonce_key"
_COUNTER_CONSTRAINT = "submission_op_device_id_counter_key"


class _Rejection(Exception):
    def __init__(self, reason: RejectReason) -> None:
        self.reason: RejectReason = reason


async def push(
    session: AsyncSession,
    batch_device_id: str,
    raw_ops: list[dict[str, Any]],
    raw_keys: Sequence[ContentKeyIn] = (),
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
    device_ids = (
        {op.device_id for op in ops} | {key.device_id for key in raw_keys} | {batch_device_id}
    )
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

    # Content keys may name a submission this batch has no ops for — a device
    # re-sending a key after its ops were already accepted, say — so they widen
    # the lookup too.
    referenced_submissions = {op.submission_id for op in ops} | {
        key.submission_id for key in raw_keys
    }
    submissions = {
        s.id: s
        for s in (
            await session.execute(
                select(Submission).where(Submission.id.in_(referenced_submissions))
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
    # Keyed by the op that produced it, so an op the database refuses at the
    # last moment does not leave a tombstone for a deletion that never happened.
    tombstones: dict[str, Tombstone] = {}
    touched: dict[str, list[str]] = {}
    # Ops past the device/form/submission gate. The crypto gate runs afterwards
    # because it needs to know which submissions this batch will have created.
    admitted: list[SyncOp] = []

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

        admitted.append(op)

    # Implicitly created submissions must hit the database before the content
    # keys and ops that reference them: without relationship()s the unit of
    # work does not order inserts across mappers.
    await session.flush()

    # Content keys the batch carries, plus the ones the server already holds.
    # A key is admitted only when everything it points at resolves, so an op
    # can never end up referencing a key row that failed to insert.
    key_submissions = await _admit_content_keys(session, raw_keys, submissions, devices)
    key_submissions.update(
        await _stored_content_keys(
            session, {op.content_key_id for op in admitted if op.is_encrypted}
        )
    )
    taken_nonces = await _taken_nonces(session, admitted)
    await session.flush()

    for op in admitted:
        if op.is_encrypted:
            # mypy: is_encrypted guarantees all three fields are present.
            assert op.content_key_id is not None and op.nonce is not None
            if key_submissions.get(op.content_key_id) != op.submission_id:
                # Either the key never arrived, or it belongs to a different
                # submission and its ciphertext could never authenticate here.
                rejected.append(RejectedOp(op_id=op.op_id, reason="unknown_content_key"))
                continue
            nonce = bytes.fromhex(op.nonce)
            if (op.content_key_id, nonce) in taken_nonces:
                rejected.append(RejectedOp(op_id=op.op_id, reason="nonce_reused"))
                continue
            taken_nonces.add((op.content_key_id, nonce))
        else:
            nonce = None

        if (op.device_id, op.counter) in known_counters:
            # A second op in this same batch claiming a counter an earlier one
            # already took: the first occurrence decides, as for a duplicate
            # opId.
            accepted.append(op.op_id)
            continue
        known_counters.add((op.device_id, op.counter))

        to_insert.append(
            SubmissionOp(
                id=op.op_id,
                submission_id=op.submission_id,
                op_kind=op.kind,
                path=op.path,
                # SQL NULL, not JSON null: a JSONB column turns a Python None
                # into the JSON value `null`, which is a stored value and fails
                # submission_op_encryption_check. The constraint is right to
                # care — "no plaintext here" and "the answer is null" are
                # different facts about someone's data.
                value=null() if op.is_encrypted else op.value,
                value_ciphertext=(
                    bytes.fromhex(op.value_ciphertext) if op.value_ciphertext else None
                ),
                content_key_id=op.content_key_id,
                nonce=nonce,
                device_id=op.device_id,
                actor_id=op.actor_id,
                counter=op.counter,
                wall_clock=op.wall_clock,
            )
        )
        if op.kind == "repeat_delete":
            tombstones[op.op_id] = Tombstone(
                id=new_ulid(),
                project_id=devices[op.device_id].project_id,
                subject_type="repeat_instance",
                subject_id=f"{op.submission_id}:{op.path}",
                submission_id=op.submission_id,
                path=op.path,
                device_id=op.device_id,
                counter=op.counter,
            )
        touched.setdefault(op.submission_id, []).append(op.op_id)
        accepted.append(op.op_id)

    # The pre-checks above see only what was committed when they ran. A
    # concurrent push can still take a nonce or a counter in between, so the
    # index has the last word — and turns it into the same stated reason.
    refused = await _insert_ops(session, to_insert)
    if refused:
        to_insert = [row for row in to_insert if row.id not in refused]
        for op_id, reason in refused.items():
            if reason is None:
                # A counter collision means the op is already stored under
                # another id: the replay verdict, which is acceptance.
                continue
            accepted.remove(op_id)
            rejected.append(RejectedOp(op_id=op_id, reason=reason))
        touched = {
            submission_id: kept
            for submission_id, op_ids in touched.items()
            if (kept := [op_id for op_id in op_ids if op_id not in refused])
        }

    session.add_all([t for op_id, t in tombstones.items() if op_id not in refused])
    await session.flush()

    # Media the accepted ops referenced. The op is accepted whether or not the
    # file has arrived — it usually has not, since a device finishes a
    # questionnaire in minutes and a 3 MB photograph when it next sees a tower
    # (sync §9) — so the reference is recorded as `pending` and the two halves
    # pair up whenever the second one lands.
    #
    # Plaintext ops only. In an encrypting project the reference is inside a
    # ciphertext the server has no key for, and the pairing is made from the
    # other end instead: the client names `opId` when it opens the upload
    # session. Nothing here tries to guess at a value it cannot read.
    await media_service.register_pending_references(
        session,
        [
            (media_id, row.submission_id, row.id, row.path or "")
            for row in to_insert
            if row.op_kind == "set" and row.value_ciphertext is None
            for media_id in (media_service.media_reference_id(row.value),)
            if media_id is not None
        ],
    )

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


async def _stored_content_keys(
    session: AsyncSession, content_key_ids: set[str | None]
) -> dict[str, str]:
    """{content_key_id: submission_id} for the keys the server already holds."""
    wanted = {key_id for key_id in content_key_ids if key_id}
    if not wanted:
        return {}
    rows = await session.execute(
        select(SubmissionContentKey.id, SubmissionContentKey.submission_id).where(
            SubmissionContentKey.id.in_(wanted)
        )
    )
    return {row.id: row.submission_id for row in rows}


async def _admit_content_keys(
    session: AsyncSession,
    raw_keys: Sequence[ContentKeyIn],
    submissions: dict[str, Submission],
    devices: dict[str, Device],
) -> dict[str, str]:
    """Store the content keys this batch carries (encryption envelope §4.2–4.3).

    Returns {content_key_id: submission_id} for every key that will exist after
    the flush, so the caller can reject ops naming one that will not.

    A key whose submission, device or recipient set does not resolve is dropped
    rather than half-stored. The ops it covers are rejected `unknown_content_key`
    and retried on the next sync — recoverable. Storing a key wrapped to fewer
    recipients than the client believed is not: a recovery key holder would
    discover at the worst possible moment that their copy was never written.
    """
    if not raw_keys:
        return {}

    existing = (
        (
            await session.execute(
                select(SubmissionContentKey).where(
                    SubmissionContentKey.submission_id.in_({k.submission_id for k in raw_keys})
                )
            )
        )
        .scalars()
        .all()
    )
    stored_submission = {row.id: row.submission_id for row in existing}
    # One content key per device per submission (envelope §4.2). A device
    # offering a second one has lost its own key material; it must not silently
    # replace the key its earlier ops were encrypted with.
    owner_key = {(row.submission_id, row.device_id): row.id for row in existing}

    project_ids = {
        submissions[key.submission_id].project_id
        for key in raw_keys
        if key.submission_id in submissions
    }
    recipients: dict[str, set[str]] = {}
    if project_ids:
        rows = await session.execute(
            select(ProjectKey.id, ProjectKey.project_id).where(
                ProjectKey.project_id.in_(project_ids),
                ProjectKey.revoked_at.is_(None),
            )
        )
        for key_id, project_id in rows:
            recipients.setdefault(project_id, set()).add(key_id)

    admitted: dict[str, str] = {}
    for key in raw_keys:
        if key.content_key_id in stored_submission:
            # Immutable and idempotent: a re-send is a no-op, never an error.
            admitted[key.content_key_id] = stored_submission[key.content_key_id]
            continue

        submission = submissions.get(key.submission_id)
        device = devices.get(key.device_id)
        if submission is None or device is None or device.revoked_at is not None:
            continue
        if device.project_id != submission.project_id:
            continue
        if (key.submission_id, key.device_id) in owner_key:
            continue
        active = recipients.get(submission.project_id, set())
        if not all(wrap.project_key_id in active for wrap in key.wraps):
            continue

        session.add(
            SubmissionContentKey(
                id=key.content_key_id,
                submission_id=key.submission_id,
                device_id=key.device_id,
            )
        )
        for wrap in key.wraps:
            session.add(
                SubmissionWrappedKey(
                    content_key_id=key.content_key_id,
                    project_key_id=wrap.project_key_id,
                    submission_id=key.submission_id,
                    ephemeral_public=bytes.fromhex(wrap.ephemeral_public),
                    nonce=bytes.fromhex(wrap.nonce),
                    wrapped_key=bytes.fromhex(wrap.wrapped_key),
                )
            )
        owner_key[(key.submission_id, key.device_id)] = key.content_key_id
        admitted[key.content_key_id] = key.submission_id
    return admitted


async def _taken_nonces(
    session: AsyncSession, ops: Sequence[SyncOp]
) -> set[tuple[str, bytes]]:
    """Which (content_key_id, nonce) pairs in this batch the server already has.

    Envelope §4.5: a repeated pair means a device reused a logical counter, and
    AES-GCM under a reused nonce leaks the plaintext of both messages. The
    server can enforce this without holding a key.
    """
    pairs = {
        (op.content_key_id, bytes.fromhex(op.nonce))
        for op in ops
        if op.is_encrypted and op.content_key_id and op.nonce
    }
    if not pairs:
        return set()
    rows = await session.execute(
        select(SubmissionOp.content_key_id, SubmissionOp.nonce).where(
            SubmissionOp.content_key_id.in_({key_id for key_id, _ in pairs}),
            SubmissionOp.nonce.in_({nonce for _, nonce in pairs}),
        )
    )
    return {(row.content_key_id, bytes(row.nonce)) for row in rows} & pairs


def _integrity_reason(exc: IntegrityError) -> RejectReason | None:
    """Turn a unique-index violation into the reason a client can act on.

    None means "already stored" — a counter collision under a different opId,
    which the push path reports as accepted, the same as any other replay.
    Anything unrecognised propagates: a constraint we did not anticipate is a
    bug, and swallowing it would hide it behind a rejected op.
    """
    constraint = getattr(getattr(exc, "orig", None), "constraint_name", None) or str(exc.orig)
    if _NONCE_CONSTRAINT in constraint:
        return "nonce_reused"
    if _COUNTER_CONSTRAINT in constraint or "submission_op_pkey" in constraint:
        return None
    raise exc


async def _insert_ops(
    session: AsyncSession, rows: list[SubmissionOp]
) -> dict[str, RejectReason | None]:
    """Insert the batch's ops, naming any the database refuses.

    The fast path is one flush. It only falls back to a savepoint per op when
    that flush fails, which happens when a concurrent push took a nonce or a
    counter between our pre-check and our write. One loser must not cost the
    other 499 ops their push, and it must not surface as a 500 either.
    """
    if not rows:
        return {}
    try:
        async with session.begin_nested():
            session.add_all(rows)
            await session.flush()
        return {}
    except IntegrityError:
        pass

    refused: dict[str, RejectReason | None] = {}
    for row in rows:
        try:
            async with session.begin_nested():
                session.add(row)
                await session.flush()
        except IntegrityError as exc:
            refused[row.id] = _integrity_reason(exc)
    return refused


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
            if op.value_ciphertext is not None:
                # The current value of this path is one the server cannot read,
                # so it has no place in a queryable fold. Removing rather than
                # skipping matters: in field_level mode a field can be answered
                # in plaintext and later re-answered under encryption, and
                # leaving the old plaintext behind would report a superseded
                # answer as current — and disclose the very value the newer op
                # was encrypted to protect.
                data.pop(op.path, None)
                continue
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
                    # Relayed exactly as pushed: the server is a courier for
                    # these bytes, never a reader (envelope §3).
                    value_ciphertext=(
                        bytes(row.value_ciphertext).hex()
                        if row.value_ciphertext is not None
                        else None
                    ),
                    content_key_id=row.content_key_id,
                    nonce=bytes(row.nonce).hex() if row.nonce is not None else None,
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
