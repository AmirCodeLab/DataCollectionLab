"""Platform-level tables: organisations, people, memberships, roles, sessions.

Global by prefix, tenant-scoped by policy: a person and a role belong to one
organisation and carry it (specs/erd-v0.1.md §1). Normative DDL:
migrations/schema/001_initial.sql and 008_identity.sql.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class PlatformOrganization(Base):
    __tablename__ = "platform_organization"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlatformUser(Base):
    """A person: exists once, belongs to one organisation, is never deleted."""

    __tablename__ = "platform_user"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'invited', 'suspended', 'deactivated')",
            name="platform_user_status_check",
        ),
        UniqueConstraint("organization_id", "id", name="platform_user_org_id_key"),
        UniqueConstraint("username", name="platform_user_username_key"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    email: Mapped[str | None] = mapped_column(Text, unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    mfa_secret: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    organization_id: Mapped[str] = mapped_column(
        Text, ForeignKey("platform_organization.id", ondelete="RESTRICT"), nullable=False
    )
    display_name: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    #: The login identifier.
    username: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(
        Text, ForeignKey("platform_user.id", ondelete="RESTRICT")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class PlatformOrgMembership(Base):
    """Member of this organisation (pilot scope §3.2–§3.4): who created it,
    whether it is approved yet, and whether it outlives the project."""

    __tablename__ = "platform_org_membership"
    __table_args__ = (
        CheckConstraint(
            "org_role IN ('owner', 'admin', 'member')",
            name="platform_org_membership_role_check",
        ),
        CheckConstraint(
            "status IN ('active', 'pending_approval', 'deactivated')",
            name="platform_org_membership_status_check",
        ),
        CheckConstraint(
            "membership_kind IN ('permanent', 'temporary')",
            name="platform_org_membership_kind_check",
        ),
        CheckConstraint(
            "(approved_by IS NULL) = (approved_at IS NULL)",
            name="platform_org_membership_approval_check",
        ),
        CheckConstraint(
            "status <> 'pending_approval' OR approved_at IS NULL",
            name="platform_org_membership_pending_unapproved_check",
        ),
        ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["platform_user.organization_id", "platform_user.id"],
            name="platform_org_membership_same_org_fk",
            ondelete="CASCADE",
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
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    membership_kind: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'permanent'")
    )
    created_by: Mapped[str | None] = mapped_column(
        Text, ForeignKey("platform_user.id", ondelete="RESTRICT")
    )
    approved_by: Mapped[str | None] = mapped_column(
        Text, ForeignKey("platform_user.id", ondelete="RESTRICT")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Role(Base):
    """A named set of permissions for a scope kind — an organisation's own
    (pilot scope §3.5). The standard four are seeded per organisation."""

    __tablename__ = "role"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="role_org_name_key"),
        CheckConstraint(
            "scope_kind IN ('organization', 'project', 'team')", name="role_scope_kind_check"
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        Text, ForeignKey("platform_organization.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    scope_kind: Mapped[str] = mapped_column(Text, nullable=False)
    builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class RolePermission(Base):
    __tablename__ = "role_permission"
    __table_args__ = (
        CheckConstraint(
            "permission IN ('user.create', 'user.approve', 'user.deactivate', "
            "'user.assign_role', 'team.manage', 'sample.upload', 'sample.assign', "
            "'form.edit', 'form.publish', 'form.deploy', 'submission.view', "
            "'submission.review', 'export.download', 'device.revoke')",
            name="role_permission_name_check",
        ),
    )

    role_id: Mapped[str] = mapped_column(
        Text, ForeignKey("role.id", ondelete="CASCADE"), primary_key=True
    )
    permission: Mapped[str] = mapped_column(Text, primary_key=True)


class UserRole(Base):
    """This person holds this role in this scope: the organisation, one
    project, or one team. Exactly the column the scope kind names is set."""

    __tablename__ = "user_role"
    __table_args__ = (
        CheckConstraint(
            "scope_kind IN ('organization', 'project', 'team')",
            name="user_role_scope_kind_check",
        ),
        CheckConstraint(
            "(scope_kind = 'organization' AND project_id IS NULL AND team_id IS NULL) OR "
            "(scope_kind = 'project' AND project_id IS NOT NULL AND team_id IS NULL) OR "
            "(scope_kind = 'team' AND team_id IS NOT NULL)",
            name="user_role_scope_target_check",
        ),
        Index(
            "user_role_live_idx",
            "user_id",
            "role_id",
            "scope_kind",
            text("coalesce(project_id, '')"),
            text("coalesce(team_id, '')"),
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("platform_user.id", ondelete="RESTRICT"), nullable=False
    )
    role_id: Mapped[str] = mapped_column(
        Text, ForeignKey("role.id", ondelete="RESTRICT"), nullable=False
    )
    scope_kind: Mapped[str] = mapped_column(Text, nullable=False)
    project_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("project.id", ondelete="CASCADE")
    )
    team_id: Mapped[str | None] = mapped_column(Text, ForeignKey("team.id", ondelete="CASCADE"))
    granted_by: Mapped[str | None] = mapped_column(
        Text, ForeignKey("platform_user.id", ondelete="RESTRICT")
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlatformSession(Base):
    """A login: the hash of an opaque cookie token, for the console or for an
    app on one device. Visible — and creatable — only while the person's
    membership is active (the policy on this table, 008_identity.sql §7)."""

    __tablename__ = "platform_session"
    __table_args__ = (
        UniqueConstraint("token_hash", name="platform_session_token_hash_key"),
        CheckConstraint("kind IN ('console', 'app')", name="platform_session_kind_check"),
        CheckConstraint(
            "(kind = 'app') = (device_id IS NOT NULL)", name="platform_session_device_check"
        ),
        Index("platform_session_user_idx", "user_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("platform_user.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    device_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("device.id", ondelete="CASCADE")
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(Text)
