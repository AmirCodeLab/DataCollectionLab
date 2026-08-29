"""Wire types for the submissions read API (console views).

Read-only projections of the op log and its fold. The wire format is camelCase;
models alias to the backend's snake_case, as everywhere else.

Ciphertext never leaves the server through here: an encrypted op reports
`encrypted: true` and a null value. Decryption is the client's job — the
console is not a key holder (specs/encryption-envelope-v0.1.md §3).
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Mirrors submission_status_check in migrations/schema/001_initial.sql.
SubmissionStatus = Literal[
    "draft", "finalized", "in_review", "approved", "rejected", "correction_required"
]

DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 200

# A correction loop can grow a submission's log without bound, and the console
# renders every row it is given. Past this, the detail view says so rather than
# silently showing a prefix.
MAX_DETAIL_OPS = 1000


class SubmissionSummary(BaseModel):
    """One row of the submission list."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    form_id: str = Field(serialization_alias="formId")
    form_title: str = Field(serialization_alias="formTitle")
    form_version: int = Field(serialization_alias="formVersion")
    status: SubmissionStatus
    origin_device_id: str | None = Field(serialization_alias="originDeviceId")
    op_count: int = Field(serialization_alias="opCount")
    received_at: datetime = Field(serialization_alias="receivedAt")


class SubmissionListResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    submissions: list[SubmissionSummary]
    # Total matching the filters, not the page — the console shows "n of N".
    total: int
    limit: int
    offset: int


class SubmissionOpView(BaseModel):
    """One row of the raw op log."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    kind: str
    path: str | None
    value: Any
    encrypted: bool
    device_id: str = Field(serialization_alias="deviceId")
    actor_id: str | None = Field(serialization_alias="actorId")
    counter: int
    # Diagnostic only. Ordering is (counter, deviceId) — never this (spec §3).
    wall_clock: datetime = Field(serialization_alias="wallClock")
    received_at: datetime = Field(serialization_alias="receivedAt")
    server_seq: int = Field(serialization_alias="serverSeq")


class SubmissionStateView(BaseModel):
    """The materialised fold: current value per field path."""

    model_config = ConfigDict(populate_by_name=True)

    data: dict[str, Any]
    op_high_water: int = Field(serialization_alias="opHighWater")
    computed_at: datetime = Field(serialization_alias="computedAt")


class SubmissionDetail(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    project_id: str = Field(serialization_alias="projectId")
    form_id: str = Field(serialization_alias="formId")
    form_title: str = Field(serialization_alias="formTitle")
    form_version: int = Field(serialization_alias="formVersion")
    status: SubmissionStatus
    origin_device_id: str | None = Field(serialization_alias="originDeviceId")
    created_by: str | None = Field(serialization_alias="createdBy")
    started_at: datetime | None = Field(serialization_alias="startedAt")
    finalized_at: datetime | None = Field(serialization_alias="finalizedAt")
    received_at: datetime = Field(serialization_alias="receivedAt")
    op_count: int = Field(serialization_alias="opCount")
    # Absent only for a submission whose fold has not run — never expected in
    # practice, since push folds in the same transaction.
    state: SubmissionStateView | None
    # In (counter, deviceId) order: replay order, not arrival order.
    ops: list[SubmissionOpView]
    # True when op_count exceeds MAX_DETAIL_OPS and `ops` is a prefix.
    ops_truncated: bool = Field(serialization_alias="opsTruncated")
