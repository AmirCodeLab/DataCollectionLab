"""Login, logout, and who am I (proposal §3, §9).

The session is a cookie and a row. Nothing readable is returned to the page:
`Me` names the person and what they may do, and the token travels only in
the `Set-Cookie` header, HttpOnly.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import (
    Identity,
    access,
    clear_session_cookies,
    get_db,
    organization_slug,
    public,
    session_ttl,
    set_session_cookies,
)
from app.infrastructure.database import OrganizationUnknown, rescope_to_organization
from app.modules.auth import service
from app.modules.auth.schemas import (
    LoginError,
    LoginErrorResponse,
    LoginRequest,
    LogoutResponse,
    Me,
)

router = APIRouter()


def _me(identity: Identity, org_slug: str) -> Me:
    return Me(
        user_id=identity.user_id,
        username=identity.username,
        display_name=identity.display_name,
        organization_id=identity.principal.org_id,
        organization_slug=org_slug,
        session_kind=identity.kind,
        device_id=identity.device_id,
        scope_kind=identity.principal.scope_kind or "none",
        permissions=sorted(identity.permissions),
        project_ids=list(identity.principal.project_ids),
        team_ids=list(identity.principal.team_ids),
        expires_at=identity.expires_at.isoformat(),
    )


@router.post(
    "/login",
    response_model=Me,
    response_model_by_alias=True,
    responses={
        400: {"model": LoginErrorResponse},
        401: {"model": LoginErrorResponse},
        403: {"model": LoginErrorResponse},
    },
    dependencies=[
        Depends(public("the login itself; the organisation is resolved before a user is read"))
    ],
)
async def login(
    request: LoginRequest,
    response: Response,
    http: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Me:
    """Sign in, for the console or for a handset on its device.

    The organisation is resolved first — from the request's `organization`,
    else the deployment's configured one — and only then is the person looked
    up under its policy (ERD §1). Whether the person may hold a session is
    the session policy's decision: a `pending_approval` or `deactivated`
    membership is refused by the database, and the reason is read afterwards
    to name it here.
    """
    slug = request.organization or organization_slug(http)
    try:
        # Resolved for real: the request's session is on the slug the cookie
        # or the setting named, which may be nothing; the login names its own.
        await rescope_to_organization(session, slug)
        async with session.begin():
            login = await service.login(
                session,
                username=request.username,
                password=request.password,
                kind=request.kind,
                device_id=request.device_id,
                org_slug=slug,
                ttl=session_ttl(),
            )
    except OrganizationUnknown as error:
        # The same answer as a wrong password: which organisations exist is
        # not something a login form gets to enumerate.
        raise HTTPException(
            status_code=401,
            detail=LoginError(
                reason="invalid_credentials", message="Wrong username or password."
            ).model_dump(),
        ) from error
    except service.LoginRefused as refusal:
        raise HTTPException(
            status_code=refusal.status_code,
            detail=LoginError(reason=refusal.reason, message=refusal.message).model_dump(),
        ) from refusal
    set_session_cookies(response, login.token, slug)
    return _me(login.identity, slug)


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    response: Response,
    http: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    identity: Annotated[Identity, Depends(access(signed_in=True))],
) -> LogoutResponse:
    """Revoke this session. The row is the state, so this is a row update;
    the cookies are cleared as a courtesy to the browser."""
    async with session.begin():
        await service.logout(session, identity.session_id)
    clear_session_cookies(response)
    return LogoutResponse(status="logged_out")


@router.get("/me", response_model=Me, response_model_by_alias=True)
async def me(
    http: Request, identity: Annotated[Identity, Depends(access(signed_in=True))]
) -> Me:
    """Who this session is and what it may do — what a console reads on load
    to decide which screens to offer."""
    return _me(identity, organization_slug(http))

