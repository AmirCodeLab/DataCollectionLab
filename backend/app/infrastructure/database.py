"""The one connection factory, and the principal every transaction declares.

ERD §1: isolation is a policy in the database, read from a principal the
connection sets. That holds only if three things are true of every connection
the application makes, and this module is where all three are made true:

1. **The application connects as `dcp_app`, never as the owner.** A superuser
   is exempt from row-level security and ``FORCE`` does not change that — the
   owner role in docker-compose is a superuser and read every row with FORCE
   on (probed 7 September 2026). So the engine refuses, at connect time and
   before any query, a role that is a superuser, has BYPASSRLS, or owns a
   table. A process that reaches a query has already passed that check.

2. **The principal is set per transaction, ``is_local => true``, never at
   session level** (ERD §1.1). A session-level setting rode a pooled
   connection into the next request and showed it another person's row; a
   transaction-local one was gone when the transaction ended. There is no
   reset step to forget, because the transaction's end is the reset — and
   because that is a claim about the pool rather than about this file, the
   pool asserts it: a connection returning with a principal still on it is
   discarded, with the traceback in the log, and never serves again.

3. **There is one of these.** ``tests/test_one_connection_factory.py`` fails
   on any engine, raw connection or ``postgresql://`` literal in ``app/`` or
   ``scripts/`` outside this file. A second connection is a route around
   every policy; an export script with its own engine is exactly the "one
   report nobody thought of". ``migrations/env.py`` runs as the owner by
   design and is the named exemption.

Sessions are handed out by :func:`session_as` (a principal you already hold)
and :func:`session_for_organization` (resolve the deployment's organisation
by slug first, ERD §1: the organisation is known before any user is read).
Both are ``@asynccontextmanager``: see ``test_no_session_generator_loops``.

The declarative ``Base`` lives here so every module's models share a single
``MetaData``; Alembic's env.py points at it for autogenerate support. The
engine is created lazily, never at import time: Alembic, tests and scripts
all import this module with different database URLs in play.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import asyncpg
from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, SessionTransaction

from app.core.config import get_settings

#: The role the application runs as. Created NOLOGIN by 008_identity.sql; a
#: deployment gives it LOGIN and a password (:func:`ensure_app_role_can_login`
#: for development, test and CI; an operator otherwise).
APP_ROLE = "dcp_app"


class Base(DeclarativeBase):
    """Shared declarative base for every model in app/modules/*/models.py.

    The normative schema is backend/migrations/schema/*.sql; the models
    mirror it. If a model and the SQL file disagree, the SQL file wins.
    """


# ---------------------------------------------------------------------------
# The principal
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Principal:
    """What the policies read from the connection (ERD §1).

    Every field empty is *nobody*: an absent principal is no access, and the
    policies compare through ``coalesce(current_setting(...), '')`` so that
    ``''`` and NULL deny alike.
    """

    org_id: str = ""
    org_slug: str = ""
    user_id: str = ""
    #: 'organization' | 'project' | 'team' — the widest live grant (§5).
    scope_kind: str = ""
    #: The people whose work this principal may see.
    visible_user_ids: tuple[str, ...] = ()

    @classmethod
    def organization(cls, org_id: str, *, slug: str = "") -> Principal:
        """Organisation-wide scope: everything in one organisation, nothing
        outside it. What a request carries until login exists (item 1's
        remaining half), and what provisioning runs as."""
        return cls(org_id=org_id, org_slug=slug, scope_kind="organization")

    def as_settings(self) -> dict[str, str]:
        return {
            "org_id": self.org_id,
            "org_slug": self.org_slug,
            "user_id": self.user_id,
            "scope_kind": self.scope_kind,
            "visible_user_ids": ",".join(self.visible_user_ids),
        }


#: Explicitly nobody. A session with no principal declares this, so that no
#: transaction ever begins without saying who it is for.
NOBODY = Principal()

#: The settings, in the order the policies name them.
PRINCIPAL_SETTINGS = ("app.org_id", "app.org_slug", "app.user_id", "app.scope_kind",
                      "app.visible_user_ids")

_DECLARE_PRINCIPAL = text(
    "SELECT set_config('app.org_id', :org_id, true),"
    "       set_config('app.org_slug', :org_slug, true),"
    "       set_config('app.user_id', :user_id, true),"
    "       set_config('app.scope_kind', :scope_kind, true),"
    "       set_config('app.visible_user_ids', :visible_user_ids, true)"
)

_READ_PRINCIPAL = "SELECT " + ", ".join(
    f"coalesce(current_setting('{name}', true), '') AS \"{name}\"" for name in PRINCIPAL_SETTINGS
)


@event.listens_for(Session, "after_begin")
def _declare_principal(
    session: Session, _transaction: SessionTransaction, connection: Connection
) -> None:
    """Every transaction begins by declaring its principal — the session's, or
    nobody. ``is_local => true``: gone at COMMIT or ROLLBACK, so a pooled
    connection carries nothing into the next request. Re-applied after every
    commit inside a session, because a commit ends the transaction that
    carried it."""
    principal: Principal = session.info.get("principal") or NOBODY
    connection.execute(_DECLARE_PRINCIPAL, principal.as_settings())


# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------


def _with_database(url: str, database: str | None) -> str:
    if database is None:
        return url
    return urlunsplit(urlsplit(url)._replace(path=f"/{database}"))


def app_url(database: str | None = None) -> str:
    """The application's URL: ``dcp_app``, from ``DATABASE_URL``."""
    return _with_database(get_settings().database_url, database)


def admin_url(database: str | None = None) -> str:
    """The owner's URL, from ``DATABASE_ADMIN_URL``: migrations and
    provisioning only. Never a request."""
    return _with_database(get_settings().database_admin_url, database)


def asyncpg_dsn(url: str) -> str:
    """The same URL as asyncpg spells it."""
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


# ---------------------------------------------------------------------------
# The application engine, and what it refuses
# ---------------------------------------------------------------------------


class PrivilegedConnection(RuntimeError):
    """The application connected as a role the policies do not bind."""


class PrincipalLeaked(RuntimeError):
    """A connection came back to the pool still carrying a principal."""


_ROLE_QUERY = """
SELECT current_user AS role,
       r.rolsuper AS superuser,
       r.rolbypassrls AS bypasses_rls,
       EXISTS (SELECT 1 FROM pg_tables
                WHERE schemaname = 'public' AND tableowner = current_user) AS owns_tables
FROM pg_roles r
WHERE r.rolname = current_user
"""


def _refuse_a_privileged_role(dbapi_connection: Any, _record: Any) -> None:
    """Pool ``connect``: before this connection serves a single query."""

    async def read(raw: asyncpg.Connection) -> Any:
        return await raw.fetchrow(_ROLE_QUERY)

    row = dbapi_connection.run_async(read)
    reasons = []
    if row["superuser"]:
        reasons.append("is a superuser, which row-level security never applies to")
    if row["bypasses_rls"]:
        reasons.append("has BYPASSRLS")
    if row["owns_tables"]:
        reasons.append("owns the tables, which only FORCE binds")
    if row["role"] != APP_ROLE:
        reasons.append(f"is not {APP_ROLE}")
    if reasons:
        raise PrivilegedConnection(
            f"refusing to run the application as {row['role']!r}: it "
            + "; ".join(reasons)
            + ". Every policy in the schema would be bypassed and every screen would look "
            f"correct. DATABASE_URL must connect as {APP_ROLE} (ERD §1); the owner belongs "
            "in DATABASE_ADMIN_URL, for migrations."
        )


def _refuse_a_leaked_principal(dbapi_connection: Any, _record: Any, reset_state: Any) -> None:
    """Pool ``reset``, on the way back to the pool: the transaction's end is
    the reset, so after a rollback nothing transaction-local survives.
    Anything that does was set at session level — the leak ERD §1.1 is
    about — and raising here is how the pool discards the connection: it
    logs the traceback, invalidates the connection, and hands the slot back.
    The next request gets a fresh connection, never this one.
    """
    if reset_state.terminate_only:
        return
    dbapi_connection.rollback()

    async def read(raw: asyncpg.Connection) -> Any:
        return await raw.fetchrow(_READ_PRINCIPAL)

    row = dbapi_connection.run_async(read)
    carried = {name: row[name] for name in PRINCIPAL_SETTINGS if row[name]}
    if carried:
        raise PrincipalLeaked(
            f"a connection returned to the pool still carrying {carried}: a principal was "
            "set at session level. ERD §1.1 — the principal is transaction-local, always, "
            "because the next request on this connection would have been another tenant's. "
            "The connection has been discarded."
        )


def create_engine(
    database: str | None = None, *, url: str | None = None, **kwargs: Any
) -> AsyncEngine:
    """The application's engine: ``dcp_app``, guarded.

    ``database`` swaps the database name in ``DATABASE_URL`` (tests and
    scripts that work on a scratch database); ``url`` replaces it whole. Both
    still connect through the guards — there is no way to build an engine
    here that a superuser could use.
    """
    engine = create_async_engine(url or app_url(database), **kwargs)
    event.listen(engine.sync_engine, "connect", _refuse_a_privileged_role)
    event.listen(engine.sync_engine, "reset", _refuse_a_leaked_principal)
    return engine


def create_admin_engine(database: str | None = None, *, url: str | None = None) -> AsyncEngine:
    """The owner's engine, for migrations and provisioning. It sees every row
    and writes without a policy: nothing that serves a request may hold one."""
    return create_async_engine(url or admin_url(database))


@lru_cache(maxsize=1)
def default_engine() -> AsyncEngine:
    """The process's application engine."""
    return create_engine()


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


class OrganizationUnknown(LookupError):
    """No organisation has this slug — or none is visible, which under the
    policy is the same thing."""


@asynccontextmanager
async def session_as(
    principal: Principal, *, engine: AsyncEngine | None = None
) -> AsyncIterator[AsyncSession]:
    """A session whose every transaction declares ``principal``."""
    factory = create_session_factory(engine if engine is not None else default_engine())
    async with factory(info={"principal": principal}) as session:
        yield session


@asynccontextmanager
async def session_for_organization(
    slug: str, *, engine: AsyncEngine | None = None
) -> AsyncIterator[AsyncSession]:
    """Resolve the organisation first, then a session scoped to it.

    ERD §1: with a principal of nothing the application can see no user, so
    the organisation is known before anything else is read. ``app.org_slug``
    admits exactly that one ``platform_organization`` row; its id becomes
    ``app.org_id`` for the rest of the session. This deployment is
    single-tenant, so the slug is the configured one; multi-tenant
    provisioning has to deliver the resolution (hostname, login form), and
    nothing here reads a user without an organisation in the meantime.
    """
    async with session_as(Principal(org_slug=slug), engine=engine) as session:
        org_id = (
            await session.execute(
                text("SELECT id FROM platform_organization WHERE slug = :slug"), {"slug": slug}
            )
        ).scalar_one_or_none()
        # End the resolving transaction: the next one declares the whole principal.
        await session.rollback()
        if org_id is None:
            raise OrganizationUnknown(
                f"no organisation with slug {slug!r} is visible. Seed one "
                "(scripts/seed_dev.py) or set ORGANIZATION_SLUG to the deployment's."
            )
        session.info["principal"] = Principal.organization(org_id, slug=slug)
        yield session


# ---------------------------------------------------------------------------
# Administration: the owner, for provisioning only
# ---------------------------------------------------------------------------


@asynccontextmanager
async def admin_connection(
    database: str | None = None, *, timeout: float = 5
) -> AsyncIterator[asyncpg.Connection]:
    """A raw owner connection: CREATE/DROP DATABASE and role provisioning,
    which cannot run inside a transaction."""
    conn = await asyncpg.connect(asyncpg_dsn(admin_url(database)), timeout=timeout)
    try:
        yield conn
    finally:
        await conn.close()


async def recreate_database(name: str, *, via: str = "postgres") -> None:
    """Drop ``name`` if it exists and create it empty, from the maintenance
    database — the one the admin URL names may be the one being dropped."""
    async with admin_connection(via) as conn:
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{name}"')


async def ensure_app_role_can_login(*, database: str | None = None) -> None:
    """Give ``dcp_app`` LOGIN with the password ``DATABASE_URL`` carries.

    The migration creates the role NOLOGIN and grants it the tables; a
    deployment decides how it logs in. For development, tests and CI that is
    this: the admin, once, before anything connects as the application.
    """
    password = urlsplit(app_url()).password or ""
    if not password.replace("_", "").replace("-", "").isalnum():
        raise ValueError("the application password in DATABASE_URL must be alphanumeric")
    async with admin_connection(database) as conn:
        await conn.execute(
            "DO $$ BEGIN "
            f"IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN "
            f"CREATE ROLE {APP_ROLE} NOLOGIN; END IF; END $$"
        )
        await conn.execute(f"ALTER ROLE {APP_ROLE} LOGIN PASSWORD '{password}'")

