"""Wire types for review and quality rules (item 6)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

type Decision = Literal["approved", "rejected", "correction_required", "comment"]
type Outcome = Literal["violation", "not_evaluated"]
type ReviewPolicy = Literal["flagged", "all"]
#: `quality_rule_severity_check` in 001, named once so the document does too.
type Severity = Literal["info", "warning", "error"]
#: Why a decision was refused, and why a rule was.
type ReviewRefusalReason = Literal[
    "unknown_decision", "not_found", "reason_required", "not_allowed"
]
type RuleRefusalReason = Literal["invalid_expression", "unknown_form", "not_found"]


class ReviewRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    decision: Decision
    #: Required for a decision that returns the work. A rejection with no
    #: reason arrives at the enumerator as a repeat of the same visit.
    comment: str | None = Field(default=None, max_length=4000)


class ReviewResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    review_id: str = Field(serialization_alias="reviewId")
    status: str
    #: True when this decision handed the submission back to its enumerator.
    #: The device learns from the pull's returned-work statement, not from
    #: this response.
    returns_work: bool = Field(serialization_alias="returnsWork")


class ReviewRefusal(BaseModel):
    """A refusal a client can act on, in the shape items 2 and 4 use."""

    reason: ReviewRefusalReason
    message: str


class ReviewRefusalResponse(BaseModel):
    detail: ReviewRefusal


class ReviewEntry(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    decision: Decision
    comment: str | None
    reviewer: str | None
    created_at: datetime = Field(serialization_alias="createdAt")


class FlagView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    #: Null when the rule has since been deleted. `ruleName` and
    #: `ruleDefinition` are the rule **as it was when this flag was raised**,
    #: so a rule edited afterwards cannot rewrite the history of a decision
    #: made under it.
    rule_id: str | None = Field(serialization_alias="ruleId")
    rule_name: str | None = Field(serialization_alias="ruleName")
    severity: str
    #: `violation` — the rule ran and did not hold. `not_evaluated` — it could
    #: not run at all, which is not a pass and is never counted as one.
    outcome: Outcome
    detail: dict[str, Any]
    path: str | None
    created_at: datetime = Field(serialization_alias="createdAt")
    resolved_at: datetime | None = Field(serialization_alias="resolvedAt")


class SubmissionQualityResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    #: Open violations, in severity order.
    flags: list[FlagView]
    #: Rules that could not be evaluated. Separate from `flags` because a
    #: reviewer must not read "nothing flagged" as "checked and clean".
    unevaluated: list[FlagView]
    reviews: list[ReviewEntry]


class QualityRuleIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1, max_length=200)
    #: An IR expression. Compiled before it is stored, so a rule that cannot
    #: be evaluated is refused at the author rather than discovered as
    #: "not evaluated" on every submission afterwards.
    definition: dict[str, Any]
    severity: Severity = "warning"
    enabled: bool = True
    #: Null applies the rule to every form in the project.
    form_id: str | None = Field(default=None, alias="formId")


class QualityRuleOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    definition: dict[str, Any]
    severity: str
    enabled: bool
    form_id: str | None = Field(serialization_alias="formId")
    created_at: datetime = Field(serialization_alias="createdAt")


class QualityRuleListResponse(BaseModel):
    rules: list[QualityRuleOut]


class RuleRefusal(BaseModel):
    reason: RuleRefusalReason
    message: str


class RuleRefusalResponse(BaseModel):
    detail: RuleRefusal
