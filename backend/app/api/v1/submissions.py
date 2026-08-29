"""Submission read endpoints — the console's view of the op log.

Public API, same as every other route here: the console has no private
endpoints (docs/project-conventions.md rule 9). Read-only; a submission changes only by ops
arriving through /sync/push.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.modules.submissions import service
from app.modules.submissions.schemas import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    SubmissionDetail,
    SubmissionListResponse,
    SubmissionStatus,
)

router = APIRouter()


@router.get("", response_model=SubmissionListResponse, response_model_by_alias=True)
async def list_submissions(
    session: Annotated[AsyncSession, Depends(get_db)],
    form_id: Annotated[str | None, Query(alias="formId")] = None,
    status: Annotated[SubmissionStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SubmissionListResponse:
    """One page of submissions, newest arrival first.

    `formId` is the wire form key an op carries, not the form row id, so the
    same value filters here and identifies a form in a pushed op. An unknown
    `status` is a 422 rather than an empty page — a typo should say so.
    """
    async with session.begin():
        return await service.list_submissions(
            session, form_id=form_id, status=status, limit=limit, offset=offset
        )


@router.get("/{submission_id}", response_model=SubmissionDetail, response_model_by_alias=True)
async def get_submission(
    session: Annotated[AsyncSession, Depends(get_db)],
    submission_id: Annotated[str, Path(min_length=1, max_length=64)],
) -> SubmissionDetail:
    """Folded current state plus the raw op log in (counter, deviceId) order."""
    async with session.begin():
        detail = await service.get_submission(session, submission_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="submission not found")
    return detail
