"""The review loop gets its policies, its provenance and its reviewer

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-10

migrations/schema/016_review.sql is the NORMATIVE definition, executed here
statement by statement (the reason 0010 gives). The downgrade drops the
policies it added, the columns it added and the grant it made — and puts
back 001's open-flag index, which this migration narrows.
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NORMATIVE = Path(__file__).resolve().parents[1] / "schema" / "016_review.sql"


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
    op.execute("DROP POLICY IF EXISTS review_is_never_deleted ON review")
    op.execute("DROP POLICY IF EXISTS review_is_append_only ON review")
    for table in ("review", "quality_flag", "quality_rule"):
        op.execute(f"DROP POLICY IF EXISTS isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE project DROP CONSTRAINT project_review_policy_check")
    op.execute("ALTER TABLE project DROP COLUMN review_policy")
    op.execute("DROP INDEX IF EXISTS quality_flag_unevaluated_idx")
    op.execute("DROP INDEX IF EXISTS quality_flag_open_idx")
    # 001's index, exactly: every unresolved flag, whatever its outcome.
    op.execute(
        "CREATE INDEX quality_flag_open_idx ON quality_flag (submission_id) "
        "WHERE resolved_at IS NULL"
    )
    op.execute("ALTER TABLE quality_flag DROP CONSTRAINT quality_flag_outcome_check")
    op.execute(
        "ALTER TABLE quality_flag DROP COLUMN rule_definition, "
        "DROP COLUMN rule_name, DROP COLUMN outcome"
    )
    op.execute(
        "DELETE FROM role_permission WHERE permission = 'submission.review' "
        "AND role_id IN (SELECT id FROM role WHERE builtin AND name = 'Supervisor')"
    )
