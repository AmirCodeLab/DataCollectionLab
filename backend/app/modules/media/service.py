"""Resumable chunked media upload (sync protocol §9, encryption envelope §6).

Three calls, and one property that shapes all of them: **an operation and the
file it references arrive independently, in either order.** A device finishes a
questionnaire in minutes and finishes a 3 MB photograph when it next sees a
tower. So:

* an op naming media the server does not have is accepted and the media is
  marked `pending` (never a foreign key from media to submission_op — the op
  may genuinely not exist yet, and a constraint would turn the normal case into
  an error);
* opening a session for a file that is part-uploaded returns which chunks are
  already here, so a resumed upload sends only what is missing;
* a file that lands before its op is stored anyway and pairs up when the op
  arrives.

**The server never decrypts anything here.** For an encrypting project the
chunks are ciphertext under a per-file media key it has no copy of (§6), and
the hash it computes is over those ciphertext bytes. Hashing plaintext would
let it confirm that two submissions contain the same photograph, which is the
inference the mode exists to prevent — so it never sees plaintext to hash.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.ulid import new_ulid
from app.infrastructure.media_storage import chunk_hash, chunk_storage_key, get_media_store
from app.modules.crypto.models import ProjectKey
from app.modules.media.models import Media, MediaChunk, MediaUploadSession, MediaWrappedKey
from app.modules.media.schemas import (
    CHUNK_SIZE_BYTES,
    MediaChunkResponse,
    MediaCompleteRequest,
    MediaCompleteResponse,
    MediaKeysView,
    MediaPolicy,
    MediaPolicyResponse,
    MediaPolicyUpdate,
    MediaUploadFailure,
    MediaUploadSessionRequest,
    MediaUploadSessionResponse,
    MediaView,
    MediaWrappedKeyView,
    SubmissionMediaResponse,
    wire_chunk_size,
)
from app.modules.projects.models import Device, Project
from app.modules.submissions.models import Submission, SubmissionOp

# Modes in which the server holds no key for media content.
_ENCRYPTING_MODES = {"field_level", "project_e2e"}


class MediaError(Exception):
    """A refusal a client can act on: `reason` is the contract, `message` explains."""

    def __init__(self, status_code: int, reason: MediaUploadFailure, message: str) -> None:
        super().__init__(f"{reason}: {message}")
        self.status_code = status_code
        self.reason: MediaUploadFailure = reason
        self.message = message


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


async def open_session(
    session: AsyncSession, request: MediaUploadSessionRequest
) -> MediaUploadSessionResponse:
    """Open or resume an upload for one file.

    Idempotent on `mediaId`. A second call for a file already part-uploaded is
    how resumption starts, which is why there is no separate status endpoint:
    the resuming client has to make this call anyway, and a second way to ask
    the same question is a second thing that can disagree with the first.
    """
    device = (
        await session.execute(select(Device).where(Device.id == request.device_id))
    ).scalar_one_or_none()
    if device is None or device.revoked_at is not None:
        raise MediaError(
            403,
            "device_not_authorized",
            f"device {request.device_id!r} is not registered, or has been revoked. "
            "Register it with POST /api/v1/devices before uploading.",
        )

    submission = (
        await session.execute(select(Submission).where(Submission.id == request.submission_id))
    ).scalar_one_or_none()
    if submission is None or submission.project_id != device.project_id:
        # Not found and belongs-to-another-project are one refusal on purpose:
        # distinguishing them would tell an unauthorised caller which
        # submission ids exist.
        raise MediaError(
            404,
            "submission_not_found",
            f"no submission {request.submission_id!r} in this device's project. "
            "Push the submission's first operation before uploading its media.",
        )

    project = (
        await session.execute(select(Project).where(Project.id == device.project_id))
    ).scalar_one()

    _check_media_key(project, request)
    await _check_recipients(session, project.id, request)

    media = (
        await session.execute(select(Media).where(Media.id == request.media_id))
    ).scalar_one_or_none()

    if media is None:
        media = Media(
            id=request.media_id,
            submission_id=request.submission_id,
            op_id=request.op_id,
            device_id=request.device_id,
            field_path=request.field_path,
            mime_type=request.mime_type,
            size_bytes=request.size_bytes,
            chunk_count=request.chunk_count,
            encrypted=request.encrypted,
            content_key_id=request.content_key_id,
            status="uploading",
        )
        session.add(media)
        await session.flush()
        _store_wraps(session, media.id, request)
    else:
        if media.submission_id != request.submission_id or (
            media.device_id is not None and media.device_id != request.device_id
        ):
            # A media id is a client-generated ULID, so a collision means a
            # broken generator or a hostile client. Either way, silently
            # attaching new chunks to somebody else's file is not an option.
            raise MediaError(
                409,
                "media_conflict",
                f"media {request.media_id!r} already belongs to another submission "
                "or device.",
            )
        if media.status == "complete":
            # Already finished. Returning the full chunk list rather than
            # refusing means a client that lost the completion response stops
            # re-uploading instead of starting over.
            pass
        else:
            # A resumed upload may legitimately restate these — an image
            # recompressed at a new project quality setting, say — as long as
            # nothing has landed yet.
            received = await _received_indexes(session, media.id)
            if not received:
                media.mime_type = request.mime_type
                media.size_bytes = request.size_bytes
                media.chunk_count = request.chunk_count
                media.encrypted = request.encrypted
                media.content_key_id = request.content_key_id
                # Replace rather than add: a restated session may carry a new
                # media key (nothing has been encrypted under the old one yet,
                # since nothing has landed), and the wraps are keyed by
                # (media_id, project_key_id) — adding would collide with itself.
                await session.execute(
                    delete(MediaWrappedKey).where(MediaWrappedKey.media_id == media.id)
                )
                await session.flush()
                _store_wraps(session, media.id, request)
            media.status = "uploading"
            # The op id and path may only become known on a later attempt.
            media.op_id = media.op_id or request.op_id
            media.field_path = media.field_path or request.field_path
            media.device_id = media.device_id or request.device_id

    expires_at = datetime.now(tz=UTC) + timedelta(
        seconds=get_settings().media_session_ttl_seconds
    )
    upload = (
        await session.execute(
            select(MediaUploadSession).where(MediaUploadSession.media_id == media.id)
        )
    ).scalar_one_or_none()
    if upload is None:
        upload = MediaUploadSession(
            id=new_ulid(),
            media_id=media.id,
            chunk_size=CHUNK_SIZE_BYTES,
            received_chunks=0,
            expires_at=expires_at,
        )
        session.add(upload)
    else:
        # Resuming extends the window. A device that has been uploading through
        # a bad week should not lose its progress to a clock.
        upload.expires_at = expires_at
    await session.flush()

    received = await _received_indexes(session, media.id)
    return MediaUploadSessionResponse(
        upload_id=upload.id,
        media_id=media.id,
        chunk_size=CHUNK_SIZE_BYTES,
        chunk_count=media.chunk_count,
        received_chunks=received,
        status=media.status,
        expires_at=upload.expires_at,
    )


def _check_media_key(project: Project, request: MediaUploadSessionRequest) -> None:
    """A file in an encrypting project must arrive with wraps, or with none of
    the crypto fields at all.

    An encrypted file whose media key is wrapped to nobody is not protected
    data, it is destroyed data — and nothing later in the pipeline would notice,
    because ciphertext nobody can open looks exactly like ciphertext somebody
    can. This is the only moment the mistake is still recoverable.
    """
    if not request.encrypted:
        if project.security_mode in _ENCRYPTING_MODES:
            # Not refused. `field_level` encrypts sensitive fields only, and a
            # photograph of a building exterior in such a project is legitimately
            # in the clear. The decision is the client's, made from the form's
            # `sensitive` flags, and the server cannot second-guess it without
            # the form.
            return
        return

    if request.content_key_id is None:
        raise MediaError(
            422,
            "unwrapped_media_key",
            "an encrypted file must name the media key that opens it "
            "(contentKeyId, envelope §6).",
        )
    if not request.wraps:
        raise MediaError(
            422,
            "unwrapped_media_key",
            "an encrypted file must carry its media key wrapped to at least one "
            "project key. A media key wrapped to nobody is a file nobody can "
            "ever open again, including the people who collected it "
            "(envelope §4.3).",
        )


def _store_wraps(session: AsyncSession, media_id: str, request: MediaUploadSessionRequest) -> None:
    for wrap in request.wraps:
        session.add(
            MediaWrappedKey(
                media_id=media_id,
                project_key_id=wrap.project_key_id,
                ephemeral_public=bytes.fromhex(wrap.ephemeral_public),
                nonce=bytes.fromhex(wrap.nonce),
                wrapped_key=bytes.fromhex(wrap.wrapped_key),
            )
        )


async def _check_recipients(
    session: AsyncSession, project_id: str, request: MediaUploadSessionRequest
) -> None:
    """Every wrap must name an active project key of this device's project.

    Checked before anything is stored: a wrap to a key that is not a recipient
    is a wrap whose holder will never be asked for it, and storing it would make
    the file look better protected than it is.
    """
    if not request.wraps:
        return
    active = set(
        (
            await session.execute(
                select(ProjectKey.id).where(
                    ProjectKey.project_id == project_id,
                    ProjectKey.revoked_at.is_(None),
                )
            )
        ).scalars()
    )
    unknown = sorted({w.project_key_id for w in request.wraps} - active)
    if unknown:
        raise MediaError(
            422,
            "unknown_recipient",
            f"media key wrapped to {unknown} — not active recipients of this "
            "project. Refresh GET /api/v1/devices/{deviceId}/crypto and wrap again.",
        )


async def _received_indexes(session: AsyncSession, media_id: str) -> list[int]:
    return list(
        (
            await session.execute(
                select(MediaChunk.chunk_index)
                .where(MediaChunk.media_id == media_id)
                .order_by(MediaChunk.chunk_index)
            )
        ).scalars()
    )


async def _session_and_media(
    session: AsyncSession, upload_id: str
) -> tuple[MediaUploadSession, Media]:
    upload = (
        await session.execute(select(MediaUploadSession).where(MediaUploadSession.id == upload_id))
    ).scalar_one_or_none()
    if upload is None:
        raise MediaError(
            404,
            "session_not_found",
            f"no upload session {upload_id!r}. Open one with "
            "POST /api/v1/media/upload-sessions — it returns the chunks already "
            "stored, so nothing already uploaded is sent twice.",
        )
    if upload.expires_at <= datetime.now(tz=UTC):
        raise MediaError(
            410,
            "session_expired",
            f"upload session {upload_id!r} expired at {upload.expires_at.isoformat()}. "
            "Open a new one for the same mediaId; the chunks already stored are "
            "still there and will not be re-requested.",
        )
    media = (
        await session.execute(select(Media).where(Media.id == upload.media_id))
    ).scalar_one()
    return upload, media


# ---------------------------------------------------------------------------
# Chunks
# ---------------------------------------------------------------------------


async def put_chunk(
    session: AsyncSession, upload_id: str, chunk_index: int, data: bytes
) -> MediaChunkResponse:
    """Store one chunk. Idempotent: re-sending a stored chunk is a success.

    A client that lost the response cannot tell "stored" from "lost in transit",
    so making the retry safe is cheaper than making the client careful.
    """
    upload, media = await _session_and_media(session, upload_id)

    if not 0 <= chunk_index < media.chunk_count:
        raise MediaError(
            422,
            "chunk_out_of_range",
            f"chunk {chunk_index} is outside the declared range "
            f"0..{media.chunk_count - 1}.",
        )

    # The spec's 4 MiB is the PLAINTEXT chunk size; AES-GCM appends a 16-byte
    # tag, so an encrypted full chunk is 4 MiB + 16 on the wire. The server only
    # ever sees ciphertext and has to check against what actually arrives.
    full = wire_chunk_size(encrypted=media.encrypted)
    last = chunk_index == media.chunk_count - 1
    if not data:
        raise MediaError(422, "chunk_size_mismatch", "an empty chunk carries nothing.")
    if not last and len(data) != full:
        # Fixed size, not negotiated (envelope §6). The nonce for chunk n is
        # derived from (media_id, n), so a client that chunks differently would
        # encrypt different plaintext under a nonce another client already used
        # — the one failure AES-GCM does not survive.
        raise MediaError(
            422,
            "chunk_size_mismatch",
            f"chunk {chunk_index} is {len(data)} bytes; every chunk but the last "
            f"must be exactly {full} — {CHUNK_SIZE_BYTES} of content"
            + (" plus a 16-byte GCM tag" if media.encrypted else "")
            + " (envelope §6).",
        )
    if len(data) > full:
        raise MediaError(
            422,
            "chunk_size_mismatch",
            f"chunk {chunk_index} is {len(data)} bytes, over the {full} byte "
            "chunk size.",
        )

    existing = (
        await session.execute(
            select(MediaChunk).where(
                MediaChunk.media_id == media.id, MediaChunk.chunk_index == chunk_index
            )
        )
    ).scalar_one_or_none()

    digest = chunk_hash(data)
    key = chunk_storage_key(media.id, chunk_index)

    if existing is None:
        get_media_store().put(key, data)
        session.add(
            MediaChunk(
                media_id=media.id,
                chunk_index=chunk_index,
                size_bytes=len(data),
                chunk_hash=digest,
                storage_key=key,
            )
        )
    elif existing.chunk_hash != digest:
        # Same index, different bytes. The last write wins because the client
        # is the authority on its own file — a recompression or a retry after a
        # partial read is legitimate — but the completion hash then has to match
        # what is actually stored, which is checked in `complete`.
        get_media_store().put(key, data)
        existing.chunk_hash = digest
        existing.size_bytes = len(data)

    media.status = "uploading"
    await session.flush()

    received = (
        await session.execute(
            select(func.count()).select_from(MediaChunk).where(MediaChunk.media_id == media.id)
        )
    ).scalar_one()
    upload.received_chunks = received

    return MediaChunkResponse(
        media_id=media.id,
        chunk_index=chunk_index,
        size_bytes=len(data),
        received_chunks=received,
        chunk_count=media.chunk_count,
    )


# ---------------------------------------------------------------------------
# Completion
# ---------------------------------------------------------------------------


async def complete(
    session: AsyncSession, upload_id: str, request: MediaCompleteRequest
) -> MediaCompleteResponse:
    """Seal the upload: every chunk present, and the hash is what we stored.

    The hash is computed here over the stored bytes rather than echoed from the
    request. Echoing would make the check a formality — the point is to catch a
    chunk that arrived corrupted or a client whose chunking disagrees with ours,
    and only recomputation can do that.
    """
    _upload, media = await _session_and_media(session, upload_id)

    chunks = (
        (
            await session.execute(
                select(MediaChunk)
                .where(MediaChunk.media_id == media.id)
                .order_by(MediaChunk.chunk_index)
            )
        )
        .scalars()
        .all()
    )
    present = {chunk.chunk_index for chunk in chunks}
    missing = sorted(set(range(media.chunk_count)) - present)
    if missing:
        raise MediaError(
            409,
            "chunks_missing",
            f"{len(missing)} of {media.chunk_count} chunks have not arrived: "
            f"{missing[:10]}{'...' if len(missing) > 10 else ''}. Send them and "
            "call complete again.",
        )

    store = get_media_store()
    digest = hashlib.sha256()
    total = 0
    for chunk in chunks:
        data = store.get(chunk.storage_key)
        digest.update(data)
        total += len(data)
    computed = digest.hexdigest()

    if computed != request.ciphertext_hash:
        media.status = "failed"
        raise MediaError(
            422,
            "hash_mismatch",
            f"stored bytes hash to {computed}, the client declared "
            f"{request.ciphertext_hash}. The file is not sealed; re-send the "
            "chunks that differ and call complete again.",
        )

    media.ciphertext_hash = computed
    media.size_bytes = total
    media.storage_key = f"media/{media.id}"
    media.status = "complete"
    media.uploaded_at = datetime.now(tz=UTC)
    await session.flush()

    return MediaCompleteResponse(
        media_id=media.id,
        hash=computed,
        size_bytes=total,
        chunk_count=media.chunk_count,
        status=media.status,
    )


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


async def submission_media(
    session: AsyncSession, submission_id: str
) -> SubmissionMediaResponse | None:
    """Every file belonging to one submission, and whether each has paired up.

    `resolved` is computed here rather than left to the console because working
    it out means joining the op log against the media table — and because
    "there is a photograph for this answer" and "the answer mentions a
    photograph" are exactly the two halves this design lets arrive separately.
    """
    exists = (
        await session.execute(select(Submission.id).where(Submission.id == submission_id))
    ).scalar_one_or_none()
    if exists is None:
        return None

    rows = (
        (
            await session.execute(
                select(Media)
                .where(Media.submission_id == submission_id)
                .order_by(Media.created_at, Media.id)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return SubmissionMediaResponse(
            submission_id=submission_id, media=[], keys=[], pending_count=0
        )

    media_ids = [row.id for row in rows]
    counts: dict[str, int] = {
        media_id: int(received)
        for media_id, received in (
            await session.execute(
                select(MediaChunk.media_id, func.count())
                .where(MediaChunk.media_id.in_(media_ids))
                .group_by(MediaChunk.media_id)
            )
        ).all()
    }

    # Which referencing ops have actually arrived. An op id named by a media row
    # is not proof the op is here — the client names it when it opens the
    # session, which routinely happens before the push lands.
    named_ops = {row.op_id for row in rows if row.op_id}
    arrived: set[str] = set()
    if named_ops:
        arrived = {
            op_id
            for op_id in (
                await session.execute(
                    select(SubmissionOp.id).where(SubmissionOp.id.in_(named_ops))
                )
            ).scalars()
        }

    wraps: dict[str, list[MediaWrappedKeyView]] = {}
    for wrap in (
        (
            await session.execute(
                select(MediaWrappedKey)
                .where(MediaWrappedKey.media_id.in_(media_ids))
                .order_by(MediaWrappedKey.media_id, MediaWrappedKey.project_key_id)
            )
        )
        .scalars()
        .all()
    ):
        wraps.setdefault(wrap.media_id, []).append(
            MediaWrappedKeyView(
                project_key_id=wrap.project_key_id,
                ephemeral_public=bytes(wrap.ephemeral_public).hex(),
                nonce=bytes(wrap.nonce).hex(),
                wrapped_key=bytes(wrap.wrapped_key).hex(),
            )
        )

    views = [
        MediaView(
            media_id=row.id,
            submission_id=row.submission_id,
            op_id=row.op_id,
            field_path=row.field_path,
            device_id=row.device_id,
            mime_type=row.mime_type,
            size_bytes=row.size_bytes,
            chunk_count=row.chunk_count,
            received_chunks=counts.get(row.id, 0),
            status=row.status,
            encrypted=row.encrypted,
            ciphertext_hash=row.ciphertext_hash,
            content_key_id=row.content_key_id,
            resolved=row.status == "complete" and row.op_id is not None and row.op_id in arrived,
            created_at=row.created_at,
            uploaded_at=row.uploaded_at,
        )
        for row in rows
    ]

    return SubmissionMediaResponse(
        submission_id=submission_id,
        media=views,
        keys=[
            MediaKeysView(
                media_id=row.id,
                content_key_id=row.content_key_id,
                wraps=wraps.get(row.id, []),
            )
            for row in rows
            if row.encrypted
        ],
        pending_count=sum(1 for view in views if not view.resolved),
    )


# ---------------------------------------------------------------------------
# Pairing an op with its file
# ---------------------------------------------------------------------------

# A media reference as it appears in a plaintext op value (Form IR §2.1:
# `image`/`audio`/`video`/`file`/`signature` all carry `{id, filename, hash,
# size}`). Only `id` is required to make the pairing.
_MEDIA_REFERENCE_KEYS = {"id", "filename", "hash", "size"}


def media_reference_id(value: object) -> str | None:
    """The media id in an op value, or None if this is not a media reference.

    Deliberately strict about the shape. A `set` op on a `text` field whose
    answer happens to be a JSON object with an `id` must not create a phantom
    media row that a submission then waits forever for.
    """
    if not isinstance(value, dict):
        return None
    if not _MEDIA_REFERENCE_KEYS.issuperset(value.keys()):
        return None
    media_id = value.get("id")
    if not isinstance(media_id, str) or not media_id or len(media_id) > 64:
        return None
    # `filename` alone is not enough to call this a media reference; a bare
    # {"id": ...} is not either. Requiring one of the file-shaped fields keeps
    # arbitrary objects out.
    if not ({"filename", "hash", "size"} & value.keys()):
        return None
    return media_id


async def register_pending_references(
    session: AsyncSession,
    references: list[tuple[str, str, str, str]],
) -> None:
    """Record media an accepted op referenced but the server does not hold.

    `references` is (media_id, submission_id, op_id, path). Called from the sync
    push path for plaintext ops only — in an encrypting project the reference is
    inside a ciphertext the server cannot read, and the pairing is made instead
    when the client opens the upload session and names `opId` there.

    Creates the row `pending` if the file has not been seen, and otherwise
    fills in the op that references it. Never a foreign key in either
    direction: each half is legitimately the first to arrive.
    """
    if not references:
        return

    wanted = {media_id for media_id, _, _, _ in references}
    existing = {
        row.id: row
        for row in (await session.execute(select(Media).where(Media.id.in_(wanted))))
        .scalars()
        .all()
    }

    seen: set[str] = set()
    for media_id, submission_id, op_id, path in references:
        if media_id in seen:
            continue
        seen.add(media_id)
        row = existing.get(media_id)
        if row is None:
            session.add(
                Media(
                    id=media_id,
                    submission_id=submission_id,
                    op_id=op_id,
                    field_path=path,
                    # Unknown until the file arrives and declares it. The
                    # alternative — guessing from the extension in `filename` —
                    # would put a guess where a fact belongs.
                    mime_type="application/octet-stream",
                    size_bytes=0,
                    chunk_count=0,
                    encrypted=False,
                    status="pending",
                )
            )
        elif row.submission_id == submission_id:
            row.op_id = row.op_id or op_id
            row.field_path = row.field_path or path
    await session.flush()


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


def _policy_of(project: Project) -> MediaPolicy:
    return MediaPolicy(
        image_max_dimension=project.media_image_max_dimension,
        image_quality=project.media_image_quality,
        gps_max_accuracy_m=project.media_gps_max_accuracy_m,
    )


async def device_media_policy(
    session: AsyncSession, device_id: str
) -> MediaPolicyResponse | None:
    """The capture settings this device must apply.

    Fetched every sync, like the crypto config, and cached locally: a device may
    go two weeks without a server and has to keep capturing to the project's
    settings throughout. None when the device is unknown or revoked — a device
    the server will not accept data from has no business learning a project's
    settings either.
    """
    device = (
        await session.execute(select(Device).where(Device.id == device_id))
    ).scalar_one_or_none()
    if device is None or device.revoked_at is not None:
        return None
    project = (
        await session.execute(select(Project).where(Project.id == device.project_id))
    ).scalar_one()
    return MediaPolicyResponse(
        project_id=project.id, chunk_size=CHUNK_SIZE_BYTES, policy=_policy_of(project)
    )


async def project_media_policy(
    session: AsyncSession, project_id: str
) -> MediaPolicyResponse | None:
    """A project's capture settings, for the console."""
    project = (
        await session.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project is None:
        return None
    return MediaPolicyResponse(
        project_id=project.id, chunk_size=CHUNK_SIZE_BYTES, policy=_policy_of(project)
    )


async def update_media_policy(
    session: AsyncSession, project_id: str, update: MediaPolicyUpdate
) -> MediaPolicyResponse | None:
    """Change a project's capture settings. Omitted fields are left alone.

    Takes effect on each device at its next sync. There is no way to make it
    retroactive, and it is not meant to be: a photograph already captured at
    1600px is the evidence that exists.
    """
    project = (
        await session.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project is None:
        return None
    if update.image_max_dimension is not None:
        project.media_image_max_dimension = update.image_max_dimension
    if update.image_quality is not None:
        project.media_image_quality = update.image_quality
    if update.gps_max_accuracy_m is not None:
        project.media_gps_max_accuracy_m = update.gps_max_accuracy_m
    await session.flush()
    return MediaPolicyResponse(
        project_id=project.id, chunk_size=CHUNK_SIZE_BYTES, policy=_policy_of(project)
    )
