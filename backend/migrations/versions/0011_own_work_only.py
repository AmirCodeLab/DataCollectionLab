"""Seeing other people's work is a permission

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-09

migrations/schema/011_own_work_only.sql is the NORMATIVE definition: one
CREATE OR REPLACE of `dcp_principal_for`, executed as written. The downgrade
restores 010's body exactly.
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NORMATIVE = Path(__file__).resolve().parents[1] / "schema" / "011_own_work_only.sql"

# 010's body, for the downgrade.
_BEFORE = """
CREATE OR REPLACE FUNCTION dcp_principal_for(person text)
    RETURNS TABLE (scope_kind text, visible_user_ids text[], project_ids text[],
                   team_ids text[], permissions text[])
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public
    AS $$
        WITH RECURSIVE grants AS (
            SELECT ur.scope_kind, ur.project_id, ur.team_id, ur.role_id
            FROM user_role ur
            WHERE ur.user_id = person AND ur.revoked_at IS NULL
        ),
        teams AS (
            SELECT g.team_id AS id FROM grants g WHERE g.team_id IS NOT NULL
            UNION
            SELECT t.id FROM team t JOIN teams ON t.parent_team_id = teams.id
        )
        SELECT
            coalesce((SELECT CASE
                        WHEN bool_or(g.scope_kind = 'organization') THEN 'organization'
                        WHEN bool_or(g.scope_kind = 'project') THEN 'project'
                        WHEN bool_or(g.scope_kind = 'team') THEN 'team'
                      END FROM grants g), ''),
            (SELECT array_agg(DISTINCT v.id ORDER BY v.id) FROM (
                SELECT person AS id
                UNION
                SELECT pm.user_id FROM project_member pm
                WHERE pm.status = 'active'
                  AND (pm.project_id IN (SELECT g.project_id FROM grants g
                                         WHERE g.scope_kind = 'project')
                       OR pm.team_id IN (SELECT id FROM teams))) v),
            (SELECT coalesce(array_agg(DISTINCT g.project_id ORDER BY g.project_id), '{}')
               FROM grants g WHERE g.scope_kind = 'project'),
            (SELECT coalesce(array_agg(DISTINCT id ORDER BY id), '{}') FROM teams),
            (SELECT coalesce(array_agg(DISTINCT rp.permission ORDER BY rp.permission), '{}')
               FROM grants g JOIN role_permission rp ON rp.role_id = g.role_id)
    $$
"""


def upgrade() -> None:
    op.execute(NORMATIVE.read_text())


def downgrade() -> None:
    op.execute(_BEFORE)
