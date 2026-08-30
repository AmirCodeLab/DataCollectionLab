"""Media files, their per-file keys, their chunks and their upload sessions.

Normative DDL: migrations/schema/001_initial.sql and 002_media.sql.

Media never travels inside the op stream (sync protocol §9). An operation
carries a `mediaId`; the file arrives separately, chunked and resumable, and
the two are paired afterwards — in either order, since a device finishes
answering long before a 3 MB photograph finishes uploading over 2G.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
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
        Index("media_submission_idx", "submission_id", "status"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    submission_id: Mapped[str] = mapped_column(
        Text, ForeignKey("submission.id", ondelete="CASCADE"), nullable=False
    )
    # Deliberately NOT a foreign key to submission_op: an op referencing media
    # is accepted before the file arrives, so the op may not exist yet.
    op_id: Mapped[str | None] = mapped_column(Text)
    device_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("device.id", ondelete="RESTRICT")
    )
    # Which field this answers. Plaintext in every security mode, and not a new
    # disclosure: an op's `path` already travels in the clear (envelope §3.1).
    field_path: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # Hash of CIPHERTEXT, never plaintext: hashing plaintext would let the
    # server confirm two submissions contain the same photograph.
    ciphertext_hash: Mapped[str | None] = mapped_column(Text)
    encrypted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # The media key's own id (envelope §6), NOT a submission content key — see
    # migrations/schema/002_media.sql for why the 001 foreign key had to go.
    # Its wrapped copies are in MediaWrappedKey.
    content_key_id: Mapped[str | None] = mapped_column(Text)
    storage_key: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class MediaWrappedKey(Base):
    """The media key wrapped to one recipient project key (envelope §6, §4.4).

    Wrapped copies only. The server has never held a private key that opens one,
    which is why handing them back to whoever asks costs nothing (§7).
    """

    __tablename__ = "media_wrapped_key"
    __table_args__ = (
        CheckConstraint(
            "octet_length(ephemeral_public) = 32 "
            "AND octet_length(nonce) = 12 "
            "AND octet_length(wrapped_key) = 48",
            name="media_wrapped_key_sizes_check",
        ),
    )

    media_id: Mapped[str] = mapped_column(
        Text, ForeignKey("media.id", ondelete="CASCADE"), primary_key=True
    )
    project_key_id: Mapped[str] = mapped_column(
        Text, ForeignKey("project_key.id", ondelete="RESTRICT"), primary_key=True
    )
    ephemeral_public: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    wrapped_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class MediaChunk(Base):
    """One 4 MiB chunk that has landed.

    Rows rather than a counter because resumption needs to know exactly which
    indexes arrived: chunks may be uploaded out of order, and re-sending from
    the first gap would re-send chunks the server already holds — on the
    connections this is designed for, that is the difference between an upload
    that finishes and one that never does.
    """

    __tablename__ = "media_chunk"
    __table_args__ = (
        CheckConstraint("chunk_index >= 0", name="media_chunk_index_check"),
        CheckConstraint("size_bytes > 0", name="media_chunk_size_check"),
    )

    media_id: Mapped[str] = mapped_column(
        Text, ForeignKey("media.id", ondelete="CASCADE"), primary_key=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    # Over the bytes AS STORED, which for encrypted media is ciphertext.
    chunk_hash: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
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
