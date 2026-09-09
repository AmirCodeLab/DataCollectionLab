"""One organisation for the db tests to hang their projects on.

Since 008_identity.sql every project names its organisation, and the tests
that seed a project directly need one to exist first. It is the same row for
every test and the insert is idempotent, because a test module may seed more
than once into the same database.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ORG_ID = "01ORGTEST"


async def ensure_organization(session: AsyncSession) -> None:
    await session.execute(
        text(
            "INSERT INTO platform_organization (id, name, slug) "
            "VALUES (:id, 'Test Organisation', 'test') ON CONFLICT (id) DO NOTHING"
        ),
        {"id": ORG_ID},
    )
