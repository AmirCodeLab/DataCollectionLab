"""Submissions and the operation log (specs/sync-protocol-v0.1.md).

submission_op is append-only: no UPDATE, no DELETE, ever. It is simultaneously
the sync mechanism and the correction audit trail. submission_state and
submission_snapshot are derived and rebuildable from the log.

Normative DDL: migrations/schema/001_initial.sql.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import BYTEA, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class Submission(Base):
    __tablename__ = "submission"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'finalized', 'in_review', 'approved', "
            "'rejected', 'correction_required')",
            name="submission_status_check",
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(
        Text, ForeignKey("project.id", ondelete="CASCADE"), nullable=False
    )
    environment_id: Mapped[str] = mapped_column(
        Text, ForeignKey("environment.id", ondelete="RESTRICT"), nullable=False
    )
    form_version_id: Mapped[str] = mapped_column(
        Text, ForeignKey("form_version.id", ondelete="RESTRICT"), nullable=False
    )
    case_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("case_record.id", ondelete="SET NULL")
    )
    visit_id: Mapped[str | None] = mapped_column(Text, ForeignKey("visit.id", ondelete="SET NULL"))
    origin_device_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("device.id", ondelete="SET NULL")
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class SubmissionContentKey(Base):
    """One content key per device per submission (encryption envelope §4.2)."""

    __tablename__ = "submission_content_key"
    __table_args__ = (UniqueConstraint("submission_id", "device_id"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    submission_id: Mapped[str] = mapped_column(
        Text, ForeignKey("submission.id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[str] = mapped_column(
        Text, ForeignKey("device.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class SubmissionWrappedKey(Base):
    """A content key wrapped to one recipient project key (envelope §4.3)."""

    __tablename__ = "submission_wrapped_key"
    __table_args__ = (
        CheckConstraint(
            "octet_length(ephemeral_public) = 32"
            " AND octet_length(nonce) = 12"
            " AND octet_length(wrapped_key) = 48",
            name="submission_wrapped_key_sizes_check",
        ),
    )

    content_key_id: Mapped[str] = mapped_column(
        Text, ForeignKey("submission_content_key.id", ondelete="CASCADE"), primary_key=True
    )
    project_key_id: Mapped[str] = mapped_column(
        Text, ForeignKey("project_key.id", ondelete="RESTRICT"), primary_key=True
    )
    submission_id: Mapped[str] = mapped_column(
        Text, ForeignKey("submission.id", ondelete="CASCADE"), nullable=False
    )
    ephemeral_public: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    nonce: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    wrapped_key: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class SubmissionOp(Base):
    """Append-only operation log. Never UPDATE or DELETE a row."""

    __tablename__ = "submission_op"
    __table_args__ = (
        CheckConstraint(
            "op_kind IN ('set', 'unset', 'repeat_add', 'repeat_delete', 'finalize', 'reopen')",
            name="submission_op_kind_check",
        ),
        # Encrypted ops carry key and nonce; plaintext ops carry neither.
        CheckConstraint(
            "(value_ciphertext IS NULL AND content_key_id IS NULL AND nonce IS NULL)"
            " OR (value_ciphertext IS NOT NULL AND content_key_id IS NOT NULL"
            " AND nonce IS NOT NULL AND value IS NULL)",
            name="submission_op_encryption_check",
        ),
        # AES-GCM fails catastrophically on nonce reuse; this index removes the
        # failure class even if a client has a broken counter.
        UniqueConstraint("content_key_id", "nonce"),
        # Ordering is by (counter, device_id), never wall clock.
        UniqueConstraint("device_id", "counter"),
        UniqueConstraint("server_seq"),
        Index("submission_op_replay_idx", "submission_id", "counter", "device_id"),
        Index("submission_op_received_idx", "received_at"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    submission_id: Mapped[str] = mapped_column(
        Text, ForeignKey("submission.id", ondelete="CASCADE"), nullable=False
    )
    op_kind: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str | None] = mapped_column(Text)
    # Exactly one of value / value_ciphertext is populated. A project in
    # field_level mode uses both across different ops in the same submission.
    value: Mapped[Any | None] = mapped_column(JSONB)
    value_ciphertext: Mapped[bytes | None] = mapped_column(BYTEA)
    content_key_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("submission_content_key.id", ondelete="RESTRICT")
    )
    nonce: Mapped[bytes | None] = mapped_column(BYTEA)
    device_id: Mapped[str] = mapped_column(
        Text, ForeignKey("device.id", ondelete="RESTRICT"), nullable=False
    )
    actor_id: Mapped[str | None] = mapped_column(Text)
    counter: Mapped[int] = mapped_column(BigInteger, nullable=False)
    wall_clock: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    # Server arrival order, the basis of the pull cursor. Conflict resolution
    # orders by (counter, device_id), never by this and never by wall_clock.
    server_seq: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("nextval('sync_stream_seq')")
    )


class SubmissionState(Base):
    """Materialised current state, folded from the op log. Safe to rebuild."""

    __tablename__ = "submission_state"

    submission_id: Mapped[str] = mapped_column(
        Text, ForeignKey("submission.id", ondelete="CASCADE"), primary_key=True
    )
    data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    op_high_water: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class SubmissionSnapshot(Base):
    """Periodic fold of the op log, to bound replay for fresh devices."""

    __tablename__ = "submission_snapshot"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    submission_id: Mapped[str] = mapped_column(
        Text, ForeignKey("submission.id", ondelete="CASCADE"), nullable=False
    )
    op_count: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    data_ciphertext: Mapped[bytes | None] = mapped_column(BYTEA)
    content_key_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("submission_content_key.id", ondelete="RESTRICT")
    )
    nonce: Mapped[bytes | None] = mapped_column(BYTEA)
    taken_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
