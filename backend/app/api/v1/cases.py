"""Cases and assignment (item 2, analysis §7).

The list is the database's answer on the asker's principal — a supervisor's
page is their team's cases, a manager's the whole sample, an enumerator's
their own — and the two writes go through `dcp_assign_case` with the same
policies applying inside. A refusal from the database is a 403 naming
`outside_your_authority`, item 1's shape.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import access
from app.api.deps import get_db
from app.modules.cases import service
from app.modules.cases.schemas import (
    AssignRequest,
    BulkAssignRequest,
    BulkAssignResponse,
    CaseError,
    CaseErrorResponse,
    CaseListResponse,
)

router = APIRouter()

REFUSALS: dict[int | str, dict[str, Any]] = {
    400: {"model": CaseErrorResponse},
    403: {"model": CaseErrorResponse},
    404: {"model": CaseErrorResponse},
}


def _refusal(error: service.Refused) -> HTTPException:
    return HTTPException(
        status_code=error.status_code,
        detail=CaseError(reason=error.reason, message=error.message).model_dump(),
    )


@router.get(
    "",
    response_model=CaseListResponse,
    response_model_by_alias=True,
    dependencies=[
        Depends(access(permission=("sample.assign", "sample.upload", "submission.view")))
    ],
)
async def list_cases(
    session: Annotated[AsyncSession, Depends(get_db)],
    project_id: Annotated[str, Query(alias="projectId", min_length=1, max_length=64)],
) -> CaseListResponse:
    """The project's cases the asker may see, with the live holder at each
    level and the sample row behind each."""
    async with session.begin():
        return CaseListResponse(cases=await service.list_cases(session, project_id))


@router.post(
    "/{case_id}/assign",
    response_model=CaseListResponse,
    response_model_by_alias=True,
    responses=REFUSALS,
    dependencies=[Depends(access(permission="sample.assign"))],
)
async def assign_case(
    case_id: Annotated[str, Path(min_length=1, max_length=64)],
    request: AssignRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    project_id: Annotated[str, Query(alias="projectId", min_length=1, max_length=64)],
) -> CaseListResponse:
    """Assign one case to a team or to a person. Release-and-write in one
    statement; the previous holder's view moves with it."""
    async with session.begin():
        try:
            await service.assign(
                session, case_id, team_id=request.team_id, user_id=request.user_id
            )
        except service.Refused as error:
            raise _refusal(error) from error
        return CaseListResponse(cases=await service.list_cases(session, project_id))


@router.post(
    "/assign",
    response_model=BulkAssignResponse,
    responses=REFUSALS,
    dependencies=[Depends(access(permission="sample.assign"))],
)
async def assign_cases(
    request: BulkAssignRequest, session: Annotated[AsyncSession, Depends(get_db)]
) -> BulkAssignResponse:
    """The split: many cases to one team or one person, all or nothing."""
    async with session.begin():
        try:
            assigned = await service.assign_many(
                session, request.case_ids, team_id=request.team_id, user_id=request.user_id
            )
        except service.Refused as error:
            raise _refusal(error) from error
    return BulkAssignResponse(assigned=assigned)
