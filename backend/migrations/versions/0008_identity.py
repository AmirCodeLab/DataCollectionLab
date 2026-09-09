"""identity: a person, not a device, and row-level security on every table

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-07

migrations/schema/008_identity.sql is the NORMATIVE definition; this migration
transcribes it into Alembic operations so downgrade is real.
tests/test_migrations.py asserts that upgrading produces a schema identical to
executing the SQL files in name order. If they ever disagree, the SQL wins.

What cannot be an Alembic operation — the application role, the three policy
helpers, the policies themselves, the seeded roles — is executed as the same
SQL the normative file carries, and downgrade undoes each of them in turn:
policies dropped and row-level security disabled on every table, the helpers
dropped, the grants revoked. The role itself is left standing: it is a
cluster-level object other databases on the same server may reference, and a
role with no privileges is harmless.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


FIRST_ORGANIZATION = "(SELECT id FROM platform_organization ORDER BY created_at, id LIMIT 1)"
FIRST_PROJECT = "(SELECT id FROM project ORDER BY created_at, id LIMIT 1)"

PERMISSIONS = (
    "user.create",
    "user.approve",
    "user.deactivate",
    "user.assign_role",
    "team.manage",
    "sample.upload",
    "sample.assign",
    "form.edit",
    "form.publish",
    "form.deploy",
    "submission.view",
    "submission.review",
    "export.download",
    "device.revoke",
)

# (table, fk column, parent) — shape (b), in the order the normative file has.
CHAINED = (
    ("environment", "project_id", "project"),
    ("team", "project_id", "project"),
    ("project_member", "project_id", "project"),
    ("device", "project_id", "project"),
    ("project_key", "project_id", "project"),
    ("form", "project_id", "project"),
    ("entity_type", "project_id", "project"),
    ("dataset", "project_id", "project"),
    ("case_record", "project_id", "project"),
    ("tombstone", "project_id", "project"),
    ("quality_rule", "project_id", "project"),
    ("workflow_definition", "project_id", "project"),
    ("outbox_event", "project_id", "project"),
    ("user_role", "role_id", "role"),
    ("role_permission", "role_id", "role"),
    ("form_version", "form_id", "form"),
    ("form_draft", "form_id", "form"),
    ("form_deployment", "form_version_id", "form_version"),
    ("entity", "entity_type_id", "entity_type"),
    ("entity_relationship", "from_entity_id", "entity"),
    ("dataset_version", "dataset_id", "dataset"),
    ("dataset_record", "dataset_version_id", "dataset_version"),
    ("form_version_dataset", "form_version_id", "form_version"),
    ("assignment", "case_id", "case_record"),
    ("visit", "case_id", "case_record"),
    ("sync_cursor", "device_id", "device"),
    ("workflow_instance", "definition_id", "workflow_definition"),
    ("workflow_transition", "instance_id", "workflow_instance"),
    ("submission_content_key", "submission_id", "submission"),
    ("submission_wrapped_key", "submission_id", "submission"),
    ("submission_op", "submission_id", "submission"),
    ("submission_state", "submission_id", "submission"),
    ("submission_snapshot", "submission_id", "submission"),
    ("media", "submission_id", "submission"),
    ("media_upload_session", "media_id", "media"),
    ("media_wrapped_key", "media_id", "media"),
    ("media_chunk", "media_id", "media"),
    ("quality_flag", "submission_id", "submission"),
    ("review", "submission_id", "submission"),
)

ROOTS = ("project", "platform_user", "role", "audit_event", "platform_org_membership")

# Every table the normative file secures, for the downgrade to undo in full.
SECURED = (
    ROOTS
    + ("platform_organization", "platform_session", "submission")
    + tuple(table for table, _, _ in CHAINED)
)


def _quoted(values: Sequence[str]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    # -- 1. The application's role -------------------------------------------
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dcp_app') THEN
                CREATE ROLE dcp_app NOLOGIN;
            END IF;
        END
        $$
        """
    )
    op.execute("GRANT USAGE ON SCHEMA public TO dcp_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO dcp_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO dcp_app")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO dcp_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO dcp_app"
    )

    # -- 2. The discriminators -----------------------------------------------
    op.add_column("project", sa.Column("organization_id", sa.Text(), nullable=True))
    op.create_foreign_key(
        "project_organization_id_fkey",
        "project",
        "platform_organization",
        ["organization_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.execute(
        f"UPDATE project SET organization_id = {FIRST_ORGANIZATION} WHERE organization_id IS NULL"
    )
    op.alter_column("project", "organization_id", nullable=False)
    op.create_index("project_organization_idx", "project", ["organization_id"])

    op.add_column("platform_user", sa.Column("organization_id", sa.Text(), nullable=True))
    op.create_foreign_key(
        "platform_user_organization_id_fkey",
        "platform_user",
        "platform_organization",
        ["organization_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.execute(
        f"UPDATE platform_user SET organization_id = {FIRST_ORGANIZATION} "
        "WHERE organization_id IS NULL"
    )
    op.alter_column("platform_user", "organization_id", nullable=False)
    op.create_unique_constraint(
        "platform_user_org_id_key", "platform_user", ["organization_id", "id"]
    )

    op.add_column("audit_event", sa.Column("organization_id", sa.Text(), nullable=True))
    op.create_foreign_key(
        "audit_event_organization_id_fkey",
        "audit_event",
        "platform_organization",
        ["organization_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.execute(
        f"UPDATE audit_event SET organization_id = {FIRST_ORGANIZATION} "
        "WHERE organization_id IS NULL"
    )
    op.alter_column("audit_event", "organization_id", nullable=False)

    op.add_column("outbox_event", sa.Column("project_id", sa.Text(), nullable=True))
    op.create_foreign_key(
        "outbox_event_project_id_fkey",
        "outbox_event",
        "project",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.execute(f"UPDATE outbox_event SET project_id = {FIRST_PROJECT} WHERE project_id IS NULL")
    op.alter_column("outbox_event", "project_id", nullable=False)

    op.drop_column("platform_organization", "schema_name")

    # -- 3. People and memberships -------------------------------------------
    op.add_column(
        "platform_user",
        sa.Column("display_name", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column("platform_user", sa.Column("username", sa.Text(), nullable=True))
    op.add_column("platform_user", sa.Column("phone", sa.Text(), nullable=True))
    op.add_column("platform_user", sa.Column("created_by", sa.Text(), nullable=True))
    op.create_foreign_key(
        "platform_user_created_by_fkey",
        "platform_user",
        "platform_user",
        ["created_by"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column(
        "platform_user",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.alter_column("platform_user", "email", nullable=True)
    op.create_unique_constraint("platform_user_username_key", "platform_user", ["username"])

    op.add_column(
        "platform_org_membership",
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
    )
    op.add_column(
        "platform_org_membership",
        sa.Column("membership_kind", sa.Text(), nullable=False, server_default="permanent"),
    )
    op.add_column("platform_org_membership", sa.Column("created_by", sa.Text(), nullable=True))
    op.add_column("platform_org_membership", sa.Column("approved_by", sa.Text(), nullable=True))
    op.add_column(
        "platform_org_membership",
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "platform_org_membership",
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "platform_org_membership_created_by_fkey",
        "platform_org_membership",
        "platform_user",
        ["created_by"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "platform_org_membership_approved_by_fkey",
        "platform_org_membership",
        "platform_user",
        ["approved_by"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "platform_org_membership_status_check",
        "platform_org_membership",
        "status IN ('active', 'pending_approval', 'deactivated')",
    )
    op.create_check_constraint(
        "platform_org_membership_kind_check",
        "platform_org_membership",
        "membership_kind IN ('permanent', 'temporary')",
    )
    op.create_check_constraint(
        "platform_org_membership_approval_check",
        "platform_org_membership",
        "(approved_by IS NULL) = (approved_at IS NULL)",
    )
    op.create_check_constraint(
        "platform_org_membership_pending_unapproved_check",
        "platform_org_membership",
        "status <> 'pending_approval' OR approved_at IS NULL",
    )
    op.create_foreign_key(
        "platform_org_membership_same_org_fk",
        "platform_org_membership",
        "platform_user",
        ["organization_id", "user_id"],
        ["organization_id", "id"],
        ondelete="CASCADE",
    )

    # -- 4. Roles ------------------------------------------------------------
    op.create_table(
        "role",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("organization_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("scope_kind", sa.Text(), nullable=False),
        sa.Column("builtin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["platform_organization.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("organization_id", "name", name="role_org_name_key"),
        sa.CheckConstraint(
            "scope_kind IN ('organization', 'project', 'team')", name="role_scope_kind_check"
        ),
    )
    op.create_table(
        "role_permission",
        sa.Column("role_id", sa.Text(), primary_key=True),
        sa.Column("permission", sa.Text(), primary_key=True),
        sa.ForeignKeyConstraint(["role_id"], ["role.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            f"permission IN ({_quoted(PERMISSIONS)})", name="role_permission_name_check"
        ),
    )
    op.create_table(
        "user_role",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("role_id", sa.Text(), nullable=False),
        sa.Column("scope_kind", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=True),
        sa.Column("team_id", sa.Text(), nullable=True),
        sa.Column("granted_by", sa.Text(), nullable=True),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["platform_user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["role_id"], ["role.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["team.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by"], ["platform_user.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "scope_kind IN ('organization', 'project', 'team')",
            name="user_role_scope_kind_check",
        ),
        sa.CheckConstraint(
            "(scope_kind = 'organization' AND project_id IS NULL AND team_id IS NULL) OR "
            "(scope_kind = 'project' AND project_id IS NOT NULL AND team_id IS NULL) OR "
            "(scope_kind = 'team' AND team_id IS NOT NULL)",
            name="user_role_scope_target_check",
        ),
    )
    op.execute(
        "CREATE UNIQUE INDEX user_role_live_idx ON user_role "
        "(user_id, role_id, scope_kind, coalesce(project_id, ''), coalesce(team_id, '')) "
        "WHERE revoked_at IS NULL"
    )
    op.execute(
        """
        INSERT INTO role (id, organization_id, name, scope_kind, builtin)
        SELECT o.id || '_' || r.suffix, o.id, r.name, r.scope_kind, true
        FROM platform_organization o,
             (VALUES ('admin',      'Admin',             'organization'),
                     ('pm',         'Programme manager', 'project'),
                     ('supervisor', 'Supervisor',        'team'),
                     ('enumerator', 'Enumerator',        'team')) AS r(suffix, name, scope_kind)
        """
    )
    op.execute(
        f"""
        INSERT INTO role_permission (role_id, permission)
        SELECT r.id, p.name
        FROM role r,
             (VALUES {", ".join(f"('{p}')" for p in PERMISSIONS)}) AS p(name)
        WHERE r.builtin AND (
            (r.name = 'Admin')
            OR (r.name = 'Programme manager' AND p.name <> 'device.revoke')
            OR (r.name = 'Supervisor'
                AND p.name IN ('user.create', 'sample.assign', 'submission.view'))
        )
        """
    )

    # -- 5. Project membership ------------------------------------------------
    op.add_column(
        "project_member", sa.Column("status", sa.Text(), nullable=False, server_default="active")
    )
    op.add_column("project_member", sa.Column("added_by", sa.Text(), nullable=True))
    op.add_column(
        "project_member", sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_foreign_key(
        "project_member_added_by_fkey",
        "project_member",
        "platform_user",
        ["added_by"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "project_member_user_fk",
        "project_member",
        "platform_user",
        ["user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "project_member_status_check", "project_member", "status IN ('active', 'removed')"
    )
    op.drop_constraint("project_member_role_check", "project_member", type_="check")
    op.drop_column("project_member", "project_role")

    # -- 6. Devices ------------------------------------------------------------
    op.execute("UPDATE device SET user_id = NULL WHERE user_id = 'usr_unassigned'")
    op.alter_column("device", "user_id", nullable=True)
    op.add_column("device", sa.Column("bound_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "device_user_fk", "device", "platform_user", ["user_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_check_constraint(
        "device_bound_check", "device", "(user_id IS NULL) = (bound_at IS NULL)"
    )

    # -- 7. Sessions -----------------------------------------------------------
    op.create_table(
        "platform_session",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("device_id", sa.Text(), nullable=True),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["platform_user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["device.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("token_hash", name="platform_session_token_hash_key"),
        sa.CheckConstraint("kind IN ('console', 'app')", name="platform_session_kind_check"),
        sa.CheckConstraint(
            "(kind = 'app') = (device_id IS NOT NULL)", name="platform_session_device_check"
        ),
    )
    op.create_index("platform_session_user_idx", "platform_session", ["user_id"])

    # -- 8. Who did what -------------------------------------------------------
    for name, table, column in (
        ("form_version_published_by_fk", "form_version", "published_by"),
        ("form_deployment_deployed_by_fk", "form_deployment", "deployed_by"),
        ("form_draft_updated_by_fk", "form_draft", "updated_by"),
        ("assignment_user_fk", "assignment", "user_id"),
        ("assignment_assigned_by_fk", "assignment", "assigned_by"),
        ("audit_event_actor_fk", "audit_event", "actor_id"),
    ):
        op.create_foreign_key(name, table, "platform_user", [column], ["id"], ondelete="RESTRICT")

    # -- 9. Row-level security, from three helpers ------------------------------
    op.execute(
        "CREATE FUNCTION dcp_principal(name text) RETURNS text LANGUAGE sql STABLE "
        "RETURN coalesce(current_setting(name, true), '')"
    )
    op.execute(
        """
        CREATE FUNCTION dcp_policy(tbl regclass, using_expr text) RETURNS void
            LANGUAGE plpgsql AS $$
        BEGIN
            EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY', tbl);
            EXECUTE format('ALTER TABLE %s FORCE ROW LEVEL SECURITY', tbl);
            EXECUTE format('DROP POLICY IF EXISTS isolation ON %s', tbl);
            EXECUTE format('CREATE POLICY isolation ON %s USING (%s) WITH CHECK (%s)',
                           tbl, using_expr, using_expr);
        END
        $$
        """
    )
    op.execute(
        "CREATE FUNCTION dcp_policy_root(tbl regclass) RETURNS void LANGUAGE sql "
        "RETURN dcp_policy(tbl, 'organization_id = dcp_principal(''app.org_id'')')"
    )
    op.execute(
        "CREATE FUNCTION dcp_policy_chain(tbl regclass, fk_column text, parent regclass) "
        "RETURNS void LANGUAGE sql "
        "RETURN dcp_policy(tbl, format('%I IN (SELECT id FROM %s)', fk_column, parent))"
    )
    for table in ROOTS:
        op.execute(f"SELECT dcp_policy_root('{table}')")
    op.execute(
        "SELECT dcp_policy('platform_organization', "
        "'id = dcp_principal(''app.org_id'') OR slug = dcp_principal(''app.org_slug'')')"
    )
    op.execute(
        "SELECT dcp_policy('platform_session', "
        "'EXISTS (SELECT 1 FROM platform_org_membership m "
        " WHERE m.user_id = platform_session.user_id AND m.status = ''active'')')"
    )
    for table, column, parent in CHAINED[:15]:
        op.execute(f"SELECT dcp_policy_chain('{table}', '{column}', '{parent}')")
    for table, column, parent in CHAINED[15:28]:
        op.execute(f"SELECT dcp_policy_chain('{table}', '{column}', '{parent}')")
    op.execute(
        "SELECT dcp_policy('submission', "
        "'project_id IN (SELECT id FROM project) AND ("
        "  created_by = ANY (string_to_array(dcp_principal(''app.visible_user_ids''), '','')) "
        "  OR dcp_principal(''app.scope_kind'') = ''organization'')')"
    )
    for table, column, parent in CHAINED[28:]:
        op.execute(f"SELECT dcp_policy_chain('{table}', '{column}', '{parent}')")


def downgrade() -> None:
    # -- 9. Policies off every table, helpers gone ------------------------------
    for table in SECURED:
        op.execute(f"DROP POLICY IF EXISTS isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP FUNCTION dcp_policy_chain(regclass, text, regclass)")
    op.execute("DROP FUNCTION dcp_policy_root(regclass)")
    op.execute("DROP FUNCTION dcp_policy(regclass, text)")
    op.execute("DROP FUNCTION dcp_principal(text)")

    # -- 8. Who did what ---------------------------------------------------------
    for name, table in (
        ("audit_event_actor_fk", "audit_event"),
        ("assignment_assigned_by_fk", "assignment"),
        ("assignment_user_fk", "assignment"),
        ("form_draft_updated_by_fk", "form_draft"),
        ("form_deployment_deployed_by_fk", "form_deployment"),
        ("form_version_published_by_fk", "form_version"),
    ):
        op.drop_constraint(name, table, type_="foreignkey")

    # -- 7. Sessions -------------------------------------------------------------
    op.drop_index("platform_session_user_idx", table_name="platform_session")
    op.drop_table("platform_session")

    # -- 6. Devices --------------------------------------------------------------
    op.drop_constraint("device_bound_check", "device", type_="check")
    op.drop_constraint("device_user_fk", "device", type_="foreignkey")
    op.drop_column("device", "bound_at")
    op.execute("UPDATE device SET user_id = 'usr_unassigned' WHERE user_id IS NULL")
    op.alter_column("device", "user_id", nullable=False)

    # -- 5. Project membership ---------------------------------------------------
    op.add_column(
        "project_member",
        sa.Column("project_role", sa.Text(), nullable=False, server_default="enumerator"),
    )
    op.alter_column("project_member", "project_role", server_default=None)
    op.create_check_constraint(
        "project_member_role_check",
        "project_member",
        "project_role IN ('manager', 'supervisor', 'enumerator', 'analyst', 'viewer')",
    )
    op.drop_constraint("project_member_status_check", "project_member", type_="check")
    op.drop_constraint("project_member_user_fk", "project_member", type_="foreignkey")
    op.drop_constraint("project_member_added_by_fkey", "project_member", type_="foreignkey")
    op.drop_column("project_member", "removed_at")
    op.drop_column("project_member", "added_by")
    op.drop_column("project_member", "status")

    # -- 4. Roles ----------------------------------------------------------------
    op.execute("DROP INDEX user_role_live_idx")
    op.drop_table("user_role")
    op.drop_table("role_permission")
    op.drop_table("role")

    # -- 3. People and memberships ------------------------------------------------
    op.drop_constraint(
        "platform_org_membership_same_org_fk", "platform_org_membership", type_="foreignkey"
    )
    for name in (
        "platform_org_membership_pending_unapproved_check",
        "platform_org_membership_approval_check",
        "platform_org_membership_kind_check",
        "platform_org_membership_status_check",
    ):
        op.drop_constraint(name, "platform_org_membership", type_="check")
    op.drop_constraint(
        "platform_org_membership_approved_by_fkey", "platform_org_membership", type_="foreignkey"
    )
    op.drop_constraint(
        "platform_org_membership_created_by_fkey", "platform_org_membership", type_="foreignkey"
    )
    for column in (
        "deactivated_at",
        "approved_at",
        "approved_by",
        "created_by",
        "membership_kind",
        "status",
    ):
        op.drop_column("platform_org_membership", column)

    op.drop_constraint("platform_user_username_key", "platform_user", type_="unique")
    op.execute("UPDATE platform_user SET email = id WHERE email IS NULL")
    op.alter_column("platform_user", "email", nullable=False)
    op.drop_column("platform_user", "updated_at")
    op.drop_constraint("platform_user_created_by_fkey", "platform_user", type_="foreignkey")
    op.drop_column("platform_user", "created_by")
    op.drop_column("platform_user", "phone")
    op.drop_column("platform_user", "username")
    op.drop_column("platform_user", "display_name")

    # -- 2. The discriminators ----------------------------------------------------
    op.add_column(
        "platform_organization",
        sa.Column("schema_name", sa.Text(), nullable=False, server_default="public"),
    )
    op.alter_column("platform_organization", "schema_name", server_default=None)
    op.create_unique_constraint(
        "platform_organization_schema_name_key", "platform_organization", ["schema_name"]
    )
    op.drop_constraint("outbox_event_project_id_fkey", "outbox_event", type_="foreignkey")
    op.drop_column("outbox_event", "project_id")
    op.drop_constraint("audit_event_organization_id_fkey", "audit_event", type_="foreignkey")
    op.drop_column("audit_event", "organization_id")
    op.drop_constraint("platform_user_org_id_key", "platform_user", type_="unique")
    op.drop_constraint("platform_user_organization_id_fkey", "platform_user", type_="foreignkey")
    op.drop_column("platform_user", "organization_id")
    op.drop_index("project_organization_idx", table_name="project")
    op.drop_constraint("project_organization_id_fkey", "project", type_="foreignkey")
    op.drop_column("project", "organization_id")

    # -- 1. The application's role: privileges revoked, the role left standing ----
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM dcp_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE USAGE, SELECT ON SEQUENCES FROM dcp_app"
    )
    op.execute("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM dcp_app")
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM dcp_app")
    op.execute("REVOKE USAGE ON SCHEMA public FROM dcp_app")
