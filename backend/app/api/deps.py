"""Shared FastAPI dependencies."""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.database import create_engine, create_session_factory


@lru_cache(maxsize=1)
def _session_factory() -> async_sessionmaker[AsyncSession]:
    return create_session_factory(create_engine())


async def get_db() -> AsyncIterator[AsyncSession]:
    async with _session_factory()() as session:
        yield session
