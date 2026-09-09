"""One organisation for the db tests to hang their projects on, and the way
the API under test connects to it.

Since 008_identity.sql every project names its organisation, and the tests
that seed a project directly need one to exist first. It is the same row for
every test and the insert is idempotent, because a test module may seed more
than once into the same database.

Seeding runs as the owner: it is provisioning, and provisioning is the
owner's job. The API under test does not — it runs through the one connection
factory as `dcp_app`, with this organisation's principal, which is the path a
request takes minus the login that is not built yet. A test that drove the
API as the owner would pass whether or not any policy applied.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from urllib.parse import urlsplit

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database import Principal, create_engine, session_as

ORG_ID = "01ORGTEST"
ORG_SLUG = "test"

#: What a request carries until login exists: the whole organisation.
ORG_PRINCIPAL = Principal.organization(ORG_ID, slug=ORG_SLUG)


async def ensure_organization(session: AsyncSession) -> None:
    await session.execute(
        text(
            "INSERT INTO platform_organization (id, name, slug) "
            "VALUES (:id, 'Test Organisation', :slug) ON CONFLICT (id) DO NOTHING"
        ),
        {"id": ORG_ID, "slug": ORG_SLUG},
    )


def database_of(url: str) -> str:
    """The database a module's scratch URL names."""
    return urlsplit(url).path.lstrip("/")


def api_session_override(database: str) -> Callable[[], AsyncIterator[AsyncSession]]:
    """The `get_db` override for a module's scratch database.

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
