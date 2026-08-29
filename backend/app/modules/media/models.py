"""Media files and resumable upload sessions.

Normative DDL: migrations/schema/001_initial.sql.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class Media(Base):
    __tablename__ = "media"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'uploading', 'complete', 'failed')",
            name="media_status_check",
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    submission_id: Mapped[str] = mapped_column(
        Text, ForeignKey("submission.id", ondelete="CASCADE"), nullable=False
    )
    # Deliberately NOT a foreign key to submission_op: an op referencing media
    # is accepted before the file arrives, so the op may not exist yet.
    op_id: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # Hash of CIPHERTEXT, never plaintext: hashing plaintext would let the
    # server confirm two submissions contain the same photograph.
    ciphertext_hash: Mapped[str | None] = mapped_column(Text)
    encrypted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    content_key_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("submission_content_key.id", ondelete="RESTRICT")
    )
    storage_key: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class MediaUploadSession(Base):
    __tablename__ = "media_upload_session"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    media_id: Mapped[str] = mapped_column(
        Text, ForeignKey("media.id", ondelete="CASCADE"), nullable=False
    )
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False)
    received_chunks: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
