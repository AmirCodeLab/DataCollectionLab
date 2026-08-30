"""Projects, environments, teams, membership and devices.

Normative DDL: migrations/schema/001_initial.sql.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
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


class Project(Base):
    __tablename__ = "project"
    __table_args__ = (
        CheckConstraint(
            "security_mode IN ('standard', 'field_level', 'project_e2e')",
            name="project_security_mode_check",
        ),
        CheckConstraint(
            "media_image_max_dimension BETWEEN 320 AND 8192",
            name="project_media_image_max_dimension_check",
        ),
        CheckConstraint(
            "media_image_quality BETWEEN 1 AND 100",
            name="project_media_image_quality_check",
        ),
        CheckConstraint(
            "media_gps_max_accuracy_m BETWEEN 1 AND 10000",
            name="project_media_gps_max_accuracy_check",
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    # Fixed at creation. Changing it would require re-encrypting or decrypting
    # historical data, which defeats the point of having chosen it.
    security_mode: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'standard'")
    )
    # Capture policy, fetched by devices and cached for however long they are
    # next offline. Compression is a project decision because it trades
    # evidentiary quality against bandwidth and only the study knows which side
    # it is on; the GPS threshold is a project decision because a phone indoors
    # will report a 2 km "fix" with the same authority as a good one.
    media_image_max_dimension: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1600")
    )
    media_image_quality: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("80")
    )
    media_gps_max_accuracy_m: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("50")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Environment(Base):
    __tablename__ = "environment"
    __table_args__ = (
        UniqueConstraint("project_id", "kind"),
        CheckConstraint(
            "kind IN ('development', 'staging', 'production')",
            name="environment_kind_check",
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(
        Text, ForeignKey("project.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Team(Base):
    __tablename__ = "team"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(
        Text, ForeignKey("project.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    parent_team_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("team.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ProjectMember(Base):
    __tablename__ = "project_member"
    __table_args__ = (
        CheckConstraint(
            "project_role IN ('manager', 'supervisor', 'enumerator', 'analyst', 'viewer')",
            name="project_member_role_check",
        ),
    )

    project_id: Mapped[str] = mapped_column(
        Text, ForeignKey("project.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_role: Mapped[str] = mapped_column(Text, nullable=False)
    team_id: Mapped[str | None] = mapped_column(Text, ForeignKey("team.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Device(Base):
    __tablename__ = "device"
    __table_args__ = (
        CheckConstraint(
            "platform IN ('android', 'ios', 'desktop', 'web')",
            name="device_platform_check",
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(
        Text, ForeignKey("project.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    os_version: Mapped[str | None] = mapped_column(Text)
    app_version: Mapped[str | None] = mapped_column(Text)
    # Highest logical counter the server has accepted from this device.
    # Ordering depends on it, so it is authoritative state, not a statistic.
    last_counter: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
