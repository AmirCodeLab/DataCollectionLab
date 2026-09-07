"""Forms, immutable published versions, and per-environment deployments.

form_version rows are never updated once published — editing produces a new
row (specs/erd-v0.1.md §4). Normative DDL: migrations/schema/001_initial.sql.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class Form(Base):
    __tablename__ = "form"
    __table_args__ = (UniqueConstraint("project_id", "form_key"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(
        Text, ForeignKey("project.id", ondelete="CASCADE"), nullable=False
    )
    form_key: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FormVersion(Base):
    """Immutable once published. Editing produces a new row, never an UPDATE."""

    __tablename__ = "form_version"
    __table_args__ = (UniqueConstraint("form_id", "version"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    form_id: Mapped[str] = mapped_column(
        Text, ForeignKey("form.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    ir: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    ir_checksum: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[str | None] = mapped_column(Text)

    # How this version got here, when it came from a spreadsheet. All NULL for
    # a version published from hand-written IR, which is the honest record of
    # not having been imported — see migrations/schema/003_form_import.sql, and
    # the CHECK there that stops a half-recorded import looking like a whole one.
    import_source_name: Mapped[str | None] = mapped_column(Text)
    import_source_sha256: Mapped[str | None] = mapped_column(Text)
    # `none_as_null`, and it is load-bearing rather than tidy. Without it
    # SQLAlchemy writes Python None into a JSONB column as the JSON value
    # `null`, which is NOT NULL in SQL — so a version that was never imported
    # failed `form_version_import_complete_check`, which asks for all five
    # columns NULL or all five set. The two nulls print identically in an error
    # message, which is what made it worth a comment.
    import_report: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    import_importer_version: Mapped[str | None] = mapped_column(Text)
    imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class FormDraft(Base):
    """Unpublished IR, one row per form. **Nothing here can become a version.**

    The columns this model does not have are the design. No `version`, no
    `ir_checksum`, no `published_at`, no status: there is no state a draft can
    be put into that means published, so promoting one is not a column write —
    it is `publish_version`, which compiles and runs `check_publishable`.

    That is deliberate rather than minimal. A table shaped like `form_version`
    sitting beside `form_version` is the shortcut the next person in a hurry
    takes, and Form IR §2.3 is about exactly that: a second route to the same
    artifact is how two callers end up disagreeing about which version a
    submission belongs to (breaks 40, 42, 61). `migrations/schema/006_form_draft.sql`
    carries the reasoning; `tests/test_form_version_has_one_writer.py` holds the
    other half.
    """

    __tablename__ = "form_draft"

    form_id: Mapped[str] = mapped_column(
        Text, ForeignKey("form.id", ondelete="CASCADE"), primary_key=True
    )
    ir: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    #: Optimistic concurrency. Two authors and one draft is last-write-wins
    #: unless something stops it, and a silently discarded afternoon is not
    #: reported as a bug — it is assumed to be a forgotten save.
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_by: Mapped[str | None] = mapped_column(Text)
    #: The author's test cases — steps and expectations the builder replays
    #: after every edit. Stored and returned, never run here; never a
    #: conformance vector (`migrations/schema/007_form_draft_test_cases.sql`).
    test_cases: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list
    )


class FormDeployment(Base):
    __tablename__ = "form_deployment"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    environment_id: Mapped[str] = mapped_column(
        Text, ForeignKey("environment.id", ondelete="CASCADE"), nullable=False
    )
    form_version_id: Mapped[str] = mapped_column(
        Text, ForeignKey("form_version.id", ondelete="RESTRICT"), nullable=False
    )
    deployed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    deployed_by: Mapped[str | None] = mapped_column(Text)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
