"""A case is held only by someone whose membership is active

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-09

migrations/schema/014_assignment_needs_active_membership.sql is the NORMATIVE
definition; the downgrade restores 012's function exactly.
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NORMATIVE = (
    Path(__file__).resolve().parents[1] / "schema" / "014_assignment_needs_active_membership.sql"
)

# One statement, no `$$` body and no quoted semicolon, so the file is the
# statement once its comments are dropped.
BEFORE = """
CREATE OR REPLACE FUNCTION dcp_person_under_live_team(the_case text, person text) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public
    RETURN EXISTS (SELECT 1 FROM assignment a
                   JOIN project_member pm ON pm.team_id = a.team_id AND pm.user_id = person
                   WHERE a.case_id = the_case AND a.released_at IS NULL
                     AND a.team_id IS NOT NULL AND pm.status = 'active')
"""


def upgrade() -> None:
    sql = "\n".join(
        line for line in NORMATIVE.read_text().splitlines() if not line.startswith("--")
    ).strip().rstrip(";")
    op.execute(sql)


def downgrade() -> None:
    op.execute(BEFORE.strip())
