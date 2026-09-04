"""datasets: row hashes and form-version binding

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-03

migrations/schema/004_datasets.sql is the NORMATIVE definition; this migration
transcribes it into Alembic operations so downgrade is real.
tests/test_migrations.py asserts that upgrading produces a schema identical to
executing the SQL files in name order. If they ever disagree, the SQL wins.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "dataset_record",
        sa.Column("row_hash", sa.Text(), nullable=False, server_default=""),
    )
    op.create_index(
        "dataset_record_version_hash_idx",
        "dataset_record",
        ["dataset_version_id", "record_key", "row_hash"],
    )

    op.create_table(
        "form_version_dataset",
        sa.Column("form_version_id", sa.Text(), nullable=False),
        sa.Column("dataset_key", sa.Text(), nullable=False),
        sa.Column("dataset_version_id", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["form_version_id"], ["form_version.id"], ondelete="CASCADE"),
        # RESTRICT: a dataset version a published form still references must not
        # be deletable, or the form's choice lists stop resolving and its
        # collected answers stop being explicable.
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_version.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("form_version_id", "dataset_key"),
    )
    op.create_index(
        "form_version_dataset_version_idx",
        "form_version_dataset",
        ["dataset_version_id"],
    )


def downgrade() -> None:
    op.drop_index("form_version_dataset_version_idx", table_name="form_version_dataset")
    op.drop_table("form_version_dataset")
    op.drop_index("dataset_record_version_hash_idx", table_name="dataset_record")
    op.drop_column("dataset_record", "row_hash")
