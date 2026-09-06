"""form_draft: somewhere to keep a form that is not published yet

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-06

migrations/schema/006_form_draft.sql is the NORMATIVE definition; this
migration transcribes it into Alembic operations so downgrade is real.
tests/test_migrations.py asserts that upgrading produces a schema identical to
executing the SQL files in name order. If they ever disagree, the SQL wins.

The columns this table does not have are the point — see the SQL file.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "form_draft",
        sa.Column("form_id", sa.Text(), primary_key=True),
        sa.Column("ir", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["form_id"], ["form.id"], ondelete="CASCADE"),
        sa.CheckConstraint("revision >= 1", name="form_draft_revision_positive"),
    )
    op.execute(
        "COMMENT ON TABLE form_draft IS "
        "'Unpublished form IR, one row per form. A draft becomes a version only "
        "through POST /forms/versions, which compiles and runs check_publishable. "
        "This table carries no version, checksum or published state on purpose: "
        "there is nothing here to promote.'"
    )


def downgrade() -> None:
    op.drop_table("form_draft")
