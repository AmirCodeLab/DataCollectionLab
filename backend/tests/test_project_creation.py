"""Creating a project, and the line it sits on (gate 1).

An **organisation** cannot be created through a route: there is no principal
until one exists, so the act needs a privilege no request may hold, and it
lives in `scripts/provision.py`. A **project** can, because by the time
anybody asks for one an administrator exists and can be refused like anybody
else (A2).

These tests hold the two halves of that: the route creates what A5 says it
creates, and it refuses what it should, under a principal that is not
organisation-wide by accident.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy import text

from app.infrastructure.database import (
    Principal,
    admin_connection,
    admin_url,
    create_engine,
    session_as,
)
from app.modules.projects.schemas import ProjectCreate
from app.modules.projects.service import ENVIRONMENT_KINDS, ProjectCreateError, create_project

DB = "dcp_test_project_create"
ORG, OTHER_ORG = "01ORGPRJ", "01ORGOTHER"


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


async def _seed() -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.infrastructure.database import create_admin_engine
    from app.modules.auth import builtin_roles

    async with admin_connection(DB) as conn:
        for org, slug in ((ORG, "prj"), (OTHER_ORG, "other")):
            await conn.execute(
                "INSERT INTO platform_organization (id, name, slug) VALUES ($1, $2, $2)",
                org,
                slug,
            )
    engine = create_admin_engine(database=DB)
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            await builtin_roles.install(session, ORG)
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def project_db() -> Any:
    from alembic import command
    from alembic.config import Config

    from tests.test_migrations import BACKEND_DIR

    async def prepare() -> str | None:
        try:
            async with admin_connection() as conn:
                await conn.execute(f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)")
                await conn.execute(f"CREATE DATABASE {DB}")
        except Exception as exc:  # noqa: BLE001
            return f"{type(exc).__name__}: {exc}"
        return None

    reason = _run(prepare())
    if reason is not None:
        pytest.skip(f"postgres not available: {reason}")

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", admin_url(DB))
    command.upgrade(config, "head")
    _run(_seed())
    yield DB

    async def drop() -> None:
        async with admin_connection() as conn:
            await conn.execute(f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)")

    _run(drop())


def _administrator(org: str = ORG) -> Principal:
    return Principal(
        org_id=org,
        org_slug="prj",
        user_id="01USRADM",
        scope_kind="organization",
        permissions=("project.manage",),
    )


@pytest.mark.db
def test_a_project_arrives_with_all_three_environments(project_db: str) -> None:
    """A5. A project that can deploy nowhere is not a project, and the person
    who finds that out is whoever was trying to get a form onto a phone."""

    async def go() -> None:
        engine = create_engine(database=project_db)
        try:
            async with session_as(_administrator(), engine=engine) as s, s.begin():
                created = await create_project(
                    s, ProjectCreate(name="Household listing", slug="listing"), organization_id=ORG
                )
            async with session_as(_administrator(), engine=engine) as s:
                kinds = (
                    (
                        await s.execute(
                            text(
                                "SELECT kind FROM environment "
                                "WHERE project_id = :p ORDER BY kind"
                            ),
                            {"p": created.id},
                        )
                    )
                    .scalars()
                    .all()
                )
            assert sorted(kinds) == sorted(ENVIRONMENT_KINDS)
            assert created.active_key_count == 0, (
                "a new project has no key, and the projects screen says devices "
                "cannot sync until one exists"
            )
        finally:
            await engine.dispose()

    _run(go())


@pytest.mark.db
def test_a_duplicate_slug_is_refused_by_name(project_db: str) -> None:
    """The slug is what URLs and environment names are built from. A console
    puts this message beside the field."""

    async def go() -> None:
        engine = create_engine(database=project_db)
        try:
            async with session_as(_administrator(), engine=engine) as s, s.begin():
                await create_project(
                    s, ProjectCreate(name="First", slug="census"), organization_id=ORG
                )
            async with session_as(_administrator(), engine=engine) as s, s.begin():
                with pytest.raises(ProjectCreateError) as refused:
                    await create_project(
                        s, ProjectCreate(name="Second", slug="census"), organization_id=ORG
                    )
            assert refused.value.reason == "slug_taken"
            assert "census" in refused.value.message
        finally:
            await engine.dispose()

    _run(go())


@pytest.mark.db
def test_the_project_lands_in_the_principals_organisation_and_not_a_named_one(
    project_db: str,
) -> None:
    """`ProjectCreate` has no organisation field, and this is why.

    A body that named one would be a caller choosing which organisation their
    project appears in. The policy would refuse the write — `project` is an
    organisation root — but the refusal would be a 500-shaped surprise rather
    than a design. The field does not exist, so the question cannot be asked.
    """

    async def go() -> None:
        assert "organization_id" not in ProjectCreate.model_fields
        assert "organizationId" not in {
            field.alias for field in ProjectCreate.model_fields.values() if field.alias
        }

        engine = create_engine(database=project_db)
        try:
            # And the body refuses an unknown field outright rather than
            # ignoring it, so a client that tries learns immediately.
            from pydantic import ValidationError

            with pytest.raises(ValidationError):
                ProjectCreate(  # type: ignore[call-arg]
                    name="X", slug="x", organizationId=OTHER_ORG
                )

            async with session_as(_administrator(), engine=engine) as s, s.begin():
                created = await create_project(
                    s, ProjectCreate(name="Scoped", slug="scoped"), organization_id=ORG
                )
            async with admin_connection(project_db) as conn:
                owner = await conn.fetchval(
                    "SELECT organization_id FROM project WHERE id = $1", created.id
                )
            assert owner == ORG
        finally:
            await engine.dispose()

    _run(go())
