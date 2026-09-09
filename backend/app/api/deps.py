"""Shared FastAPI dependencies."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.infrastructure.database import session_for_organization


async def get_db() -> AsyncIterator[AsyncSession]:
    """A session scoped to the deployment's organisation, as `dcp_app`.

    Until login exists (item 1's other half) every request carries the
    organisation-wide principal: everything in the configured organisation,
    nothing outside it, and nothing at all if that organisation does not
    exist. A person's own scope replaces this when a session cookie does.
    """
    async with session_for_organization(get_settings().organization_slug) as session:
        yield session
