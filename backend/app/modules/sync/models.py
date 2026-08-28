"""Sync bookkeeping: tombstones and per-device cursors.

Deletion is an operation, not an absence — tombstones are carried in pull
responses so every replica converges (specs/erd-v0.1.md §7).
Normative DDL: migrations/schema/001_initial.sql.
"""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class Tombstone(Base):
    __tablename__ = "tombstone"
    __table_args__ = (
        CheckConstraint(
            "subject_type IN ('submission', 'repeat_instance', 'case', 'entity', 'media')",
            name="tombstone_subject_check",
        ),
        Index("tombstone_pull_idx", "project_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(
        Text, ForeignKey("project.id", ondelete="CASCADE"), nullable=False
    )
    subject_type: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[str] = mapped_column(Text, nullable=False)
    submission_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("submission.id", ondelete="CASCADE")
    )
    path: Mapped[str | None] = mapped_column(Text)
    device_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("device.id", ondelete="SET NULL")
    )
    counter: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SyncCursor(Base):
    __tablename__ = "sync_cursor"

    device_id: Mapped[str] = mapped_column(
        Text, ForeignKey("device.id", ondelete="CASCADE"), primary_key=True
    )
    scope: Mapped[str] = mapped_column(Text, primary_key=True)
    cursor_value: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
