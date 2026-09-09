"""The columns a sample's composite key was composed from

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-09

migrations/schema/013_dataset_key_columns.sql is the NORMATIVE definition.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("dataset", sa.Column("key_columns", postgresql.ARRAY(sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("dataset", "key_columns")
