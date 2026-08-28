"""Encryption key registry (specs/encryption-envelope-v0.1.md §4.1).

Only public keys are stored — private keys never reach the server.
Normative DDL: migrations/schema/001_initial.sql.
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import BYTEA
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class ProjectKey(Base):
    __tablename__ = "project_key"
    __table_args__ = (
        CheckConstraint(
            "key_role IN ('primary', 'backup', 'recovery')",
            name="project_key_role_check",
        ),
        CheckConstraint(
            "octet_length(public_key) = 32",
            name="project_key_length_check",
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(
        Text, ForeignKey("project.id", ondelete="CASCADE"), nullable=False
    )
    public_key: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    key_role: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
