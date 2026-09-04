"""form import provenance

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-02

migrations/schema/003_form_import.sql is the NORMATIVE definition; this
migration transcribes it into Alembic operations so downgrade is real.
tests/test_migrations.py asserts that upgrading produces a schema identical to
executing the SQL files in name order. If they ever disagree, the SQL wins.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("form_version", sa.Column("import_source_name", sa.Text(), nullable=True))
    op.add_column("form_version", sa.Column("import_source_sha256", sa.Text(), nullable=True))
    op.add_column("form_version", sa.Column("import_report", postgresql.JSONB(), nullable=True))
    op.add_column("form_version", sa.Column("import_importer_version", sa.Text(), nullable=True))
    op.add_column(
        "form_version", sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.create_check_constraint(
        "form_version_import_complete_check",
        "form_version",
        """
        (import_source_name IS NULL
            AND import_source_sha256 IS NULL
            AND import_report IS NULL
            AND import_importer_version IS NULL
            AND imported_at IS NULL)
        OR
        (import_source_name IS NOT NULL
            AND import_source_sha256 IS NOT NULL
            AND import_report IS NOT NULL
            AND import_importer_version IS NOT NULL
            AND imported_at IS NOT NULL)
        """,
    )

    op.create_index(
        "form_version_imported_idx",
        "form_version",
        [sa.text("imported_at DESC")],
        postgresql_where=sa.text("imported_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "form_version_imported_idx",
        table_name="form_version",
        postgresql_where=sa.text("imported_at IS NOT NULL"),
    )
    op.drop_constraint("form_version_import_complete_check", "form_version", type_="check")
    op.drop_column("form_version", "imported_at")
    op.drop_column("form_version", "import_importer_version")
    op.drop_column("form_version", "import_report")
    op.drop_column("form_version", "import_source_sha256")
    op.drop_column("form_version", "import_source_name")
