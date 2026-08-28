"""Wire types for the sync API (specs/sync-protocol-v0.1.md §2, §4, §5).

The wire format is camelCase; models alias to the snake_case the rest of the
backend uses. Ops arrive as raw dicts and are validated one at a time in the
service so a malformed op rejects itself, never the batch.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Sync protocol §4: batches are bounded.
MAX_BATCH_OPS = 500

OpKind = Literal["set", "unset", "repeat_add", "repeat_delete", "finalize", "reopen"]

RejectReason = Literal["unknown_form_version", "not_authorized", "submission_closed", "malformed"]

# Kinds that address a field or repeat instance and therefore need a path.
_PATH_KINDS = {"set", "unset", "repeat_add", "repeat_delete"}


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
    device_id: str = Field(alias="deviceId", min_length=1)
    actor_id: str | None = Field(default=None, alias="actorId")
    # Monotonic logical counter per device; the basis of ordering, never reset.
    counter: int = Field(ge=0)
    # Diagnostic and audit only — never used for ordering (spec §3).
    wall_clock: datetime = Field(alias="wallClock")

    @model_validator(mode="after")
    def _path_required_for_field_kinds(self) -> "SyncOp":
        if self.kind in _PATH_KINDS and not self.path:
            raise ValueError(f"kind {self.kind!r} requires a path")
        return self


class PushRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    device_id: str = Field(alias="deviceId", min_length=1)
    # Raw dicts, deliberately: each op is validated individually so one
    # malformed op is rejected by itself instead of failing the request.
    ops: list[dict[str, Any]] = Field(max_length=MAX_BATCH_OPS)


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
    kind: str
    path: str | None
    value: Any
    device_id: str = Field(serialization_alias="deviceId")
    actor_id: str | None = Field(serialization_alias="actorId")
    counter: int
    wall_clock: datetime = Field(serialization_alias="wallClock")
    server_seq: int = Field(serialization_alias="serverSeq")


class PulledTombstone(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    subject_type: str = Field(serialization_alias="subjectType")
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
