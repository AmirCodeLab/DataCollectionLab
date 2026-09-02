"""Forms, immutable published versions, and per-environment deployments.

form_version rows are never updated once published — editing produces a new
row (specs/erd-v0.1.md §4). Normative DDL: migrations/schema/001_initial.sql.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class Form(Base):
    __tablename__ = "form"
    __table_args__ = (UniqueConstraint("project_id", "form_key"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(
        Text, ForeignKey("project.id", ondelete="CASCADE"), nullable=False
    )
    form_key: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FormVersion(Base):
    """Immutable once published. Editing produces a new row, never an UPDATE."""

    __tablename__ = "form_version"
    __table_args__ = (UniqueConstraint("form_id", "version"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    form_id: Mapped[str] = mapped_column(
        Text, ForeignKey("form.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    ir: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    ir_checksum: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[str | None] = mapped_column(Text)

    # How this version got here, when it came from a spreadsheet. All NULL for
    # a version published from hand-written IR, which is the honest record of
    # not having been imported — see migrations/schema/003_form_import.sql, and
    # the CHECK there that stops a half-recorded import looking like a whole one.
    import_source_name: Mapped[str | None] = mapped_column(Text)
    import_source_sha256: Mapped[str | None] = mapped_column(Text)
    import_report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    import_importer_version: Mapped[str | None] = mapped_column(Text)
    imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class FormDeployment(Base):
    __tablename__ = "form_deployment"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    environment_id: Mapped[str] = mapped_column(
        Text, ForeignKey("environment.id", ondelete="CASCADE"), nullable=False
    )
    form_version_id: Mapped[str] = mapped_column(
        Text, ForeignKey("form_version.id", ondelete="RESTRICT"), nullable=False
    )
    deployed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    deployed_by: Mapped[str | None] = mapped_column(Text)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
