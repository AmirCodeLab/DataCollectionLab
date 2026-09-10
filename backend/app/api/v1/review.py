"""Review decisions and quality rules (item 6).

Two surfaces, two permissions, and neither invents a scope. A decision needs
`submission.review` and the database enforces it too — the console will check
before drawing the control, and a check in a screen is not a guarantee
(defect 26, one surface up). A rule needs `project.manage`.

There is no queue route. The queue is a filter on the submission list that
already exists, under the policy path that already scopes it (item 6, D4).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import Identity, access
from app.api.deps import get_db
from app.modules.quality import review as review_service
from app.modules.quality import rules as rules_service
from app.modules.quality.schemas import (
    QualityRuleIn,
    QualityRuleListResponse,
    QualityRuleOut,
    ReviewRefusalResponse,
    ReviewRequest,
    ReviewResponse,
    RuleRefusalResponse,
    SubmissionQualityResponse,
)
from app.modules.quality.service import RuleRefused

#: Every 422 this module declares says its own description.
#:
#: FastAPI takes an undeclared one from `http.HTTPStatus(422).phrase`, which
#: CPython **renamed in 3.13**: "Unprocessable Entity" became "Unprocessable
#: Content". `specs/openapi.json` is compared byte for byte, so the same app
#: then emits a different document on a laptop than CI checks on the pinned
#: 3.12 — a gate that goes red on a morning nobody touched the API, which is
#: exactly what break 72 was. Saying the phrase here takes the interpreter out
#: of the answer instead of pinning the answer to an interpreter.
_UNPROCESSABLE = "Unprocessable Entity"

router = APIRouter()

REVIEW = access(permission="submission.review")
VIEW = access(permission="submission.view")
MANAGE = access(permission="project.manage")


@router.post(
    "/submissions/{submission_id}/review",
    response_model=ReviewResponse,
    response_model_by_alias=True,
    responses={
        403: {"model": ReviewRefusalResponse},
        404: {"model": ReviewRefusalResponse},
        409: {"model": ReviewRefusalResponse},
        422: {"model": ReviewRefusalResponse, "description": _UNPROCESSABLE},
    },
)
async def decide(
    request: ReviewRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    identity: Annotated[Identity, Depends(REVIEW)],
    submission_id: Annotated[str, Path(min_length=1, max_length=64)],
) -> ReviewResponse:
    """Approve, reject, request a correction, or leave a comment.

    The only writer of a review state. Refusals carry a machine-readable
    `reason` beside a sentence saying what to do about it:

    - `reason_required` — a decision that returns the work needs one. Work
      handed back without a reason arrives as a repeat of the same visit.
    - `not_allowed` — the submission cannot take this decision, and the
      message says why (a draft has not been submitted; an approved
      submission has been acted on).
    - `not_found` — no such submission, or not one this person may review.
      The two are one answer on purpose.
    """
    async with session.begin():
        try:
            recorded = await review_service.decide(
                session,
                submission_id,
                reviewer_id=identity.principal.user_id,
                decision=request.decision,
                comment=request.comment,
            )
        except review_service.ReviewRefused as refusal:
            raise HTTPException(
                status_code=_STATUS[refusal.reason],
                detail={"reason": refusal.reason, "message": refusal.message},
            ) from refusal
    return ReviewResponse(
        review_id=recorded.review_id,
        status=recorded.status,
        returns_work=recorded.returns_work,
    )


_STATUS = {
    "not_found": 404,
    "reason_required": 422,
    "not_allowed": 409,
    "unknown_decision": 422,
}


@router.get(
    "/submissions/{submission_id}/quality",
    response_model=SubmissionQualityResponse,
    response_model_by_alias=True,
)
async def submission_quality(
    session: Annotated[AsyncSession, Depends(get_db)],
    identity: Annotated[Identity, Depends(VIEW)],
    submission_id: Annotated[str, Path(min_length=1, max_length=64)],
) -> SubmissionQualityResponse:
    """What the rules said about one submission, and what has been decided.

    `flags` and `unevaluated` are separate lists rather than one list with a
    field to read, because a reviewer who skims must not be able to read
    "nothing flagged" as "checked and clean" (item 6, D3).
    """
    async with session.begin():
        return await rules_service.submission_quality(session, submission_id)


@router.get(
    "/quality/rules",
    response_model=QualityRuleListResponse,
    response_model_by_alias=True,
)
async def list_rules(
    session: Annotated[AsyncSession, Depends(get_db)],
    identity: Annotated[Identity, Depends(VIEW)],
    project_id: Annotated[str, Query(alias="projectId", min_length=1, max_length=64)],
) -> QualityRuleListResponse:
    """A project's rules. Readable by anyone who may see its work, because a
    reviewer needs to know what was checked."""
    async with session.begin():
        return await rules_service.list_rules(session, project_id)


@router.post(
    "/quality/rules",
    response_model=QualityRuleOut,
    response_model_by_alias=True,
    responses={422: {"model": RuleRefusalResponse, "description": _UNPROCESSABLE}},
)
async def create_rule(
    request: QualityRuleIn,
    session: Annotated[AsyncSession, Depends(get_db)],
    identity: Annotated[Identity, Depends(MANAGE)],
    project_id: Annotated[str, Query(alias="projectId", min_length=1, max_length=64)],
) -> QualityRuleOut:
    """Add a rule, compiling its expression first.

    A rule that cannot be evaluated is refused here, with the compiler's own
    message. Storing it would turn one author's mistake into a `not_evaluated`
    row on every submission for as long as it stayed enabled.
    """
    async with session.begin():
        try:
            return await rules_service.create_rule(session, project_id, request)
        except RuleRefused as refusal:
            raise HTTPException(
                status_code=422,
                detail={"reason": refusal.reason, "message": refusal.message},
            ) from refusal


@router.patch(
    "/quality/rules/{rule_id}",
    response_model=QualityRuleOut,
    response_model_by_alias=True,
    responses={
        404: {"model": RuleRefusalResponse},
        422: {"model": RuleRefusalResponse, "description": _UNPROCESSABLE},
    },
)
async def update_rule(
    request: QualityRuleIn,
    session: Annotated[AsyncSession, Depends(get_db)],
    identity: Annotated[Identity, Depends(MANAGE)],
    rule_id: Annotated[str, Path(min_length=1, max_length=64)],
) -> QualityRuleOut:
    """Edit a rule. Flags already raised keep the definition they were raised
    under — a decision made last week was made under last week's rule, and
    this cannot reach back and change what it says."""
    async with session.begin():
        try:
            return await rules_service.update_rule(session, rule_id, request)
        except RuleRefused as refusal:
            raise HTTPException(
                status_code=404 if refusal.reason == "not_found" else 422,
                detail={"reason": refusal.reason, "message": refusal.message},
            ) from refusal
