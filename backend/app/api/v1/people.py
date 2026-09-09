"""People: who is in the organisation, who is waiting, who may do what.

Every route here declares the courtesy permission; every write is decided by
the policies of 010_people.sql on the asker's principal. A refusal from the
database is a 403 naming `outside_your_authority`, so a screen that offered
something the database would not permit finds out — which is the point of
having the two read the same list.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import Identity, access
from app.api.deps import get_db
from app.modules.people import service
from app.modules.people.schemas import (
    CreatePersonRequest,
    GrantRequest,
    PeopleError,
    PeopleErrorResponse,
    Person,
    PersonListResponse,
)

router = APIRouter()

REFUSALS: dict[int | str, dict[str, Any]] = {
    403: {"model": PeopleErrorResponse},
    404: {"model": PeopleErrorResponse},
    409: {"model": PeopleErrorResponse},
}

#: Any of these opens the people screen: it is where each of them is done.
PEOPLE_PERMISSIONS = (
    "user.create",
    "user.approve",
    "user.deactivate",
    "user.assign_role",
    "team.manage",
)


def _refusal(error: service.Refused) -> HTTPException:
    return HTTPException(
        status_code=error.status_code,
        detail=PeopleError(reason=error.reason, message=error.message).model_dump(),
    )


@router.get(
    "",
    response_model=PersonListResponse,
    response_model_by_alias=True,
    dependencies=[Depends(access(permission=PEOPLE_PERMISSIONS))],
)
async def list_people(session: Annotated[AsyncSession, Depends(get_db)]) -> PersonListResponse:
    """Everyone the asker may see: their scope, the people they created, and
    themself. Pending memberships first, so a queue reads as a queue."""
    async with session.begin():
        return PersonListResponse(people=await service.list_people(session))


@router.post(
    "",
    response_model=Person,
    response_model_by_alias=True,
    status_code=201,
    responses=REFUSALS,
)
async def create_person(
    request: CreatePersonRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    identity: Annotated[Identity, Depends(access(permission="user.create"))],
) -> Person:
    """Create a person with a role in a scope. Whether they are active or
    waiting for approval is the database's decision from the creator's
    permissions (§3.2, §3.3): the response's `membershipStatus` says which."""
    async with session.begin():
        try:
            return await service.create_person(session, request, identity.principal)
        except service.Refused as error:
            raise _refusal(error) from error


@router.post(
    "/{user_id}/approve",
    response_model=Person,
    response_model_by_alias=True,
    responses=REFUSALS,
)
async def approve(
    user_id: Annotated[str, Path(min_length=1, max_length=64)],
    session: Annotated[AsyncSession, Depends(get_db)],
    identity: Annotated[Identity, Depends(access(permission="user.approve"))],
) -> Person:
    async with session.begin():
        try:
            return await service.approve(session, user_id, identity.principal)
        except service.Refused as error:
            raise _refusal(error) from error


@router.post(
    "/{user_id}/deactivate",
    response_model=Person,
    response_model_by_alias=True,
    responses=REFUSALS,
)
async def deactivate(
    user_id: Annotated[str, Path(min_length=1, max_length=64)],
    session: Annotated[AsyncSession, Depends(get_db)],
    identity: Annotated[Identity, Depends(access(permission="user.deactivate"))],
) -> Person:
    """Deactivated is not deleted (§3.4): the record and its history stay."""
    async with session.begin():
        try:
            return await service.deactivate(session, user_id, identity.principal)
        except service.Refused as error:
            raise _refusal(error) from error


@router.post(
    "/{user_id}/reactivate",
    response_model=Person,
    response_model_by_alias=True,
    responses=REFUSALS,
)
async def reactivate(
    user_id: Annotated[str, Path(min_length=1, max_length=64)],
    session: Annotated[AsyncSession, Depends(get_db)],
    identity: Annotated[Identity, Depends(access(permission="user.approve"))],
) -> Person:
    async with session.begin():
        try:
            return await service.reactivate(session, user_id, identity.principal)
        except service.Refused as error:
            raise _refusal(error) from error


@router.post(
    "/{user_id}/grants",
    response_model=Person,
    response_model_by_alias=True,
    responses=REFUSALS,
)
async def grant(
    user_id: Annotated[str, Path(min_length=1, max_length=64)],
    request: GrantRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    identity: Annotated[Identity, Depends(access(permission="user.assign_role"))],
) -> Person:
    """Grant a role in a scope — inside the grantor's own authority, or the
    database refuses it."""
    async with session.begin():
        try:
            return await service.grant(session, user_id, request, identity.principal)
        except service.Refused as error:
            raise _refusal(error) from error


@router.post(
    "/{user_id}/grants/{grant_id}/revoke",
    response_model=Person,
    response_model_by_alias=True,
    responses=REFUSALS,
    dependencies=[Depends(access(permission="user.assign_role"))],
)
async def revoke(
    user_id: Annotated[str, Path(min_length=1, max_length=64)],
    grant_id: Annotated[str, Path(min_length=1, max_length=64)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Person:
    async with session.begin():
        try:
            return await service.revoke(session, user_id, grant_id)
        except service.Refused as error:
            raise _refusal(error) from error
