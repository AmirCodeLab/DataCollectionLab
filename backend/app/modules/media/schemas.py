"""Wire types for media upload (sync protocol §9, encryption envelope §6).

The wire format is camelCase; models alias to the backend's snake_case, as
everywhere else. Binary travels as lowercase hex, matching the envelope's other
wire shapes.

One shape here is not a Pydantic model and cannot be: the chunk body itself.
`PUT .../chunks/{n}` takes 4 MiB of raw bytes as `application/octet-stream`.
Base64 inside a JSON envelope would be the uniform choice and would cost a
third more bytes on every chunk, which on the connections this exists for is
the difference between an upload that completes and one that does not.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.crypto.envelope import MEDIA_CHUNK_BYTES, NONCE_BYTES

# Envelope §4.3: 32-byte ephemeral public, 32-byte key + 16-byte GCM tag.
EPHEMERAL_PUBLIC_BYTES = 32
WRAPPED_KEY_BYTES = 48

# Envelope §6: "Chunk size is fixed at 4 MiB." Fixed, not negotiated — the
# nonce for chunk n is derived from (media_id, n), so two clients that disagree
# about where chunk boundaries fall would derive the same nonce for different
# plaintext, which is the one failure AES-GCM does not survive.
CHUNK_SIZE_BYTES = MEDIA_CHUNK_BYTES

# AES-GCM appends a 16-byte authentication tag, so an encrypted 4 MiB chunk is
# 4 MiB + 16 bytes ON THE WIRE. The chunk size in the spec is the plaintext
# size; the server only ever sees the ciphertext, and has to check against the
# size that actually arrives. Getting this wrong makes every full chunk of
# every encrypted file fail, which is exactly how it was found.
GCM_TAG_BYTES = 16


def wire_chunk_size(*, encrypted: bool) -> int:
    """How big a full chunk is when it reaches the server."""
    return CHUNK_SIZE_BYTES + (GCM_TAG_BYTES if encrypted else 0)

# A ceiling on one file, so a bug or a hostile client cannot fill the disk one
# 4 MiB chunk at a time. 512 MiB is far past any photograph and still short of
# the video work that comes later.
MAX_MEDIA_BYTES = 512 * 1024 * 1024
MAX_CHUNKS = (MAX_MEDIA_BYTES + CHUNK_SIZE_BYTES - 1) // CHUNK_SIZE_BYTES

SHA256_HEX_LENGTH = 64

# Named `type` aliases, not plain assignments: Pydantic gives a named alias its
# own entry in the generated schema, so the closed set is stated once in the
# OpenAPI document and every field refs it (see submissions/schemas.py).

# Mirrors media_status_check in migrations/schema/001_initial.sql.
#
# `pending` is the state this whole design exists to make representable: the op
# referencing the file has been accepted and the file has not arrived. It is not
# an error, it is the normal condition of a device that finished a questionnaire
# before it finished uploading a photograph.
type MediaStatus = Literal["pending", "uploading", "complete", "failed"]

type MediaUploadFailure = Literal[
    "submission_not_found",
    "device_not_authorized",
    # The media id is already complete under a different submission or device.
    "media_conflict",
    "session_not_found",
    "session_expired",
    # The chunk index is outside the declared chunk count.
    "chunk_out_of_range",
    # A chunk that is not the last one must be exactly CHUNK_SIZE_BYTES.
    "chunk_size_mismatch",
    # `complete` was called with chunks still missing.
    "chunks_missing",
    # The hash over the stored ciphertext is not the one the client declared.
    "hash_mismatch",
    # A media key wrapped to a key this project does not have active.
    "unknown_recipient",
    # An encrypting project, and the file arrived with no wrapped keys: nobody
    # could ever open it again.
    "unwrapped_media_key",
]


class MediaWrappedKeyIn(BaseModel):
    """The media key wrapped to one recipient project key (envelope §6, §4.4)."""

    model_config = ConfigDict(populate_by_name=True)

    project_key_id: str = Field(alias="projectKeyId", min_length=1, max_length=64)
    ephemeral_public: str = Field(alias="ephemeralPublic")
    nonce: str
    wrapped_key: str = Field(alias="wrappedKey")

    @field_validator("ephemeral_public")
    @classmethod
    def _ephemeral_size(cls, value: str) -> str:
        return _hex(value, "ephemeralPublic", EPHEMERAL_PUBLIC_BYTES)

    @field_validator("nonce")
    @classmethod
    def _nonce_size(cls, value: str) -> str:
        return _hex(value, "nonce", NONCE_BYTES)

    @field_validator("wrapped_key")
    @classmethod
    def _wrapped_size(cls, value: str) -> str:
        return _hex(value, "wrappedKey", WRAPPED_KEY_BYTES)


def _hex(value: str, name: str, expect_bytes: int) -> str:
    try:
        raw = bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be hex") from exc
    if len(raw) != expect_bytes:
        raise ValueError(f"{name} must be {expect_bytes} bytes")
    return value


class MediaUploadSessionRequest(BaseModel):
    """Open — or reopen — an upload for one file.

    Idempotent on `mediaId`. Calling it again for a file already part-uploaded
    is exactly how resumption starts: the response says which chunks the server
    already holds, and the client sends the rest. That is why there is no
    separate "session status" endpoint — a resuming client has to make this call
    anyway, and a second way to ask the same question is a second thing that can
    disagree.
    """

    model_config = ConfigDict(populate_by_name=True)

    # Client-generated ULID. Devices create media offline and must be able to
    # name a file in an operation before the server has ever heard of it.
    media_id: str = Field(alias="mediaId", min_length=1, max_length=64)
    submission_id: str = Field(alias="submissionId", min_length=1, max_length=64)
    device_id: str = Field(alias="deviceId", min_length=1, max_length=64)
    # The op that references this file, when the client knows it. Optional
    # because the reference may be inside an encrypted op value the server
    # cannot read (envelope §5) — then this is the only way the pair is ever
    # made. Never a foreign key: the op may not have arrived yet.
    op_id: str | None = Field(default=None, alias="opId", max_length=64)
    field_path: str | None = Field(default=None, alias="fieldPath", max_length=500)
    mime_type: str = Field(alias="mimeType", min_length=1, max_length=200)
    size_bytes: int = Field(alias="sizeBytes", ge=1, le=MAX_MEDIA_BYTES)
    chunk_count: int = Field(alias="chunkCount", ge=1, le=MAX_CHUNKS)
    encrypted: bool
    # The media key's id (envelope §6). Present exactly when `encrypted`.
    content_key_id: str | None = Field(default=None, alias="contentKeyId", max_length=64)
    # Wrapped to every active project key. Required when `encrypted`: a media
    # key wrapped to nobody is a file nobody can ever open, including the people
    # who collected it.
    wraps: list[MediaWrappedKeyIn] = Field(default_factory=list, max_length=32)


class MediaUploadSessionResponse(BaseModel):
    """Where to send the chunks, and which ones are already here."""

    model_config = ConfigDict(populate_by_name=True)

    upload_id: str = Field(serialization_alias="uploadId")
    media_id: str = Field(serialization_alias="mediaId")
    chunk_size: int = Field(serialization_alias="chunkSize")
    chunk_count: int = Field(serialization_alias="chunkCount")
    # Ascending. The client skips exactly these and sends the rest — the whole
    # of resumption, in one field.
    received_chunks: list[int] = Field(serialization_alias="receivedChunks")
    status: MediaStatus
    expires_at: datetime = Field(serialization_alias="expiresAt")


class MediaChunkResponse(BaseModel):
    """One chunk stored. Re-sending a chunk already held is a success, not an
    error: a client that lost the response has no way to tell the difference,
    and making it retry-safe is cheaper than making it careful."""

    model_config = ConfigDict(populate_by_name=True)

    media_id: str = Field(serialization_alias="mediaId")
    chunk_index: int = Field(serialization_alias="chunkIndex")
    size_bytes: int = Field(serialization_alias="sizeBytes")
    received_chunks: int = Field(serialization_alias="receivedChunks")
    chunk_count: int = Field(serialization_alias="chunkCount")


class MediaCompleteRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    # SHA-256 over the concatenated stored bytes — CIPHERTEXT for an encrypted
    # file, never plaintext. Hashing plaintext would let the server confirm that
    # two submissions contain the same photograph, which is precisely the
    # inference end-to-end encryption exists to prevent (envelope §6).
    ciphertext_hash: str = Field(
        alias="ciphertextHash", min_length=SHA256_HEX_LENGTH, max_length=SHA256_HEX_LENGTH
    )

    @field_validator("ciphertext_hash")
    @classmethod
    def _is_hex(cls, value: str) -> str:
        return _hex(value, "ciphertextHash", SHA256_HEX_LENGTH // 2)


class MediaCompleteResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    media_id: str = Field(serialization_alias="mediaId")
    # The server's own computation over what it stored, not an echo of the
    # request. Echoing it would make the check a formality.
    hash: str
    size_bytes: int = Field(serialization_alias="sizeBytes")
    chunk_count: int = Field(serialization_alias="chunkCount")
    status: MediaStatus


class MediaUploadError(BaseModel):
    """A refusal a client can branch on, not just a status code."""

    reason: MediaUploadFailure
    message: str


class MediaUploadErrorResponse(BaseModel):
    """FastAPI sends `{"detail": ...}`; this is that envelope, not the payload
    inside it."""

    detail: MediaUploadError


class MediaView(BaseModel):
    """One file as the console sees it."""

    model_config = ConfigDict(populate_by_name=True)

    media_id: str = Field(serialization_alias="mediaId")
    submission_id: str = Field(serialization_alias="submissionId")
    # Null while the referencing op has not arrived, or while it arrived
    # encrypted and the client has not named it. Never a foreign key.
    op_id: str | None = Field(serialization_alias="opId")
    field_path: str | None = Field(serialization_alias="fieldPath")
    device_id: str | None = Field(serialization_alias="deviceId")
    mime_type: str = Field(serialization_alias="mimeType")
    size_bytes: int = Field(serialization_alias="sizeBytes")
    chunk_count: int = Field(serialization_alias="chunkCount")
    received_chunks: int = Field(serialization_alias="receivedChunks")
    status: MediaStatus
    encrypted: bool
    ciphertext_hash: str | None = Field(serialization_alias="ciphertextHash")
    content_key_id: str | None = Field(serialization_alias="contentKeyId")
    # True once BOTH halves are here: the file is complete and an op references
    # it. This is what "the pair resolved" means, and the reason it is computed
    # here rather than left to the console is that the console would have to
    # join the op log against the media table to work it out.
    resolved: bool
    created_at: datetime = Field(serialization_alias="createdAt")
    uploaded_at: datetime | None = Field(serialization_alias="uploadedAt")


class MediaWrappedKeyView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    project_key_id: str = Field(serialization_alias="projectKeyId")
    ephemeral_public: str = Field(serialization_alias="ephemeralPublic")
    nonce: str
    wrapped_key: str = Field(serialization_alias="wrappedKey")


class MediaKeysView(BaseModel):
    """The wrapped media keys for one file (envelope §6, §7)."""

    model_config = ConfigDict(populate_by_name=True)

    media_id: str = Field(serialization_alias="mediaId")
    content_key_id: str | None = Field(serialization_alias="contentKeyId")
    wraps: list[MediaWrappedKeyView]


class SubmissionMediaResponse(BaseModel):
    """Every file belonging to one submission, resolved or not."""

    model_config = ConfigDict(populate_by_name=True)

    submission_id: str = Field(serialization_alias="submissionId")
    media: list[MediaView]
    keys: list[MediaKeysView]
    # How many are still waiting for their file. The console shows this as
    # "3 photographs still uploading" rather than silently rendering a
    # submission that looks complete and is not.
    pending_count: int = Field(serialization_alias="pendingCount")


class MediaPolicy(BaseModel):
    """Per-project capture settings (see project.media_* in 002_media.sql)."""

    model_config = ConfigDict(populate_by_name=True)

    # Longest edge, in pixels, after compression. The client scales down to fit.
    image_max_dimension: int = Field(
        serialization_alias="imageMaxDimension", ge=320, le=8192
    )
    # JPEG quality, 1–100.
    image_quality: int = Field(serialization_alias="imageQuality", ge=1, le=100)
    # Metres. A fix reported as worse than this is refused, not stored quietly:
    # a point that wrong is worse than a missing one, because nothing
    # downstream can tell it from a good one.
    gps_max_accuracy_m: int = Field(serialization_alias="gpsMaxAccuracyM", ge=1, le=10000)


class MediaPolicyResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    project_id: str = Field(serialization_alias="projectId")
    chunk_size: int = Field(serialization_alias="chunkSize")
    policy: MediaPolicy


class MediaPolicyUpdate(BaseModel):
    """Change one or more settings. Omitted fields are left alone."""

    model_config = ConfigDict(populate_by_name=True)

    image_max_dimension: int | None = Field(
        default=None, alias="imageMaxDimension", ge=320, le=8192
    )
    image_quality: int | None = Field(default=None, alias="imageQuality", ge=1, le=100)
    gps_max_accuracy_m: int | None = Field(
        default=None, alias="gpsMaxAccuracyM", ge=1, le=10000
    )
