"""form_draft.test_cases: an author's test cases live with the draft

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-07

migrations/schema/007_form_draft_test_cases.sql is the NORMATIVE definition;
this migration transcribes it into Alembic operations so downgrade is real.
tests/test_migrations.py asserts that upgrading produces a schema identical to
executing the SQL files in name order. If they ever disagree, the SQL wins.

A test case is not a conformance vector and must not be stored as one — the
SQL file says why at length.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "form_draft",
        sa.Column(
            "test_cases",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.execute(
        "COMMENT ON COLUMN form_draft.test_cases IS "
        "'The author''s test cases for this draft: steps and expectations, replayed "
        "in the builder after every edit. Owned by the author, about this form, "
        "expected to change with it. Never a conformance vector; never stored as one.'"
    )


def downgrade() -> None:
    op.drop_column("form_draft", "test_cases")
