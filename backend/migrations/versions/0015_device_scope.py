"""Devices belong to the person who signed in on them, and report their own backlog

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-10

migrations/schema/015_device_scope.sql is the NORMATIVE definition, executed
here statement by statement (the reason 0010 gives). The downgrade restores
008's project chain on `device` exactly, drops the four definer functions
and drops the two reported columns.
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NORMATIVE = Path(__file__).resolve().parents[1] / "schema" / "015_device_scope.sql"


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
    op.execute(
        "DROP FUNCTION IF EXISTS dcp_bind_device(text, text), "
        "dcp_device_seen(text, text, text, text), dcp_device_by_id(text), "
        "dcp_device_register(text, text, text, text, text)"
    )
    op.execute("ALTER TABLE device DROP COLUMN reported_at")
    op.execute("ALTER TABLE device DROP COLUMN reported_pending_ops")
    # 008's policy, restored exactly: the project chain and nothing finer.
    op.execute("SELECT dcp_policy_chain('device', 'project_id', 'project')")
