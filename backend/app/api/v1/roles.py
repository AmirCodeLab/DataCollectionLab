"""Roles: a set of permissions plus a scope, never a hard-coded branch (§3.5).

The permissions a screen may offer are the contract's `PERMISSIONS`; the ones
it may put on a role are the ones the editor holds, and the database says so
too (010_people.sql §4): a role editable in the UI is a role the policy reads.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import Identity, access
from app.api.deps import get_db
from app.modules.people import service
from app.modules.people.schemas import (
    CreateRoleRequest,
    PeopleError,
    PeopleErrorResponse,
    Role,
    RoleListResponse,
    RolePermissionsRequest,
)

router = APIRouter()

REFUSALS: dict[int | str, dict[str, Any]] = {
    403: {"model": PeopleErrorResponse},
    404: {"model": PeopleErrorResponse},
    409: {"model": PeopleErrorResponse},
}


def _refusal(error: service.Refused) -> HTTPException:
    return HTTPException(
        status_code=error.status_code,
        detail=PeopleError(reason=error.reason, message=error.message).model_dump(),
    )


@router.get("", response_model=RoleListResponse, response_model_by_alias=True)
async def list_roles(
    session: Annotated[AsyncSession, Depends(get_db)],
    identity: Annotated[
        Identity,
        Depends(access(permission=("user.create", "user.assign_role", "user.approve"))),
    ],
) -> RoleListResponse:
    """Every role, with whether the asker may grant it."""
    async with session.begin():
        return RoleListResponse(roles=await service.list_roles(session, identity.principal))


@router.post(
    "",
    response_model=Role,
    response_model_by_alias=True,
    status_code=201,
    responses=REFUSALS,
)
async def create_role(
    request: CreateRoleRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    identity: Annotated[Identity, Depends(access(permission="user.assign_role"))],
) -> Role:
    """A custom role. It may carry only permissions its creator holds."""
    async with session.begin():
        try:
            return await service.create_role(session, request, identity.principal)
        except service.Refused as error:
            raise _refusal(error) from error


@router.put(
    "/{role_id}/permissions",
    response_model=Role,
    response_model_by_alias=True,
    responses=REFUSALS,
)
async def set_permissions(
    role_id: Annotated[str, Path(min_length=1, max_length=64)],
    request: RolePermissionsRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    identity: Annotated[Identity, Depends(access(permission="user.assign_role"))],
) -> Role:
    """Replace a custom role's permissions. The standard roles are not editable."""
    async with session.begin():
        try:
            return await service.set_role_permissions(
                session, role_id, request.permissions, identity.principal
            )
        except service.Refused as error:
            raise _refusal(error) from error
