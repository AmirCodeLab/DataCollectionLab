"""media capture

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-30

migrations/schema/002_media.sql is the NORMATIVE definition; this migration
transcribes it into Alembic operations so downgrade is real.
tests/test_migrations.py asserts that upgrading produces a schema identical to
executing the SQL files in name order. If they ever disagree, the SQL wins.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("media", sa.Column("device_id", sa.Text(), nullable=True))
    op.add_column("media", sa.Column("field_path", sa.Text(), nullable=True))
    op.create_foreign_key(
        "media_device_id_fkey", "media", "device", ["device_id"], ["id"], ondelete="RESTRICT"
    )

    # Envelope §6 gives each media file its own content key, which cannot live
    # in submission_content_key: that table is UNIQUE (submission_id, device_id)
    # — one operation key per device per submission — and one device captures
    # several files into one submission. The column stays as the media key's own
    # id; its wraps move to media_wrapped_key.
    op.drop_constraint("media_content_key_id_fkey", "media", type_="foreignkey")

    op.create_table(
        "media_wrapped_key",
        sa.Column("media_id", sa.Text(), nullable=False),
        sa.Column("project_key_id", sa.Text(), nullable=False),
        sa.Column("ephemeral_public", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("wrapped_key", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "octet_length(ephemeral_public) = 32 "
            "AND octet_length(nonce) = 12 "
            "AND octet_length(wrapped_key) = 48",
            name="media_wrapped_key_sizes_check",
        ),
        sa.ForeignKeyConstraint(["media_id"], ["media.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_key_id"], ["project_key.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("media_id", "project_key_id"),
    )

    op.create_table(
        "media_chunk",
        sa.Column("media_id", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("chunk_hash", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("chunk_index >= 0", name="media_chunk_index_check"),
        sa.CheckConstraint("size_bytes > 0", name="media_chunk_size_check"),
        sa.ForeignKeyConstraint(["media_id"], ["media.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("media_id", "chunk_index"),
    )

    op.create_index("media_submission_idx", "media", ["submission_id", "status"])

    op.add_column(
        "project",
        sa.Column(
            "media_image_max_dimension",
            sa.Integer(),
            server_default=sa.text("1600"),
            nullable=False,
        ),
    )
    op.add_column(
        "project",
        sa.Column(
            "media_image_quality", sa.Integer(), server_default=sa.text("80"), nullable=False
        ),
    )
    op.add_column(
        "project",
        sa.Column(
            "media_gps_max_accuracy_m",
            sa.Integer(),
            server_default=sa.text("50"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "project_media_image_max_dimension_check",
        "project",
        "media_image_max_dimension BETWEEN 320 AND 8192",
    )
    op.create_check_constraint(
        "project_media_image_quality_check", "project", "media_image_quality BETWEEN 1 AND 100"
    )
    op.create_check_constraint(
        "project_media_gps_max_accuracy_check",
        "project",
        "media_gps_max_accuracy_m BETWEEN 1 AND 10000",
    )


def downgrade() -> None:
    op.drop_constraint("project_media_gps_max_accuracy_check", "project", type_="check")
    op.drop_constraint("project_media_image_quality_check", "project", type_="check")
    op.drop_constraint("project_media_image_max_dimension_check", "project", type_="check")
    op.drop_column("project", "media_gps_max_accuracy_m")
    op.drop_column("project", "media_image_quality")
    op.drop_column("project", "media_image_max_dimension")

    op.drop_index("media_submission_idx", table_name="media")
    op.drop_table("media_chunk")
    op.drop_table("media_wrapped_key")

    op.create_foreign_key(
        "media_content_key_id_fkey",
        "media",
        "submission_content_key",
        ["content_key_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint("media_device_id_fkey", "media", type_="foreignkey")
    op.drop_column("media", "field_path")
    op.drop_column("media", "device_id")
