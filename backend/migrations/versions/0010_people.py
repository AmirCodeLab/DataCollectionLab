"""People: the principal carries the person's authority, and the database reads it

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-09

migrations/schema/010_people.sql is the NORMATIVE definition. This migration
executes that file rather than transcribing it: it is functions and policies
end to end, where a transcription's one wrong quote is a policy that admits
nothing or everything and looks identical in the catalogue snapshot
tests/test_migrations.py compares (policies are not columns). Reading the file
makes the two identical by construction. The downgrade is written by hand and
restores 008/009's policies exactly, so reversibility is real.
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NORMATIVE = Path(__file__).resolve().parents[1] / "schema" / "010_people.sql"


def _statements(sql: str) -> list[str]:
    """Split on the semicolons that end statements: outside quotes and outside
    `$$` bodies. The driver prepares each statement, and a prepared statement
    holds exactly one."""
    out: list[str] = []
    current: list[str] = []
    i, quoted, dollar = 0, False, False
    while i < len(sql):
        ch = sql[i]
        if not quoted and not dollar and sql.startswith("--", i):
            # A comment runs to the end of the line, apostrophes and all.
            end = sql.find("\n", i)
            i = len(sql) if end == -1 else end
            continue
        if not quoted and sql.startswith("$$", i):
            dollar = not dollar
            current.append("$$")
            i += 2
            continue
        if not dollar and ch == "'":
            quoted = not quoted
        if ch == ";" and not quoted and not dollar:
            statement = "".join(current).strip()
            if statement:
                out.append(statement)
            current = []
        else:
            current.append(ch)
        i += 1
    tail = "".join(current).strip()
    if tail:
        out.append(tail)
    return out


def upgrade() -> None:
    for statement in _statements(NORMATIVE.read_text()):
        op.execute(statement)


def downgrade() -> None:
    # The policies as 008 wrote them.
    for table in ("role", "role_permission"):
        op.execute(f"DROP POLICY IF EXISTS builtin_kept ON {table}")
    op.execute("DROP POLICY IF EXISTS own_authority ON role_permission")
    for table in ("platform_user", "platform_org_membership", "role"):
        op.execute(f"SELECT dcp_policy_root('{table}')")
    for table, column, parent in (
        ("user_role", "role_id", "role"),
        ("role_permission", "role_id", "role"),
        ("project_member", "project_id", "project"),
        ("team", "project_id", "project"),
    ):
        op.execute(f"SELECT dcp_policy_chain('{table}', '{column}', '{parent}')")
    op.execute(
        "SELECT dcp_policy('platform_session', "
        "'EXISTS (SELECT 1 FROM platform_org_membership m "
        " WHERE m.user_id = platform_session.user_id AND m.status = ''active'')')"
    )
    # The membership default, and the Supervisor's extra permission.
    op.execute("ALTER TABLE platform_org_membership ALTER COLUMN status SET DEFAULT 'active'")
    op.execute("DROP FUNCTION dcp_default_membership_status()")
    op.execute(
        "DELETE FROM role_permission rp USING role r "
        "WHERE rp.role_id = r.id AND r.builtin AND r.name = 'Supervisor' "
        "AND rp.permission = 'user.assign_role'"
    )
    # The functions this migration added.
    for signature in (
        "dcp_note_login(text)",
        "dcp_membership_status(text)",
        "dcp_principal_for(text)",
        "dcp_session_lookup(text)",
        "dcp_login_lookup(text)",
        "dcp_membership_active(text)",
        "dcp_restrict(regclass, text, text, text)",
        "dcp_policy(regclass, text, text)",
        "dcp_org_wide()",
        "dcp_in_list(text, text)",
        "dcp_has(text)",
    ):
        op.execute(f"DROP FUNCTION {signature}")
