"""Who is asking, and whether the route lets them.

Two layers, deliberately unequal (proposal §5):

- **The guarantee is the database.** `get_db` scopes every request's session
  to one organisation before anything is read; `current_identity` resolves
  the cookie inside that scope and hands the connection the person's
  principal — `scope_kind` and `visible_user_ids` — which the policies read
  on every query. A supervisor reaching another team's rows is refused by
  `submission`'s policy whether the query came from a screen, an export, a
  report or a sync endpoint, because none of those has a way to ask without
  a principal.
- **The courtesy is the route.** `access(...)` refuses a request before the
  handler runs — 401 with no session, 403 without the permission or the
  right kind of session — so a screen gets an answer it can show. Every
  route declares exactly one of `access(...)` or `public(...)`, and
  `tests/test_every_route_declares_access.py` fails on one that declares
  neither, naming it. That is what closes "the one place nobody thinks of as
  a screen": a route cannot exist without saying who may call it.

The organisation is resolved before the session is read (ERD §1): from the
`dcp_org` cookie the login set, else from ORGANIZATION_SLUG — the scaffold
`app.core.config` says is temporary and what replaces it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.infrastructure.database import session_for_organization
from app.modules.auth import service as auth_service
from app.modules.auth.service import Identity

SESSION_COOKIE = "dcp_session"
ORG_COOKIE = "dcp_org"
COOKIE_PATH = "/api"


def organization_slug(request: Request) -> str:
    """The organisation this request is for: the cookie the login set, else
    the deployment's configured one."""
    return request.cookies.get(ORG_COOKIE) or get_settings().organization_slug


def session_ttl() -> timedelta:
    return timedelta(seconds=get_settings().session_ttl_seconds)


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """A session scoped to the request's organisation and nobody in it.

    What an unauthenticated request gets: the organisation's root rows are
    visible (a login has to find the person), submissions are not (the scope
    policy reads a principal nobody has), and nothing can be written that a
    policy would refuse. `current_identity` replaces the principal with the
    person's once the cookie resolves.
    """
    async with session_for_organization(organization_slug(request)) as session:
        yield session


def set_session_cookies(response: Response, token: str, org_slug: str) -> None:
    """HttpOnly, SameSite=Strict, scoped to the API: no script reads it, no
    cross-site request carries it (proposal §3.2). `Secure` outside
    development, where the console is served over plain http on localhost."""
    settings = get_settings()
    secure = settings.environment != "development"
    max_age = settings.session_ttl_seconds
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        path=COOKIE_PATH,
        httponly=True,
        secure=secure,
        samesite="strict",
    )
    response.set_cookie(
        ORG_COOKIE,
        org_slug,
        max_age=max_age,
        path=COOKIE_PATH,
        httponly=True,
        secure=secure,
        samesite="strict",
    )


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path=COOKIE_PATH)
    response.delete_cookie(ORG_COOKIE, path=COOKIE_PATH)


async def current_identity(
    request: Request, session: Annotated[AsyncSession, Depends(get_db)]
) -> Identity | None:
    """The session the cookie names, resolved under the organisation's
    policies, and — the part that matters — the connection's principal
    replaced with the person's for the rest of the request."""
    token = request.cookies.get(SESSION_COOKIE)
    if token is None:
        return None
    async with session.begin():
        identity = await auth_service.resolve(
            session, token, org_slug=organization_slug(request), ttl=session_ttl()
        )
    if identity is None:
        return None
    # The resolving transaction has ended; the next one this session begins
    # declares the person, not the organisation (database._declare_principal).
    session.info["principal"] = identity.principal
    return identity


Guard = Callable[..., Awaitable[Identity | None]]


def _forbidden(reason: str, message: str) -> HTTPException:
    return HTTPException(status_code=403, detail={"reason": reason, "message": message})


def access(
    *,
    permission: str | tuple[str, ...] | None = None,
    app: bool = False,
    signed_in: bool = False,
) -> Guard:
    """The route's declaration of who may call it.

    - `permission="x"` or `permission=("x", "y")`: a console session holding
      one of them.
    - `app=True`: an app session (a handset that logged in on its device).
    - `signed_in=True`: any session at all.

    Combine them and any one admits — `access(app=True, permission="form.edit")`
    is a route both a handset and a form author read. A route must declare
    something; `access()` with nothing is a mistake, and refused here.
    """
    if permission is None and not app and not signed_in:
        raise ValueError("access() must name a permission, app=True or signed_in=True")
    permissions = (permission,) if isinstance(permission, str) else permission

    async def guard(identity: Annotated[Identity | None, Depends(current_identity)]) -> Identity:
        if identity is None:
            raise HTTPException(
                status_code=401,
                detail={"reason": "not_signed_in", "message": "Sign in to continue."},
            )
        if signed_in:
            return identity
        if app and identity.kind == "app":
            return identity
        if permissions and identity.kind == "console":
            if any(p in identity.permissions for p in permissions):
                return identity
            raise _forbidden(
                "permission_denied",
                f"This needs {' or '.join(permissions)}, which this account does not hold.",
            )
        if app and identity.kind != "app":
            raise _forbidden("app_session_required", "This is a handset's route.")
        raise _forbidden("permission_denied", "This session may not do that.")

    guard.__dcp_access__ = {  # type: ignore[attr-defined]
        "permission": permissions,
        "app": app,
        "signed_in": signed_in,
    }
    return guard


def public(reason: str) -> Guard:
    """The route's declaration that anyone may call it — with the reason,
    because an exemption without one is the hole the lint exists to close."""
    if not reason.strip():
        raise ValueError("public() needs a reason")

    async def guard() -> None:
        return None

    guard.__dcp_access__ = {"public": reason}  # type: ignore[attr-defined]
    return guard


def bound_device(identity: Identity, device_id: str) -> None:
    """An app session speaks for one device: the one it was created on.
    A request naming another is refused (proposal §4)."""
    if identity.kind != "app" or identity.device_id != device_id:
        raise _forbidden(
            "device_mismatch",
            "This session was created on a different device than the request names.",
        )


__all__ = [
    "COOKIE_PATH",
    "ORG_COOKIE",
    "SESSION_COOKIE",
    "Identity",
    "access",
    "bound_device",
    "clear_session_cookies",
    "current_identity",
    "get_db",
    "organization_slug",
    "public",
    "session_ttl",
    "set_session_cookies",
]

