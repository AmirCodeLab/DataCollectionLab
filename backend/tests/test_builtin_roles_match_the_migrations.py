"""A provisioned organisation and a migrated one hold identical grants.

Gate 1, A7's second half. The lint beside this
(`test_builtin_roles_have_one_definition.py`) stops a second *copy* appearing.
This asks the question the copies existed to answer: does an organisation
standing up today get what an organisation that has been carried through every
migration has?

Two databases, built two ways:

* **Migrated** — the organisation exists before `0007`, so `008` seeds its
  roles, `010` adds `user.assign_role` to Supervisor and `016` adds
  `submission.review`. This is what the dev organisation is, and what every
  run this project has done has been against.
* **Provisioned** — a database at head, then `builtin_roles.install`. This is
  what a customer gets.

They must agree, role by role and permission by permission. When they do not,
the failure names which side has what, because "the roles differ" is not a
finding anybody can act on.

Measured before the refactor on 11 September: they already agreed. So this is
a regression guard rather than a reconciliation, and the value is in the day it
stops agreeing — the day somebody adds a permission to a migration and not to
the file, and a customer's Supervisor quietly cannot review.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.infrastructure.database import admin_connection, admin_url

MIGRATED_DB = "dcp_test_roles_migrated"
PROVISIONED_DB = "dcp_test_roles_provisioned"
ORG = "01ORGROLES"

#: The revision immediately before `008_identity.sql` creates the roles. The
#: organisation has to exist by then for the migrations to seed it, which is
#: the whole shape of "an organisation that has been carried through".
BEFORE_ROLES = "0007"


def _config(database: str) -> Any:
    from alembic.config import Config

    from tests.test_migrations import BACKEND_DIR

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", admin_url(database))
    return config


async def _recreate(database: str) -> None:
    async with admin_connection() as conn:
        await conn.execute(f"DROP DATABASE IF EXISTS {database} WITH (FORCE)")
        await conn.execute(f"CREATE DATABASE {database}")


async def _add_organization(database: str) -> None:
    """The organisation, at whichever revision the database is on.

    `schema_name` was `NOT NULL` in 001 and dropped by 008 — the migration that
    also creates the roles. So the same INSERT cannot serve both sides of this
    comparison, and which columns exist is itself a fact about where the
    database is.
    """
    async with admin_connection(database) as conn:
        has_schema_name = await conn.fetchval(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'platform_organization' AND column_name = 'schema_name'"
        )
        if has_schema_name:
            await conn.execute(
                "INSERT INTO platform_organization (id, name, slug, schema_name) "
                "VALUES ($1, 'Roles', 'roles', 'org_roles')",
                ORG,
            )
        else:
            await conn.execute(
                "INSERT INTO platform_organization (id, name, slug) "
                "VALUES ($1, 'Roles', 'roles')",
                ORG,
            )


async def _install(database: str) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.infrastructure.database import create_admin_engine
    from app.modules.auth import builtin_roles

    engine = create_admin_engine(database=database)
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            await builtin_roles.install(session, ORG)
    finally:
        await engine.dispose()


async def _grants(database: str) -> dict[str, set[str]]:
    async with admin_connection(database) as conn:
        rows = await conn.fetch(
            "SELECT r.name, p.permission FROM role r "
            "JOIN role_permission p ON p.role_id = r.id WHERE r.builtin"
        )
    grants: dict[str, set[str]] = {}
    for row in rows:
        grants.setdefault(row["name"], set()).add(row["permission"])
    return grants


async def _drop(*databases: str) -> None:
    async with admin_connection() as conn:
        for database in databases:
            await conn.execute(f"DROP DATABASE IF EXISTS {database} WITH (FORCE)")


@pytest.mark.db
def test_a_provisioned_organisation_matches_a_migrated_one() -> None:
    from alembic import command

    async def available() -> str | None:
        try:
            await _recreate(MIGRATED_DB)
            await _recreate(PROVISIONED_DB)
        except Exception as exc:  # noqa: BLE001 - any failure means "not available"
            return f"{type(exc).__name__}: {exc}"
        return None

    reason = asyncio.run(available())
    if reason is not None:
        pytest.skip(f"postgres not available: {reason}")

    try:
        # Alembic's env.py calls asyncio.run itself, so the upgrades cannot sit
        # inside a coroutine. Interleaved deliberately.
        command.upgrade(_config(MIGRATED_DB), BEFORE_ROLES)
        asyncio.run(_add_organization(MIGRATED_DB))
        command.upgrade(_config(MIGRATED_DB), "head")

        command.upgrade(_config(PROVISIONED_DB), "head")
        asyncio.run(_add_organization(PROVISIONED_DB))
        asyncio.run(_install(PROVISIONED_DB))

        migrated = asyncio.run(_grants(MIGRATED_DB))
        provisioned = asyncio.run(_grants(PROVISIONED_DB))
    finally:
        asyncio.run(_drop(MIGRATED_DB, PROVISIONED_DB))

    assert migrated, "the migrations seeded no roles at all — the fixture is wrong"

    differences = []
    for role in sorted(set(migrated) | set(provisioned)):
        only_migrated = sorted(migrated.get(role, set()) - provisioned.get(role, set()))
        only_provisioned = sorted(provisioned.get(role, set()) - migrated.get(role, set()))
        if only_migrated or only_provisioned:
            differences.append(
                f"  {role}:\n"
                f"    only in the MIGRATIONS: {', '.join(only_migrated) or '(none)'}\n"
                f"    only in builtin_roles.sql: {', '.join(only_provisioned) or '(none)'}"
            )

    assert not differences, (
        "A provisioned organisation and a migrated one hold different grants.\n"
        + "\n".join(differences)
        + "\n\nOne of them is wrong. A permission added to a migration and not "
        "to app/modules/auth/builtin_roles.sql means every customer "
        "provisioned from now on is missing it; the reverse means the dev "
        "database has one nothing else does."
    )
