"""One more permission: project.manage

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-09

migrations/schema/009_project_manage.sql is the NORMATIVE definition; this
migration transcribes it so downgrade is real. tests/test_migrations.py
asserts that upgrading produces a schema identical to executing the SQL files
in name order. If they ever disagree, the SQL wins.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BEFORE = (
    "'user.create', 'user.approve', 'user.deactivate', 'user.assign_role', "
    "'team.manage', 'sample.upload', 'sample.assign', "
    "'form.edit', 'form.publish', 'form.deploy', "
    "'submission.view', 'submission.review', 'export.download', 'device.revoke'"
)
_AFTER = _BEFORE + ", 'project.manage'"


def _check(members: str) -> None:
    op.execute(
        "ALTER TABLE role_permission ADD CONSTRAINT role_permission_name_check "
        f"CHECK (permission IN ({members}))"
    )


def upgrade() -> None:
    op.execute("ALTER TABLE role_permission DROP CONSTRAINT role_permission_name_check")
    _check(_AFTER)
    op.execute(
        "INSERT INTO role_permission (role_id, permission) "
        "SELECT r.id, 'project.manage' FROM role r "
        "WHERE r.builtin AND r.name IN ('Admin', 'Programme manager') "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM role_permission WHERE permission = 'project.manage'")
    op.execute("ALTER TABLE role_permission DROP CONSTRAINT role_permission_name_check")
    _check(_BEFORE)
