"""Wire types for the sync API (specs/sync-protocol-v0.1.md §2, §4, §5).

The wire format is camelCase; models alias to the snake_case the rest of the
backend uses. Ops arrive as raw dicts and are validated one at a time in the
service so a malformed op rejects itself, never the batch.

Encrypted ops (spec §2.1) carry `valueCiphertext`, `contentKeyId` and `nonce`
in place of `value`. Binary travels as lowercase hex, matching the encryption
envelope's own wire shapes; nothing here can decrypt anything, and nothing here
ever should.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.crypto.envelope import NONCE_BYTES

# Sync protocol §4: batches are bounded.
MAX_BATCH_OPS = 500
# One content key per device per submission, so a batch cannot need more keys
# than it has submissions.
MAX_BATCH_KEYS = 500

# Envelope §4.3: 32-byte ephemeral public, 32-byte key + 16-byte GCM tag.
EPHEMERAL_PUBLIC_BYTES = 32
WRAPPED_KEY_BYTES = 48

# Named `type` aliases, not plain assignments: Pydantic gives a named alias its
# own entry in the generated schema, so the closed set is stated once in the
# OpenAPI document and every field refs it (see submissions/schemas.py).
type OpKind = Literal["set", "unset", "repeat_add", "repeat_delete", "finalize", "reopen"]

# Mirrors tombstone_subject_check in migrations/schema/001_initial.sql. Only
# 'submission' and 'repeat_instance' are produced today; the others exist
# because a client pulling the stream has to be able to skip a kind it does not
# handle yet rather than fail on it (spec §5).
type TombstoneSubject = Literal["submission", "repeat_instance", "case", "entity", "media"]

type RejectReason = Literal[
    "unknown_form_version",
    "not_authorized",
    "submission_closed",
    "malformed",
    # The op names a content key the server neither holds nor was sent with it.
    "unknown_content_key",
    # (contentKeyId, nonce) is already taken. Envelope §4.5 — the last line of
    # defence against a device with a broken counter.
    "nonce_reused",
]

# Kinds that address a field or repeat instance and therefore need a path.
_PATH_KINDS = {"set", "unset", "repeat_add", "repeat_delete"}


def _hex_field(name: str, value: str | None, *, expect_bytes: int | None = None) -> str | None:
    """Validate lowercase hex of an expected byte length, or raise."""
    if value is None:
        return None
    try:
        raw = bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be hex") from exc
    if expect_bytes is not None and len(raw) != expect_bytes:
        raise ValueError(f"{name} must be {expect_bytes} bytes")
    if not raw:
        raise ValueError(f"{name} must not be empty")
    return value


class SyncOp(BaseModel):
    """One operation as it travels on the wire (spec §2)."""

    model_config = ConfigDict(populate_by_name=True)

    op_id: str = Field(alias="opId", min_length=1, max_length=64)
    submission_id: str = Field(alias="submissionId", min_length=1, max_length=64)
    form_id: str = Field(alias="formId", min_length=1)
    form_version: int = Field(alias="formVersion", ge=1)
    kind: OpKind
    path: str | None = None
    value: Any = None
    # Spec §2.1. Present together or not at all; never beside `value`.
    value_ciphertext: str | None = Field(default=None, alias="valueCiphertext")
    content_key_id: str | None = Field(default=None, alias="contentKeyId", max_length=64)
    nonce: str | None = None
    device_id: str = Field(alias="deviceId", min_length=1)
    actor_id: str | None = Field(default=None, alias="actorId")
    # Monotonic logical counter per device; the basis of ordering, never reset.
    counter: int = Field(ge=0)
    # Diagnostic and audit only — never used for ordering (spec §3).
    wall_clock: datetime = Field(alias="wallClock")

    @field_validator("value_ciphertext")
    @classmethod
    def _ciphertext_is_hex(cls, value: str | None) -> str | None:
        return _hex_field("valueCiphertext", value)

    @field_validator("nonce")
    @classmethod
    def _nonce_is_hex(cls, value: str | None) -> str | None:
        return _hex_field("nonce", value, expect_bytes=NONCE_BYTES)

    @model_validator(mode="after")
    def _path_required_for_field_kinds(self) -> "SyncOp":
        if self.kind in _PATH_KINDS and not self.path:
            raise ValueError(f"kind {self.kind!r} requires a path")
        return self

    @model_validator(mode="after")
    def _encryption_fields_travel_together(self) -> "SyncOp":
        encrypted = (self.value_ciphertext, self.content_key_id, self.nonce)
        if any(f is not None for f in encrypted) and not all(f is not None for f in encrypted):
            raise ValueError(
                "valueCiphertext, contentKeyId and nonce must be present together"
            )
        if self.value_ciphertext is not None and self.value is not None:
            # Ambiguity here is a security bug, not a formatting one: the server
            # would have to guess which of the two it was meant to store.
            raise ValueError("an encrypted op must not carry a plaintext value")
        return self

    @property
    def is_encrypted(self) -> bool:
        return self.value_ciphertext is not None


class WrappedKeyIn(BaseModel):
    """One content key wrapped to one recipient project key (envelope §4.3)."""

    model_config = ConfigDict(populate_by_name=True)

    project_key_id: str = Field(alias="projectKeyId", min_length=1, max_length=64)
    ephemeral_public: str = Field(alias="ephemeralPublic")
    nonce: str
    wrapped_key: str = Field(alias="wrappedKey")

    @field_validator("ephemeral_public")
    @classmethod
    def _ephemeral_size(cls, value: str) -> str:
        return _hex_field("ephemeralPublic", value, expect_bytes=EPHEMERAL_PUBLIC_BYTES) or value

    @field_validator("nonce")
    @classmethod
    def _nonce_size(cls, value: str) -> str:
        return _hex_field("nonce", value, expect_bytes=NONCE_BYTES) or value

    @field_validator("wrapped_key")
    @classmethod
    def _wrapped_size(cls, value: str) -> str:
        return _hex_field("wrappedKey", value, expect_bytes=WRAPPED_KEY_BYTES) or value


class ContentKeyIn(BaseModel):
    """A device's content key for one submission, wrapped to every recipient.

    The key material itself is never here — only copies the server cannot open.
    """

    model_config = ConfigDict(populate_by_name=True)

    content_key_id: str = Field(alias="contentKeyId", min_length=1, max_length=64)
    submission_id: str = Field(alias="submissionId", min_length=1, max_length=64)
    device_id: str = Field(alias="deviceId", min_length=1)
    # At least one recipient: a content key wrapped to nobody is data nobody can
    # ever read again (envelope §4.3).
    wraps: list[WrappedKeyIn] = Field(min_length=1)


class PushRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    device_id: str = Field(alias="deviceId", min_length=1)
    # Raw dicts, deliberately: each op is validated individually so one
    # malformed op is rejected by itself instead of failing the request.
    ops: list[dict[str, Any]] = Field(max_length=MAX_BATCH_OPS)
    # Content keys ride the batch so a key and the first ops it encrypts commit
    # in one transaction (spec §4). Typed rather than raw: unlike an op, a
    # malformed key has no meaningful per-item rejection — the ops that depend
    # on it would all fail anyway.
    keys: list[ContentKeyIn] = Field(default_factory=list, max_length=MAX_BATCH_KEYS)


class RejectedOp(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    op_id: str | None = Field(alias="opId", serialization_alias="opId")
    reason: RejectReason


class PushResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    accepted: list[str]
    rejected: list[RejectedOp]
    server_cursor: int = Field(alias="serverCursor", serialization_alias="serverCursor")


class PulledOp(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    op_id: str = Field(serialization_alias="opId")
    submission_id: str = Field(serialization_alias="submissionId")
    form_id: str = Field(serialization_alias="formId")
    form_version: int = Field(serialization_alias="formVersion")
    kind: OpKind
    path: str | None
    value: Any
    # Relayed byte-for-byte as pushed (spec §2.1). The server has no key and
    # never had one; it is a courier here, not a reader.
    # No default. These are response fields and the server always sends
    # all three — null when the op is not encrypted. A Pydantic default
    # would make them OPTIONAL in the generated schema, and a generated
    # client would then have to handle an absent key the API never sends:
    # `string | null | undefined`, three cases for two.
    value_ciphertext: str | None = Field(serialization_alias="valueCiphertext")
    content_key_id: str | None = Field(serialization_alias="contentKeyId")
    nonce: str | None
    device_id: str = Field(serialization_alias="deviceId")
    actor_id: str | None = Field(serialization_alias="actorId")
    counter: int
    wall_clock: datetime = Field(serialization_alias="wallClock")
    server_seq: int = Field(serialization_alias="serverSeq")


class PulledTombstone(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    subject_type: TombstoneSubject = Field(serialization_alias="subjectType")
    subject_id: str = Field(serialization_alias="subjectId")
    submission_id: str | None = Field(serialization_alias="submissionId")
    path: str | None
    device_id: str | None = Field(serialization_alias="deviceId")
    counter: int | None
    created_at: datetime = Field(serialization_alias="createdAt")
    expires_at: datetime | None = Field(serialization_alias="expiresAt")
    server_seq: int = Field(serialization_alias="serverSeq")


class PullResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    ops: list[PulledOp]
    tombstones: list[PulledTombstone]
    next_cursor: int = Field(serialization_alias="nextCursor")
    has_more: bool = Field(serialization_alias="hasMore")
