"""Cases: a sample row held at two levels, everything under it in scope when it is

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-09

migrations/schema/012_cases.sql is the NORMATIVE definition, executed here
statement by statement for the reason 0010 gives: functions and policies end
to end, where a transcription's one wrong quote is a policy that admits
nothing or everything and looks identical in the catalogue snapshot. The
downgrade is by hand and restores 008's policies on the four tables exactly.
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NORMATIVE = Path(__file__).resolve().parents[1] / "schema" / "012_cases.sql"


def _statements(sql: str) -> list[str]:
    """Split on the semicolons that end statements: outside quotes, outside
    `$$` bodies, and not inside a `--` comment. The driver prepares each
    statement, and a prepared statement holds exactly one."""
    out: list[str] = []
    current: list[str] = []
    i, quoted, dollar = 0, False, False
    while i < len(sql):
        ch = sql[i]
        if not quoted and not dollar and sql.startswith("--", i):
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
    # The policies as 008 wrote them, and 010's submission policy.
    op.execute("DROP POLICY IF EXISTS never_deleted ON case_record")
    op.execute("SELECT dcp_policy_chain('case_record', 'project_id', 'project')")
    op.execute("SELECT dcp_policy_chain('assignment', 'case_id', 'case_record')")
    op.execute("SELECT dcp_policy_chain('visit', 'case_id', 'case_record')")
    before = (
        "project_id IN (SELECT id FROM project) AND ("
        "  created_by = ANY (string_to_array(dcp_principal('app.visible_user_ids'), ','))"
        "  OR dcp_principal('app.scope_kind') = 'organization')"
    )
    op.execute("SELECT dcp_policy('submission', '" + before.replace("'", "''") + "')")
    for signature in (
        "dcp_upsert_cases(text, text, text[], text[])",
        "dcp_assign_case(text, text, text, text)",
        "dcp_person_under_live_team(text, text)",
        "dcp_case_assigned_to_me(text)",
        "dcp_case_in_scope(text)",
    ):
        op.execute(f"DROP FUNCTION {signature}")
    op.execute("DROP INDEX assignment_live_person_idx")
    op.execute("DROP INDEX assignment_live_team_idx")
    op.execute("ALTER TABLE assignment DROP CONSTRAINT assignment_target_check")
    op.execute(
        "ALTER TABLE assignment ADD CONSTRAINT assignment_target_check "
        "CHECK (user_id IS NOT NULL OR team_id IS NOT NULL)"
    )
    op.execute("ALTER TABLE case_record DROP CONSTRAINT case_record_sample_check")
    op.execute("ALTER TABLE case_record DROP CONSTRAINT case_record_status_check")
    op.execute("ALTER TABLE case_record DROP COLUMN dataset_key")
