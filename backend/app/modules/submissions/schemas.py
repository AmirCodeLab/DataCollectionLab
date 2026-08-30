"""Wire types for the submissions read API (console views).

Read-only projections of the op log and its fold. The wire format is camelCase;
models alias to the backend's snake_case, as everywhere else.

An encrypted op reports `encrypted: true`, a null `value`, and the ciphertext
it actually holds — relayed byte for byte, exactly as /sync/pull relays it. The
server is a courier for those bytes, never a reader
(specs/encryption-envelope-v0.1.md §3): they are useless without a private key
it has never held. Handing them back is what makes decryption possible at all
(§7), and a submission whose ciphertext nobody can fetch is not encrypted data,
it is destroyed data.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.sync.schemas import OpKind

# Mirrors submission_status_check in migrations/schema/001_initial.sql.
#
# A PEP 695 `type` alias rather than a plain assignment, and that is a contract
# decision rather than a style one: Pydantic gives a named alias its own entry
# in the generated schema, so the OpenAPI document says `SubmissionStatus` once
# and every field refs it. A plain `SubmissionStatus = Literal[...]` inlines the
# same six strings at every use site, and a generated client then has six
# anonymous unions where the API has one closed set.
type SubmissionStatus = Literal[
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
    # The op vocabulary is the sync protocol's, not this module's — one closed
    # set, defined where ops are defined (spec §2).
    kind: OpKind
    path: str | None
    value: Any
    encrypted: bool
    # Present exactly when `encrypted`. Lowercase hex, as everywhere binary
    # travels in this API. A key holder needs all three — the ciphertext, the
    # nonce it was sealed under, and which content key opens it — plus the op
    # id, path and form version already on this row, which are the AAD (§5).
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


class WrappedKeyView(BaseModel):
    """One content key wrapped to one recipient project key (envelope §4.3)."""

    model_config = ConfigDict(populate_by_name=True)

    project_key_id: str = Field(serialization_alias="projectKeyId")
    ephemeral_public: str = Field(serialization_alias="ephemeralPublic")
    nonce: str
    wrapped_key: str = Field(serialization_alias="wrappedKey")


class ContentKeyView(BaseModel):
    """A submission's content key, in the only form the server has it: wrapped."""

    model_config = ConfigDict(populate_by_name=True)

    content_key_id: str = Field(serialization_alias="contentKeyId")
    device_id: str = Field(serialization_alias="deviceId")
    wraps: list[WrappedKeyView]


class SubmissionKeysResponse(BaseModel):
    """Every wrapped key needed to decrypt one submission (envelope §7).

    A submission built by several devices has one content key per device, all
    wrapped to the same recipients, so a single private key opens every one.
    Handing these out costs nothing: the server has never held the private key
    that opens them, and neither has whoever is asking, unless they own it.
    """

    model_config = ConfigDict(populate_by_name=True)

    submission_id: str = Field(serialization_alias="submissionId")
    content_keys: list[ContentKeyView] = Field(serialization_alias="contentKeys")


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
