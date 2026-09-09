"""Teams: a project's teams and who is in them (pilot scope §3.1)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import Identity, access
from app.api.deps import get_db
from app.modules.people import service
from app.modules.people.schemas import (
    AddTeamMemberRequest,
    CreateTeamRequest,
    PeopleError,
    PeopleErrorResponse,
    Team,
    TeamListResponse,
)

router = APIRouter()

REFUSALS: dict[int | str, dict[str, Any]] = {
    403: {"model": PeopleErrorResponse},
    404: {"model": PeopleErrorResponse},
}


def _refusal(error: service.Refused) -> HTTPException:
    return HTTPException(
        status_code=error.status_code,
        detail=PeopleError(reason=error.reason, message=error.message).model_dump(),
    )


@router.get(
    "",
    response_model=TeamListResponse,
    response_model_by_alias=True,
    dependencies=[
        Depends(access(permission=("team.manage", "user.create", "sample.assign", "user.approve")))
    ],
)
async def list_teams(
    session: Annotated[AsyncSession, Depends(get_db)],
    project_id: Annotated[str, Query(alias="projectId", min_length=1, max_length=64)],
) -> TeamListResponse:
    async with session.begin():
        return TeamListResponse(teams=await service.list_teams(session, project_id))


@router.post(
    "",
    response_model=Team,
    response_model_by_alias=True,
    status_code=201,
    responses=REFUSALS,
    dependencies=[Depends(access(permission="team.manage"))],
)
async def create_team(
    request: CreateTeamRequest, session: Annotated[AsyncSession, Depends(get_db)]
) -> Team:
    async with session.begin():
        try:
            return await service.create_team(session, request)
        except service.Refused as error:
            raise _refusal(error) from error


@router.post(
    "/{team_id}/members",
    response_model=Team,
    response_model_by_alias=True,
    responses=REFUSALS,
)
async def add_member(
    team_id: Annotated[str, Path(min_length=1, max_length=64)],
    request: AddTeamMemberRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    identity: Annotated[Identity, Depends(access(permission=("team.manage", "user.create")))],
) -> Team:
    """An existing person, selected rather than created: no approval is
    involved in adding a member to a team (§3.2)."""
    async with session.begin():
        try:
            return await service.add_team_member(
                session, team_id, request.user_id, identity.principal
            )
        except service.Refused as error:
            raise _refusal(error) from error


@router.post(
    "/{team_id}/members/{user_id}/remove",
    response_model=Team,
    response_model_by_alias=True,
    responses=REFUSALS,
    dependencies=[Depends(access(permission=("team.manage", "user.create")))],
)
async def remove_member(
    team_id: Annotated[str, Path(min_length=1, max_length=64)],
    user_id: Annotated[str, Path(min_length=1, max_length=64)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Team:
    async with session.begin():
        try:
            return await service.remove_team_member(session, team_id, user_id)
        except service.Refused as error:
            raise _refusal(error) from error
