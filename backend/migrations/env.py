"""Alembic environment.

Runs migrations through the async engine from app/infrastructure. The database
URL comes from app.core.config (DATABASE_URL env var / .env); tests may
override it with ``config.set_main_option("sqlalchemy.url", ...)``.
"""

import asyncio

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.infrastructure.database import Base

# Import every module's models so Base.metadata is complete for autogenerate.
from app.modules.audit import models as _audit_models  # noqa: F401
from app.modules.auth import models as _auth_models  # noqa: F401
from app.modules.cases import models as _cases_models  # noqa: F401
from app.modules.crypto import models as _crypto_models  # noqa: F401
from app.modules.entities import models as _entities_models  # noqa: F401
from app.modules.forms import models as _forms_models  # noqa: F401
from app.modules.media import models as _media_models  # noqa: F401
from app.modules.projects import models as _projects_models  # noqa: F401
from app.modules.quality import models as _quality_models  # noqa: F401
from app.modules.submissions import models as _submissions_models  # noqa: F401
from app.modules.sync import models as _sync_models  # noqa: F401
from app.modules.workflows import models as _workflows_models  # noqa: F401

config = context.config

target_metadata = Base.metadata


def _database_url() -> str:
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def _exclude_postgis(obj: object, name: str | None, type_: str, *_: object) -> bool:
    """Keep autogenerate away from objects owned by the postgis extension."""
    return not (type_ == "table" and name == "spatial_ref_sys")


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=_exclude_postgis,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=_exclude_postgis,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_database_url())
    async with engine.connect() as connection:
        await connection.run_sync(_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
