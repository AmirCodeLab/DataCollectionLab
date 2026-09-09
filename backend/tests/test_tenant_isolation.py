"""Isolation, on the path a request takes.

Every test here runs through `app.infrastructure.database` as `dcp_app`, with
a principal, the way the API does. The schema's guarantees were first watched
against a hand-made role in psql; the claim that matters is that they hold on
the application's own connection, and that is what these assert.

The order is the argument. The first test says the connection is not
privileged; `conftest.py` has already refused to start if it were, so this is
the same fact where a reader can see it. Everything after it is meaningless
without it: a superuser passes every isolation test whether or not isolation
works.

Fixture rows are inserted as the owner (`create_admin_engine`): a second
organisation is not provisioning, nothing can log into it, and the module
drops the database at the end.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.infrastructure.database import (
    _ROLE_QUERY,
    APP_ROLE,
    NOBODY,
    Principal,
    PrincipalLeaked,
    PrivilegedConnection,
    admin_connection,
    admin_url,
    create_admin_engine,
    create_engine,
    session_as,
)

ISOLATION_DB = "dcp_test_isolation"

ORG_A, ORG_B = "01ORGA", "01ORGB"
A = Principal.organization(ORG_A, slug="a")
B = Principal.organization(ORG_B, slug="b")

U_ACTIVE, U_PENDING, U_DEACT = "01USRACTIVE", "01USRPENDING", "01USRDEACT"


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


async def _seed() -> None:
    from app.modules.auth.models import PlatformOrganization, PlatformUser
    from app.modules.forms.models import Form, FormVersion
    from app.modules.projects.models import Environment, Project
    from app.modules.submissions.models import Submission

    engine = create_admin_engine(database=ISOLATION_DB)
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            for org, slug in ((ORG_A, "a"), (ORG_B, "b")):
                session.add(PlatformOrganization(id=org, name=f"Org {slug}", slug=slug))
            await session.flush()
            for org in (ORG_A, ORG_B):
                session.add(
                    Project(id=f"PRJ{org}", organization_id=org, name=org, slug=org.lower())
                )
            await session.flush()
            for org in (ORG_A, ORG_B):
                session.add(Environment(id=f"ENV{org}", project_id=f"PRJ{org}", kind="production"))
                session.add(
                    Form(id=f"FRM{org}", project_id=f"PRJ{org}", form_key="f", title="F")
                )
            await session.flush()
            for org in (ORG_A, ORG_B):
                session.add(
                    FormVersion(
                        id=f"VER{org}", form_id=f"FRM{org}", version=1, ir={}, ir_checksum="x"
                    )
                )
            await session.flush()
            for org in (ORG_A, ORG_B):
                session.add(
                    Submission(
                        id=f"SUB{org}",
                        project_id=f"PRJ{org}",
                        environment_id=f"ENV{org}",
                        form_version_id=f"VER{org}",
                    )
                )
            # Three people in A: one active, one waiting, one about to go.
            for user in (U_ACTIVE, U_PENDING, U_DEACT):
                session.add(PlatformUser(id=user, organization_id=ORG_A))
            await session.flush()
            await session.execute(
                text(
                    "INSERT INTO platform_org_membership "
                    "    (organization_id, user_id, org_role, status) "
                    "VALUES (:org, :active, 'member', 'active'), "
                    "       (:org, :pending, 'member', 'pending_approval'), "
                    "       (:org, :deact, 'member', 'active')"
                ),
                {"org": ORG_A, "active": U_ACTIVE, "pending": U_PENDING, "deact": U_DEACT},
            )
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def isolation_db() -> Any:
    from alembic import command
    from alembic.config import Config

    from tests.test_migrations import BACKEND_DIR

    async def prepare() -> str | None:
        try:
            async with admin_connection(timeout=3) as conn:
                await conn.execute(f"DROP DATABASE IF EXISTS {ISOLATION_DB} WITH (FORCE)")
                await conn.execute(f"CREATE DATABASE {ISOLATION_DB}")
        except Exception as exc:  # noqa: BLE001 - any failure means "not available"
            return f"{type(exc).__name__}: {exc}"
        return None

    reason = _run(prepare())
    if reason is not None:
        pytest.skip(
            f"Postgres unavailable ({reason}) — start it with: docker compose up -d postgres"
        )

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", admin_url(ISOLATION_DB))
    command.upgrade(cfg, "head")
    _run(_seed())

    yield ISOLATION_DB

    async def drop() -> None:
        async with admin_connection() as conn:
            await conn.execute(f"DROP DATABASE IF EXISTS {ISOLATION_DB} WITH (FORCE)")

    _run(drop())


async def _project_ids(engine: AsyncEngine, principal: Principal) -> set[str]:
    from app.modules.projects.models import Project

    async with session_as(principal, engine=engine) as session:
        return set((await session.execute(select(Project.id))).scalars())


async def _submission_ids(engine: AsyncEngine, principal: Principal) -> set[str]:
    from app.modules.submissions.models import Submission

    async with session_as(principal, engine=engine) as session:
        return set((await session.execute(select(Submission.id))).scalars())


# ---------------------------------------------------------------------------
# 1. The connection — before anything else
# ---------------------------------------------------------------------------


@pytest.mark.db
def test_01_the_connection_is_dcp_app_and_not_privileged(isolation_db: str) -> None:
    async def go() -> Any:
        engine = create_engine(database=isolation_db)
        try:
            async with engine.connect() as conn:
                return (await conn.execute(text(_ROLE_QUERY))).mappings().one()
        finally:
            await engine.dispose()

    row = _run(go())
    assert row["role"] == APP_ROLE
    assert row["superuser"] is False
    assert row["bypasses_rls"] is False
    assert row["owns_tables"] is False


@pytest.mark.db
def test_02_the_factory_refuses_the_owner(isolation_db: str) -> None:
    """Connect the suite as the owner: the break, run for real. The refusal is
    at connect time, before a query, and names why."""

    async def go() -> None:
        engine = create_engine(url=admin_url(isolation_db))
        try:
            with pytest.raises(PrivilegedConnection, match="superuser"):
                async with engine.connect():
                    pass
        finally:
            await engine.dispose()

    _run(go())


# ---------------------------------------------------------------------------
# 2. Isolation, unfiltered
# ---------------------------------------------------------------------------


@pytest.mark.db
def test_03_each_organisation_sees_only_its_own_rows(isolation_db: str) -> None:
    async def go() -> None:
        engine = create_engine(database=isolation_db)
        try:
            assert await _project_ids(engine, A) == {f"PRJ{ORG_A}"}
            assert await _project_ids(engine, B) == {f"PRJ{ORG_B}"}
            # The scoped policy: organisation-wide scope sees the organisation's work.
            assert await _submission_ids(engine, A) == {f"SUB{ORG_A}"}
            assert await _submission_ids(engine, B) == {f"SUB{ORG_B}"}
        finally:
            await engine.dispose()

    _run(go())


@pytest.mark.db
def test_04_no_principal_sees_nothing_on_a_fresh_and_on_a_reused_connection(
    isolation_db: str,
) -> None:
    """The break that matters most: unset is zero rows, never everything. On
    a connection that has never carried a principal (the setting is NULL) and
    on one that carried another organisation's a moment ago (it reads '')."""

    async def setting(engine: AsyncEngine, principal: Principal) -> str:
        async with session_as(principal, engine=engine) as session:
            return (
                await session.execute(
                    text("SELECT coalesce(current_setting('app.org_id', true), '')")
                )
            ).scalar_one()

    async def go() -> None:
        # One connection in the pool, so the third session reuses the second's.
        engine = create_engine(database=isolation_db, pool_size=1, max_overflow=0)
        try:
            assert await _project_ids(engine, NOBODY) == set()
            assert await _submission_ids(engine, NOBODY) == set()
            assert await _project_ids(engine, A) == {f"PRJ{ORG_A}"}
            assert await setting(engine, NOBODY) == ""
            assert await _project_ids(engine, NOBODY) == set()
            assert await _submission_ids(engine, NOBODY) == set()
            # A session with no principal at all, not even an explicit nobody.
            async with async_sessionmaker(engine)() as session:
                count = select(func.count()).select_from(text("project"))
                assert (await session.execute(count)).scalar_one() == 0
        finally:
            await engine.dispose()

    _run(go())


@pytest.mark.db
def test_05_the_principal_survives_a_commit_inside_the_session(isolation_db: str) -> None:
    """A commit ends the transaction that carried the principal. The next
    transaction in the same session must carry it again, or the second half
    of every service function would see nothing — silently."""
    from app.modules.projects.models import Project

    async def go() -> None:
        engine = create_engine(database=isolation_db)
        try:
            async with session_as(A, engine=engine) as session:
                assert set((await session.execute(select(Project.id))).scalars()) == {f"PRJ{ORG_A}"}
                await session.commit()
                assert set((await session.execute(select(Project.id))).scalars()) == {f"PRJ{ORG_A}"}
        finally:
            await engine.dispose()

    _run(go())


@pytest.mark.db
def test_06_a_session_level_principal_is_refused_on_return_to_the_pool(
    isolation_db: str, caplog: pytest.LogCaptureFixture
) -> None:
    """ERD §1.1 asserted, not relied on. A principal set at session level would
    ride this connection into the next request as another tenant's; the pool
    discards the connection, with the traceback in its log, and the next
    session — on a pool of one, so it would have been the same connection —
    sees nothing."""

    async def go() -> None:
        engine = create_engine(database=isolation_db, pool_size=1, max_overflow=0)
        try:
            async with session_as(A, engine=engine) as session:
                await session.execute(
                    text("SELECT set_config('app.org_id', :other, false)"), {"other": ORG_B}
                )
                await session.commit()
            assert await _project_ids(engine, NOBODY) == set()
            assert await _project_ids(engine, B) == {f"PRJ{ORG_B}"}
        finally:
            await engine.dispose()

    with caplog.at_level(logging.ERROR, logger="sqlalchemy.pool"):
        _run(go())
    refusals = [
        record.exc_info[1]
        for record in caplog.records
        if record.exc_info and isinstance(record.exc_info[1], PrincipalLeaked)
    ]
    assert len(refusals) == 1, "the pool did not refuse the leaked connection"
    assert "app.org_id" in str(refusals[0])


# ---------------------------------------------------------------------------
# 3. pending_approval, structurally, through the layer
# ---------------------------------------------------------------------------


def _session_row(user: str, token: str) -> Any:
    from app.modules.auth.models import PlatformSession

    return PlatformSession(
        id=f"SES{token}",
        user_id=user,
        kind="console",
        token_hash=token,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )


@pytest.mark.db
def test_07_a_pending_membership_cannot_hold_a_session(isolation_db: str) -> None:
    async def go() -> None:
        engine = create_engine(database=isolation_db)
        try:
            async with session_as(A, engine=engine) as session:
                session.add(_session_row(U_ACTIVE, "active"))
                await session.flush()  # accepted: the membership is active
                with pytest.raises(ProgrammingError, match="row-level security"):
                    async with session.begin_nested():
                        session.add(_session_row(U_PENDING, "pending"))
                        await session.flush()
                await session.rollback()
        finally:
            await engine.dispose()

    _run(go())


@pytest.mark.db
def test_08_a_deactivated_membership_loses_its_sessions(isolation_db: str) -> None:
    """Logged out by the policy: no revoke job to forget."""
    from app.modules.auth.models import PlatformSession

    async def visible(engine: AsyncEngine) -> set[str]:
        async with session_as(A, engine=engine) as session:
            return set((await session.execute(select(PlatformSession.user_id))).scalars())

    async def go() -> None:
        engine = create_engine(database=isolation_db)
        try:
            async with session_as(A, engine=engine) as session:
                session.add(_session_row(U_DEACT, "deact"))
                await session.commit()
            assert U_DEACT in await visible(engine)
            async with admin_connection(isolation_db) as owner:
                await owner.execute(
                    "UPDATE platform_org_membership SET status = 'deactivated', "
                    "deactivated_at = now() WHERE user_id = $1",
                    U_DEACT,
                )
            assert U_DEACT not in await visible(engine)
        finally:
            await engine.dispose()

    _run(go())
