"""Entities, relationships and versioned datasets.

Normative DDL: migrations/schema/001_initial.sql.
"""

from datetime import datetime
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class EntityType(Base):
    __tablename__ = "entity_type"
    __table_args__ = (UniqueConstraint("project_id", "type_key"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(
        Text, ForeignKey("project.id", ondelete="CASCADE"), nullable=False
    )
    type_key: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    schema_def: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Entity(Base):
    __tablename__ = "entity"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    entity_type_id: Mapped[str] = mapped_column(
        Text, ForeignKey("entity_type.id", ondelete="CASCADE"), nullable=False
    )
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    location: Mapped[Any | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EntityRelationship(Base):
    __tablename__ = "entity_relationship"
    __table_args__ = (UniqueConstraint("from_entity_id", "to_entity_id", "relation_kind"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    from_entity_id: Mapped[str] = mapped_column(
        Text, ForeignKey("entity.id", ondelete="CASCADE"), nullable=False
    )
    to_entity_id: Mapped[str] = mapped_column(
        Text, ForeignKey("entity.id", ondelete="CASCADE"), nullable=False
    )
    relation_kind: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Dataset(Base):
    __tablename__ = "dataset"
    __table_args__ = (UniqueConstraint("project_id", "dataset_key"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(
        Text, ForeignKey("project.id", ondelete="CASCADE"), nullable=False
    )
    dataset_key: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class DatasetVersion(Base):
    __tablename__ = "dataset_version"
    __table_args__ = (UniqueConstraint("dataset_id", "version"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    dataset_id: Mapped[str] = mapped_column(
        Text, ForeignKey("dataset.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    checksum: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class DatasetRecord(Base):
    __tablename__ = "dataset_record"
    __table_args__ = (UniqueConstraint("dataset_version_id", "record_key"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    dataset_version_id: Mapped[str] = mapped_column(
        Text, ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False
    )
    record_key: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # SHA-256 over canonical_json(data) — the encryption envelope's
    # serialisation (§5.1), not a second one invented here, because two servers
    # must produce identical bytes for the same row or every delta is spurious.
    #
    # Over the WHOLE row on purpose. It answers "did anything about this row
    # change", cheaply and version-independently. It does not decide whether a
    # device is sent anything: an edit to a column no form references must not
    # cost a 50k-row list a transfer, and that is settled by comparing the
    # projection onto the columns the device's forms actually use.
    row_hash: Mapped[str] = mapped_column(Text, nullable=False, server_default=text(""))
    # The row's position in the file it was published from, 0-based.
    #
    # The order a list is offered in is the order its author put it in, and
    # `id` cannot carry that: a ULID generated in a loop shares its timestamp
    # and randomises its tail, so paging by id is stable and *scrambled* — an
    # enumerator scrolling 38,000 villages in an order nobody chose.
    #
    # It is also the paging cursor, which is a cheaper and more obvious thing to
    # resume from than a ULID: an integer, within a version that cannot change.
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))


class FormVersionDataset(Base):
    """Which dataset version a form version was published against.

    The IR names a dataset by key — `"dataset": "districts"` (Form IR §3) — and a
    key is not a version. Resolving it at read time would let a draft opened
    against form v1 see whatever `districts` happens to be newest, which is the
    same mistake as validating a v1 answer against v2's choice list: answers
    given against a list that no longer exists, with nothing saying so.

    So the key is resolved once, at publish, and pinned. A form version is
    immutable and so is its view of its data.
    """

    __tablename__ = "form_version_dataset"

    form_version_id: Mapped[str] = mapped_column(
        Text, ForeignKey("form_version.id", ondelete="CASCADE"), primary_key=True
    )
    dataset_key: Mapped[str] = mapped_column(Text, primary_key=True)
    # RESTRICT, not CASCADE: a dataset version a published form still references
    # must not be deletable, or the form's choice lists stop resolving and its
    # collected answers stop being explicable.
    dataset_version_id: Mapped[str] = mapped_column(
        Text, ForeignKey("dataset_version.id", ondelete="RESTRICT"), nullable=False
    )
