"""Platform-level tables: organisations, user accounts, membership.

These are the only tables that are global rather than schema-per-tenant
(specs/erd-v0.1.md §1). Normative DDL: migrations/schema/001_initial.sql.
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class PlatformOrganization(Base):
    __tablename__ = "platform_organization"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    schema_name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlatformUser(Base):
    __tablename__ = "platform_user"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'invited', 'suspended', 'deactivated')",
            name="platform_user_status_check",
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    mfa_secret: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class PlatformOrgMembership(Base):
    __tablename__ = "platform_org_membership"
    __table_args__ = (
        CheckConstraint(
            "org_role IN ('owner', 'admin', 'member')",
            name="platform_org_membership_role_check",
        ),
    )

    organization_id: Mapped[str] = mapped_column(
        Text, ForeignKey("platform_organization.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("platform_user.id", ondelete="CASCADE"), primary_key=True
    )
    org_role: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
