"""datasets: rows keep the order they were published in

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-03

migrations/schema/005_dataset_order.sql is the NORMATIVE definition; this
migration transcribes it into Alembic operations so downgrade is real.
tests/test_migrations.py asserts that upgrading produces a schema identical to
executing the SQL files in name order. If they ever disagree, the SQL wins.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "dataset_record",
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "dataset_record_ordinal_idx",
        "dataset_record",
        ["dataset_version_id", "ordinal"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("dataset_record_ordinal_idx", table_name="dataset_record")
    op.drop_column("dataset_record", "ordinal")
