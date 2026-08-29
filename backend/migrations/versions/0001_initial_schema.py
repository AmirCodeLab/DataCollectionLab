"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-29

migrations/schema/001_initial.sql is the NORMATIVE schema definition; this
migration transcribes it into Alembic operations so downgrade is real and
future revisions can autogenerate against app/modules/*/models.py.
tests/test_migrations.py asserts that upgrading produces a schema identical
to executing the SQL file directly — tables, columns, types, defaults,
constraints and indexes. If they ever disagree, the SQL file wins.
"""

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    # One arrival sequence shared by submission_op and tombstone: the pull
    # cursor is a single integer over both streams (sync protocol §5).
    op.execute("CREATE SEQUENCE sync_stream_seq")
    op.create_table(
        "audit_event",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=True),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "audit_event_subject_idx",
        "audit_event",
        ["subject_type", "subject_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "outbox_event",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "outbox_event_unpublished_idx",
        "outbox_event",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("published_at IS NULL"),
    )
    op.create_table(
        "platform_organization",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("schema_name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("schema_name"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "platform_user",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("mfa_secret", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('active', 'invited', 'suspended', 'deactivated')",
            name="platform_user_status_check",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "project",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("security_mode", sa.Text(), server_default=sa.text("'standard'"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "security_mode IN ('standard', 'field_level', 'project_e2e')",
            name="project_security_mode_check",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "dataset",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("dataset_key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "dataset_key"),
    )
    op.create_table(
        "device",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("os_version", sa.Text(), nullable=True),
        sa.Column("app_version", sa.Text(), nullable=True),
        sa.Column("last_counter", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "platform IN ('android', 'ios', 'desktop', 'web')", name="device_platform_check"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "entity_type",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("type_key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "schema_def",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "type_key"),
    )
    op.create_table(
        "environment",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('development', 'staging', 'production')", name="environment_kind_check"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "kind"),
    )
    op.create_table(
        "form",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("form_key", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "form_key"),
    )
    op.create_table(
        "platform_org_membership",
        sa.Column("organization_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("org_role", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "org_role IN ('owner', 'admin', 'member')", name="platform_org_membership_role_check"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["platform_organization.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["platform_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("organization_id", "user_id"),
    )
    op.create_table(
        "project_key",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("public_key", postgresql.BYTEA(), nullable=False),
        sa.Column("key_role", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "key_role IN ('primary', 'backup', 'recovery')", name="project_key_role_check"
        ),
        sa.CheckConstraint("octet_length(public_key) = 32", name="project_key_length_check"),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "team",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("parent_team_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["parent_team_id"], ["team.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "workflow_definition",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", "version"),
    )
    op.create_table(
        "dataset_version",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("dataset_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("row_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("checksum", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["dataset_id"], ["dataset.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_id", "version"),
    )
    op.create_table(
        "entity",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("entity_type_id", sa.Text(), nullable=False),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "location",
            geoalchemy2.types.Geography(
                geometry_type="POINT",
                srid=4326,
                dimension=2,
                spatial_index=False,
                from_text="ST_GeogFromText",
                name="geography",
            ),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["entity_type_id"], ["entity_type.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "form_version",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("form_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("ir", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("ir_checksum", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["form_id"], ["form.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("form_id", "version"),
    )
    op.create_table(
        "project_member",
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("project_role", sa.Text(), nullable=False),
        sa.Column("team_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "project_role IN ('manager', 'supervisor', 'enumerator', 'analyst', 'viewer')",
            name="project_member_role_check",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["team.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("project_id", "user_id"),
    )
    op.create_table(
        "quality_rule",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("form_id", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("severity", sa.Text(), server_default=sa.text("'warning'"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "severity IN ('info', 'warning', 'error')", name="quality_rule_severity_check"
        ),
        sa.ForeignKeyConstraint(["form_id"], ["form.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "sync_cursor",
        sa.Column("device_id", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("cursor_value", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["device_id"], ["device.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("device_id", "scope"),
    )
    op.create_table(
        "workflow_instance",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("definition_id", sa.Text(), nullable=False),
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("sla_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "subject_type IN ('submission', 'case', 'visit')",
            name="workflow_instance_subject_check",
        ),
        sa.ForeignKeyConstraint(["definition_id"], ["workflow_definition.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "workflow_instance_sla_idx",
        "workflow_instance",
        ["sla_due_at"],
        unique=False,
        postgresql_where=sa.text("closed_at IS NULL"),
    )
    op.create_table(
        "case_record",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=True),
        sa.Column("case_key", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'open'"), nullable=False),
        sa.Column("priority", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "location",
            geoalchemy2.types.Geography(
                geometry_type="POINT",
                srid=4326,
                dimension=2,
                spatial_index=False,
                from_text="ST_GeogFromText",
                name="geography",
            ),
            nullable=True,
        ),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["entity_id"], ["entity.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "case_key"),
    )
    op.create_table(
        "dataset_record",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("dataset_version_id", sa.Text(), nullable=False),
        sa.Column("record_key", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["dataset_version_id"], ["dataset_version.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_version_id", "record_key"),
    )
    op.create_table(
        "entity_relationship",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("from_entity_id", sa.Text(), nullable=False),
        sa.Column("to_entity_id", sa.Text(), nullable=False),
        sa.Column("relation_kind", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["from_entity_id"], ["entity.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_entity_id"], ["entity.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("from_entity_id", "to_entity_id", "relation_kind"),
    )
    op.create_table(
        "form_deployment",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("environment_id", sa.Text(), nullable=False),
        sa.Column("form_version_id", sa.Text(), nullable=False),
        sa.Column(
            "deployed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deployed_by", sa.Text(), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["environment_id"], ["environment.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["form_version_id"], ["form_version.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "workflow_transition",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("instance_id", sa.Text(), nullable=False),
        sa.Column("from_state", sa.Text(), nullable=True),
        sa.Column("to_state", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["instance_id"], ["workflow_instance.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "assignment",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=True),
        sa.Column("team_id", sa.Text(), nullable=True),
        sa.Column("assigned_by", sa.Text(), nullable=True),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "user_id IS NOT NULL OR team_id IS NOT NULL", name="assignment_target_check"
        ),
        sa.ForeignKeyConstraint(["case_id"], ["case_record.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["team.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "visit",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("form_version_id", sa.Text(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["case_id"], ["case_record.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["form_version_id"], ["form_version.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "sequence"),
    )
    op.create_table(
        "submission",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("environment_id", sa.Text(), nullable=False),
        sa.Column("form_version_id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=True),
        sa.Column("visit_id", sa.Text(), nullable=True),
        sa.Column("origin_device_id", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'finalized', 'in_review', 'approved', 'rejected', "
            "'correction_required')",
            name="submission_status_check",
        ),
        sa.ForeignKeyConstraint(["case_id"], ["case_record.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["environment_id"], ["environment.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["form_version_id"], ["form_version.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["origin_device_id"], ["device.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["visit_id"], ["visit.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "quality_flag",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("submission_id", sa.Text(), nullable=False),
        sa.Column("rule_id", sa.Text(), nullable=True),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["rule_id"], ["quality_rule.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["submission_id"], ["submission.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "quality_flag_open_idx",
        "quality_flag",
        ["submission_id"],
        unique=False,
        postgresql_where=sa.text("resolved_at IS NULL"),
    )
    op.create_table(
        "review",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("submission_id", sa.Text(), nullable=False),
        sa.Column("reviewer_id", sa.Text(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision IN ('approved', 'rejected', 'correction_required', 'comment')",
            name="review_decision_check",
        ),
        sa.ForeignKeyConstraint(["submission_id"], ["submission.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "submission_content_key",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("submission_id", sa.Text(), nullable=False),
        sa.Column("device_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["device_id"], ["device.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["submission_id"], ["submission.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("submission_id", "device_id"),
    )
    op.create_table(
        "submission_state",
        sa.Column("submission_id", sa.Text(), nullable=False),
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("op_high_water", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["submission_id"], ["submission.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("submission_id"),
    )
    op.create_table(
        "tombstone",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column("submission_id", sa.Text(), nullable=True),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("device_id", sa.Text(), nullable=True),
        sa.Column("counter", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "server_seq",
            sa.BigInteger(),
            server_default=sa.text("nextval('sync_stream_seq')"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "subject_type IN ('submission', 'repeat_instance', 'case', 'entity', 'media')",
            name="tombstone_subject_check",
        ),
        sa.ForeignKeyConstraint(["device_id"], ["device.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["submission_id"], ["submission.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_seq"),
    )
    op.create_index("tombstone_pull_idx", "tombstone", ["project_id", "created_at"], unique=False)
    op.create_table(
        "media",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("submission_id", sa.Text(), nullable=False),
        sa.Column("op_id", sa.Text(), nullable=True),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("chunk_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("ciphertext_hash", sa.Text(), nullable=True),
        sa.Column("encrypted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("content_key_id", sa.Text(), nullable=True),
        sa.Column("storage_key", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'uploading', 'complete', 'failed')", name="media_status_check"
        ),
        sa.ForeignKeyConstraint(
            ["content_key_id"], ["submission_content_key.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["submission_id"], ["submission.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "submission_op",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("submission_id", sa.Text(), nullable=False),
        sa.Column("op_kind", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("value_ciphertext", postgresql.BYTEA(), nullable=True),
        sa.Column("content_key_id", sa.Text(), nullable=True),
        sa.Column("nonce", postgresql.BYTEA(), nullable=True),
        sa.Column("device_id", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=True),
        sa.Column("counter", sa.BigInteger(), nullable=False),
        sa.Column("wall_clock", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "server_seq",
            sa.BigInteger(),
            server_default=sa.text("nextval('sync_stream_seq')"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "op_kind IN ('set', 'unset', 'repeat_add', 'repeat_delete', 'finalize', 'reopen')",
            name="submission_op_kind_check",
        ),
        sa.CheckConstraint(
            "(value_ciphertext IS NULL AND content_key_id IS NULL AND nonce IS NULL) "
            "OR (value_ciphertext IS NOT NULL AND content_key_id IS NOT NULL "
            "AND nonce IS NOT NULL AND value IS NULL)",
            name="submission_op_encryption_check",
        ),
        sa.ForeignKeyConstraint(
            ["content_key_id"], ["submission_content_key.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["device_id"], ["device.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["submission_id"], ["submission.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_seq"),
        sa.UniqueConstraint("content_key_id", "nonce"),
        sa.UniqueConstraint("device_id", "counter"),
    )
    op.create_index("submission_op_received_idx", "submission_op", ["received_at"], unique=False)
    op.create_index(
        "submission_op_replay_idx",
        "submission_op",
        ["submission_id", "counter", "device_id"],
        unique=False,
    )
    op.create_table(
        "submission_snapshot",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("submission_id", sa.Text(), nullable=False),
        sa.Column("op_count", sa.Integer(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("data_ciphertext", postgresql.BYTEA(), nullable=True),
        sa.Column("content_key_id", sa.Text(), nullable=True),
        sa.Column("nonce", postgresql.BYTEA(), nullable=True),
        sa.Column(
            "taken_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["content_key_id"], ["submission_content_key.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["submission_id"], ["submission.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "submission_wrapped_key",
        sa.Column("content_key_id", sa.Text(), nullable=False),
        sa.Column("project_key_id", sa.Text(), nullable=False),
        sa.Column("submission_id", sa.Text(), nullable=False),
        sa.Column("ephemeral_public", postgresql.BYTEA(), nullable=False),
        sa.Column("nonce", postgresql.BYTEA(), nullable=False),
        sa.Column("wrapped_key", postgresql.BYTEA(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "octet_length(ephemeral_public) = 32 AND octet_length(nonce) = 12 "
            "AND octet_length(wrapped_key) = 48",
            name="submission_wrapped_key_sizes_check",
        ),
        sa.ForeignKeyConstraint(
            ["content_key_id"], ["submission_content_key.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_key_id"], ["project_key.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["submission_id"], ["submission.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("content_key_id", "project_key_id"),
    )
    op.create_table(
        "media_upload_session",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("media_id", sa.Text(), nullable=False),
        sa.Column("chunk_size", sa.Integer(), nullable=False),
        sa.Column("received_chunks", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["media_id"], ["media.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    # Reverse dependency order, so a missed dependency fails loudly.
    op.drop_table("media_upload_session")
    op.drop_table("submission_wrapped_key")
    op.drop_table("submission_snapshot")
    op.drop_index("submission_op_replay_idx", table_name="submission_op")
    op.drop_index("submission_op_received_idx", table_name="submission_op")
    op.drop_table("submission_op")
    op.drop_table("media")
    op.drop_index("tombstone_pull_idx", table_name="tombstone")
    op.drop_table("tombstone")
    op.drop_table("submission_state")
    op.drop_table("submission_content_key")
    op.drop_table("review")
    op.drop_index(
        "quality_flag_open_idx",
        table_name="quality_flag",
        postgresql_where=sa.text("resolved_at IS NULL"),
    )
    op.drop_table("quality_flag")
    op.drop_table("submission")
    op.drop_table("visit")
    op.drop_table("assignment")
    op.drop_table("workflow_transition")
    op.drop_table("form_deployment")
    op.drop_table("entity_relationship")
    op.drop_table("dataset_record")
    op.drop_table("case_record")
    op.drop_index(
        "workflow_instance_sla_idx",
        table_name="workflow_instance",
        postgresql_where=sa.text("closed_at IS NULL"),
    )
    op.drop_table("workflow_instance")
    op.drop_table("sync_cursor")
    op.drop_table("quality_rule")
    op.drop_table("project_member")
    op.drop_table("form_version")
    op.drop_table("entity")
    op.drop_table("dataset_version")
    op.drop_table("workflow_definition")
    op.drop_table("team")
    op.drop_table("project_key")
    op.drop_table("platform_org_membership")
    op.drop_table("form")
    op.drop_table("environment")
    op.drop_table("entity_type")
    op.drop_table("device")
    op.drop_table("dataset")
    op.drop_table("project")
    op.drop_table("platform_user")
    op.drop_table("platform_organization")
    op.drop_index(
        "outbox_event_unpublished_idx",
        table_name="outbox_event",
        postgresql_where=sa.text("published_at IS NULL"),
    )
    op.drop_table("outbox_event")
    op.drop_index("audit_event_subject_idx", table_name="audit_event")
    op.drop_table("audit_event")
    op.execute("DROP SEQUENCE sync_stream_seq")
    # Dropped only if nothing else in the database depends on it — a
    # self-hosted install may share the database with other postgis users.
    op.execute(
        """
        DO $do$ BEGIN
            DROP EXTENSION IF EXISTS postgis;
        EXCEPTION WHEN dependent_objects_still_exist THEN
            RAISE NOTICE 'postgis extension retained: other objects depend on it';
        END $do$
        """
    )
