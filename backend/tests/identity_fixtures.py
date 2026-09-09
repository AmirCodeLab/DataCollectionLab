"""One organisation for the db tests to hang their projects on, and the way
the API under test connects to it.

Since 008_identity.sql every project names its organisation, and the tests
that seed a project directly need one to exist first. It is the same row for
every test and the insert is idempotent, because a test module may seed more
than once into the same database.

Seeding runs as the owner: it is provisioning, and provisioning is the
owner's job. The API under test does not — it runs through the one connection
factory as `dcp_app`, with this organisation's principal, on the path a
request takes. A test that drove the API as the owner would pass whether or
not any policy applied.

The identity is the one thing these modules stand in for. `api_session_override`
also overrides `current_identity` with a fabricated session: a console session
holding every permission, or — when the request names a device — an app
session bound to that device, so the handset routes see the shape they
require. The login itself, the cookies, the refusals and the team boundary
are exercised for real, with no override, in `test_auth.py`; the route lint
(`test_every_route_declares_access.py`) is what makes a missing declaration a
failure regardless of what a module's override would have allowed.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import current_identity
from app.infrastructure.database import Principal, create_engine, session_as
from app.modules.auth.schemas import PERMISSIONS
from app.modules.auth.service import Identity

ORG_ID = "01ORGTEST"
ORG_SLUG = "test"

#: The fabricated person behind a module's requests: organisation-wide scope.
TEST_USER_ID = "01USRTEST"
ORG_PRINCIPAL = Principal(
    org_id=ORG_ID,
    org_slug=ORG_SLUG,
    user_id=TEST_USER_ID,
    scope_kind="organization",
    visible_user_ids=(TEST_USER_ID,),
    permissions=tuple(PERMISSIONS),
)


#: The route families a handset calls: a request there without a device in
#: it (a pull from the cursor, a chunk by upload id) is still an app session.
HANDSET_PREFIXES = ("/api/v1/sync", "/api/v1/media", "/api/v1/devices")


def identity_for(*, kind: str = "console", device_id: str | None = None) -> Identity:
    """A console session holding every permission, or an app session on
    `device_id`."""
    return Identity(
        session_id="01SESTEST",
        user_id=TEST_USER_ID,
        username="test",
        display_name="Test Person",
        kind="app" if device_id else kind,
        device_id=device_id,
        principal=ORG_PRINCIPAL,
        permissions=frozenset(PERMISSIONS),
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )


async def _device_named_by(request: Request) -> str | None:
    """The device a handset request names: a path segment, a query
    parameter, or a JSON body field."""
    if "device_id" in request.path_params:
        return str(request.path_params["device_id"])
    if request.query_params.get("deviceId"):
        return request.query_params["deviceId"]
    if request.headers.get("content-type", "").startswith("application/json"):
        try:
            body: Any = json.loads(await request.body())
        except ValueError:
            return None
        if isinstance(body, dict) and isinstance(body.get("deviceId"), str):
            return body["deviceId"]
    return None


async def ensure_organization(session: AsyncSession) -> None:
    await session.execute(
        text(
            "INSERT INTO platform_organization (id, name, slug) "
            "VALUES (:id, 'Test Organisation', :slug) ON CONFLICT (id) DO NOTHING"
        ),
        {"id": ORG_ID, "slug": ORG_SLUG},
    )
    # The fabricated person behind the API tests, as a row: a device a test
    # seeds is bound to them, the way a login binds one, so pushed ops have a
    # person to be filed under.
    await session.execute(
        text(
            "INSERT INTO platform_user (id, organization_id, display_name, username) "
            "VALUES (:id, :org, 'Test Person', 'test') ON CONFLICT (id) DO NOTHING"
        ),
        {"id": TEST_USER_ID, "org": ORG_ID},
    )


def database_of(url: str) -> str:
    """The database a module's scratch URL names."""
    return urlsplit(url).path.lstrip("/")


def api_session_override(database: str) -> Callable[[], AsyncIterator[AsyncSession]]:
    """The `get_db` override for a module's scratch database — and, installed
    beside it on the app by `install_api_overrides`, the identity override.

    One engine per request: each test runs in its own event loop, and pooled
    asyncpg connections cannot cross loops. Every engine is the factory's, so
    every request's connection is refused if it is privileged.
    """

    async def scratch_db() -> AsyncIterator[AsyncSession]:
        engine = create_engine(database=database)
        try:
            async with session_as(ORG_PRINCIPAL, engine=engine) as session:
                yield session
        finally:
            await engine.dispose()

    return scratch_db


async def fabricated_identity(request: Request) -> Identity:
    device_id = await _device_named_by(request)
    handset = request.url.path.startswith(HANDSET_PREFIXES)
    return identity_for(kind="app" if handset else "console", device_id=device_id)


def install_api_overrides(app: Any, database: str) -> None:
    """Both overrides at once, so a module cannot take the session without
    the identity and drive the API as nobody by mistake."""
    from app.api.deps import get_db

    app.dependency_overrides[get_db] = api_session_override(database)
    app.dependency_overrides[current_identity] = fabricated_identity


def install_identity_override(app: Any) -> None:
    """The identity alone, for a module that never touches the database: the
    engine routes (compile, expressions, palette, evaluate) are guarded like
    every other, and a test of the engine's answer is not a test of the guard."""
    app.dependency_overrides[current_identity] = fabricated_identity


def remove_api_overrides(app: Any) -> None:
    from app.api.deps import get_db

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(current_identity, None)
