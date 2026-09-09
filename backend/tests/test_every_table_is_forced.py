"""Every table has row-level security enabled, forced, and a policy — and
exactly the named tables carry the organisation.

ERD §1: isolation is a policy in the database, not a filter in a query. That
holds only if no table is open, and the migration is where it goes wrong
silently: a table added later with no policy is readable by every tenant, and
a policy that exists without FORCE is bypassed by the table's owner while it
looks correct in psql — visible in every diagnostic and absent where it
matters. So this test enumerates `pg_tables` on the migrated database and
FAILS CLOSED: a table it does not know with no policy is a failure, not a
skip. The exemptions are named, with the reason.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tests.test_migrations import (
    ALEMBIC_DB,
    _alembic_config,
    _dsn_for,
    postgres,  # noqa: F401 - the module-scoped fixture that provisions the database
)

# The only tables the application does not own. Nothing else is exempt, and a
# name added here is a decision with a reason beside it.
EXEMPT = {
    # Alembic's own: no tenant data, never read by the application.
    "alembic_version",
    # PostGIS's own, owned by the extension; the application never reads it.
    "spatial_ref_sys",
}

# The discriminators (ERD §1). Nothing else may carry the column — a second
# copy is a second place the organisation can be wrong.
CARRIES_ORGANIZATION = {
    "project",
    "platform_user",
    "platform_org_membership",
    "role",
    "audit_event",
}


async def _catalogue() -> list[dict[str, Any]]:
    import asyncpg

    conn = await asyncpg.connect(_dsn_for(ALEMBIC_DB))
    try:
        rows = await conn.fetch(
            """
            SELECT c.relname AS name,
                   c.relrowsecurity AS enabled,
                   c.relforcerowsecurity AS forced,
                   (SELECT count(*) FROM pg_policies p
                     WHERE p.schemaname = 'public' AND p.tablename = c.relname) AS policies,
                   EXISTS (SELECT 1 FROM information_schema.columns col
                            WHERE col.table_schema = 'public' AND col.table_name = c.relname
                              AND col.column_name = 'organization_id') AS carries_org
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'r'
            ORDER BY c.relname
            """
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


@pytest.fixture(scope="module")
def migrated(postgres: Any) -> list[dict[str, Any]]:  # noqa: F811 - pytest injects the fixture
    from alembic import command

    command.upgrade(_alembic_config(ALEMBIC_DB), "head")
    return asyncio.run(_catalogue())


@pytest.mark.db
def test_every_table_is_enabled_forced_and_has_a_policy(migrated: list[dict[str, Any]]) -> None:
    open_tables = [
        f"{t['name']} (enabled={t['enabled']}, forced={t['forced']}, policies={t['policies']})"
        for t in migrated
        if t["name"] not in EXEMPT
        and not (t["enabled"] and t["forced"] and t["policies"] >= 1)
    ]
    assert open_tables == [], (
        "tables readable around the isolation policy — a migration added one "
        f"without securing it, or FORCE was dropped: {open_tables}"
    )


@pytest.mark.db
def test_the_exemptions_are_real_and_nothing_else_is_unknown(migrated: list[dict[str, Any]]) -> None:
    """An exemption that names a table which does not exist is a stale
    decision, and the test would silently stop guarding whatever replaced it."""
    names = {t["name"] for t in migrated}
    assert EXEMPT <= names, f"exempt tables that do not exist: {sorted(EXEMPT - names)}"


@pytest.mark.db
def test_exactly_the_discriminators_carry_the_organisation(migrated: list[dict[str, Any]]) -> None:
    carrying = {t["name"] for t in migrated if t["carries_org"]}
    assert carrying == CARRIES_ORGANIZATION, (
        f"organization_id on {sorted(carrying - CARRIES_ORGANIZATION)} that should resolve "
        f"through a parent; missing from {sorted(CARRIES_ORGANIZATION - carrying)}"
    )
