"""Quality rules, flags and the review trail.

Normative DDL: migrations/schema/001_initial.sql.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class QualityRule(Base):
    __tablename__ = "quality_rule"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('info', 'warning', 'error')",
            name="quality_rule_severity_check",
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(
        Text, ForeignKey("project.id", ondelete="CASCADE"), nullable=False
    )
    form_id: Mapped[str | None] = mapped_column(Text, ForeignKey("form.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'warning'"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class QualityFlag(Base):
    __tablename__ = "quality_flag"
    __table_args__ = (
        Index(
            "quality_flag_open_idx",
            "submission_id",
            postgresql_where=text("resolved_at IS NULL AND outcome = 'violation'"),
        ),
        Index(
            "quality_flag_unevaluated_idx",
            "submission_id",
            postgresql_where=text("resolved_at IS NULL AND outcome = 'not_evaluated'"),
        ),
        CheckConstraint(
            "outcome IN ('violation', 'not_evaluated')",
            name="quality_flag_outcome_check",
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    submission_id: Mapped[str] = mapped_column(
        Text, ForeignKey("submission.id", ondelete="CASCADE"), nullable=False
    )
    rule_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("quality_rule.id", ondelete="SET NULL")
    )
    path: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    #: 'violation' — the rule ran and did not hold. 'not_evaluated' — it could
    #: not run at all, because the server holds ciphertext and no key, or the
    #: expression names a path the form does not declare. Never a pass (016).
    outcome: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'violation'")
    )
    #: The rule as it was when this flag was raised. `rule_id` is
    #: ON DELETE SET NULL, which loses the answer at exactly the moment it
    #: matters, so a decision made under a rule keeps the rule it was made
    #: under even after the rule is edited or deleted.
    rule_name: Mapped[str | None] = mapped_column(Text)
    rule_definition: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[str | None] = mapped_column(Text)


class Review(Base):
    __tablename__ = "review"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('approved', 'rejected', 'correction_required', 'comment')",
            name="review_decision_check",
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    submission_id: Mapped[str] = mapped_column(
        Text, ForeignKey("submission.id", ondelete="CASCADE"), nullable=False
    )
    reviewer_id: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
