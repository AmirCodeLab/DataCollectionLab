"""Cases, assignments and visits.

A case is a unit of assigned work; a visit is one collection event against it.
Keeping them separate is what makes longitudinal studies work
(specs/erd-v0.1.md §5). Normative DDL: migrations/schema/001_initial.sql.
"""

from datetime import datetime
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class CaseRecord(Base):
    __tablename__ = "case_record"
    __table_args__ = (UniqueConstraint("project_id", "case_key"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(
        Text, ForeignKey("project.id", ondelete="CASCADE"), nullable=False
    )
    entity_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("entity.id", ondelete="SET NULL")
    )
    case_key: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'open'"))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    location: Mapped[Any | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False)
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Assignment(Base):
    __tablename__ = "assignment"
    __table_args__ = (
        CheckConstraint(
            "user_id IS NOT NULL OR team_id IS NOT NULL",
            name="assignment_target_check",
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    case_id: Mapped[str] = mapped_column(
        Text, ForeignKey("case_record.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str | None] = mapped_column(Text)
    team_id: Mapped[str | None] = mapped_column(Text, ForeignKey("team.id", ondelete="SET NULL"))
    assigned_by: Mapped[str | None] = mapped_column(Text)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Visit(Base):
    """One collection event against a case."""

    __tablename__ = "visit"
    __table_args__ = (UniqueConstraint("case_id", "sequence"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    case_id: Mapped[str] = mapped_column(
        Text, ForeignKey("case_record.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    form_version_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("form_version.id", ondelete="RESTRICT")
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
