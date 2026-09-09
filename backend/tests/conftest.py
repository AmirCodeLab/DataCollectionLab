"""Before the first `db` test runs: the application connection is `dcp_app`
and not privileged. First, and a failure — never a skip.

A suite that connects as a superuser reports every policy working while none
of them applies: FORCE does nothing to a superuser, so the isolation tests,
the coverage test and the API tests all pass on a connection that can see
every row. That is the one shape this repository must not be able to reach
again, so it is checked once, before any test that touches the database, on
the same path a request takes (`app.infrastructure.database.create_engine`).

Two outcomes only. Postgres reachable and the application role privileged:
the run fails here, naming the role and why. Postgres reachable and the role
bound: the suite proceeds. Postgres unreachable: locally the db tests skip as
they always have; in CI (`CI` is set) that is a failure too, because a db job
that is green with every test skipped is the same shape one layer up.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy import text

_checked = False


async def _postgres_reachable() -> str | None:
    from app.infrastructure.database import admin_connection

    try:
        async with admin_connection(timeout=3):
            return None
    except Exception as exc:  # noqa: BLE001 - any failure means "not available"
        return f"{type(exc).__name__}: {exc}"


async def _assert_the_application_connection_is_bound() -> None:
    from app.infrastructure.database import (
        _ROLE_QUERY,
        APP_ROLE,
        PrivilegedConnection,
        create_engine,
        ensure_app_role_can_login,
    )

    # The migration creates the role NOLOGIN; the suite is the deployment
    # that gives it a password — the one in DATABASE_URL — as the owner, once.
    await ensure_app_role_can_login()

    engine = create_engine()
    try:
        async with engine.connect() as conn:
            row = (await conn.execute(text(_ROLE_QUERY))).mappings().one()
    except PrivilegedConnection as exc:
        pytest.fail(str(exc), pytrace=False)
    finally:
        await engine.dispose()
    # The engine's own guard has already refused anything privileged; this is
    # the same fact asserted where a reader of the test output can see it.
    assert row["role"] == APP_ROLE, row
    assert not row["superuser"], row
    assert not row["bypasses_rls"], row
    assert not row["owns_tables"], row


def pytest_runtest_setup(item: pytest.Item) -> None:
    global _checked
    if _checked or item.get_closest_marker("db") is None:
        return
    _checked = True
    reason = asyncio.run(_postgres_reachable())
    if reason is not None:
        message = f"Postgres unavailable ({reason}) — start it with: docker compose up -d postgres"
        if os.environ.get("CI"):
            pytest.fail(f"the db suite is running in CI with no Postgres: {message}", pytrace=False)
        pytest.skip(message)
    asyncio.run(_assert_the_application_connection_is_bound())
