"""Async SQLAlchemy engine, session factory and declarative base.

The declarative ``Base`` lives here so every module's models share a single
``MetaData``; Alembic's env.py points at it for autogenerate support.

The engine is created lazily, never at import time: Alembic, tests and Celery
workers all import this module with different database URLs in play.
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    """Shared declarative base for every model in app/modules/*/models.py.

    The normative schema is backend/migrations/schema/001_initial.sql; the
    models mirror it. If a model and the SQL file disagree, the SQL file wins.
    """


def create_engine(url: str | None = None) -> AsyncEngine:
    return create_async_engine(url or get_settings().database_url)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        yield session
