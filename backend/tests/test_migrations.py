"""Migration 0001 must produce exactly the schema in migrations/schema/001_initial.sql.

The SQL file is normative. Two enforcement layers:

1. Without a database: every table the DDL creates has a matching
   op.create_table and op.drop_table in the migration.
2. Against a real Postgres (docker compose up -d postgres, tests marked
   ``db``): `alembic upgrade head` and executing the SQL file directly yield
   identical schemas — same tables, columns, types, defaults, constraints and
   indexes — and downgrade → upgrade round-trips cleanly. Self-hosted users
   depend on reversible migrations.

Tests marked ``db`` SKIP when Postgres is unreachable, and are deselectable
with `pytest -m "not db"`, so the rest of the suite does not need docker.
"""

from __future__ import annotations

import asyncio
import pathlib
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pytest

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
DDL_FILE = BACKEND_DIR / "migrations" / "schema" / "001_initial.sql"
MIGRATION_FILE = BACKEND_DIR / "migrations" / "versions" / "0001_initial_schema.py"

ALEMBIC_DB = "dcp_test_migration_alembic"
REFERENCE_DB = "dcp_test_migration_ref"

# Objects not created by our DDL: alembic bookkeeping and postgis internals.
_EXCLUDED_TABLES = ("alembic_version", "spatial_ref_sys")


def test_migration_creates_and_drops_every_table() -> None:
    """Every table in the normative DDL has an op.create_table in upgrade()
    and an op.drop_table in downgrade(). Runs without a database, so gross
    drift is caught even where docker is absent; the ``db`` test does the
    full column/constraint/index comparison.
    """
    source = MIGRATION_FILE.read_text()
    tables = set(re.findall(r"^CREATE TABLE (\w+)", DDL_FILE.read_text(), re.M))
    upgrade_body, downgrade_body = source.split("def downgrade")
    # Insensitive to quote style and line wrapping. A formatter that rewrites
    # '' to "" or breaks the call across lines changes nothing about which
    # tables the migration creates, and this test must not fail for it — it
    # exists to catch drift between the DDL and the migration, nothing else.
    created = set(re.findall(r"""op\.create_table\(\s*['"](\w+)['"]""", upgrade_body))
    dropped = set(re.findall(r"""op\.drop_table\(\s*['"](\w+)['"]""", downgrade_body))
    assert created == tables, f"missing: {tables - created}, extra: {created - tables}"
    assert dropped == tables, f"missing drops: {tables - dropped}, extra: {dropped - tables}"


# ---------------------------------------------------------------------------
# Live round-trip against a real Postgres
# ---------------------------------------------------------------------------


def _admin_dsn() -> str:
    """asyncpg DSN for the configured server, from app.core.config."""
    from app.core.config import get_settings

    url = get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    return url


def _dsn_for(database: str) -> str:
    parts = urlsplit(_admin_dsn())
    return urlunsplit(parts._replace(path=f"/{database}"))


def _sqlalchemy_url_for(database: str) -> str:
    parts = urlsplit(_admin_dsn())
    return urlunsplit(parts._replace(scheme="postgresql+asyncpg", path=f"/{database}"))


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


async def _try_connect() -> str | None:
    import asyncpg

    try:
        conn = await asyncpg.connect(_admin_dsn(), timeout=3)
    except Exception as exc:  # noqa: BLE001 - any failure means "not available"
        return f"{type(exc).__name__}: {exc}"
    await conn.close()
    return None


async def _recreate_databases() -> None:
    import asyncpg

    conn = await asyncpg.connect(_admin_dsn())
    try:
        for db in (ALEMBIC_DB, REFERENCE_DB):
            await conn.execute(f"DROP DATABASE IF EXISTS {db} WITH (FORCE)")
            await conn.execute(f"CREATE DATABASE {db}")
    finally:
        await conn.close()


async def _drop_databases() -> None:
    import asyncpg

    conn = await asyncpg.connect(_admin_dsn())
    try:
        for db in (ALEMBIC_DB, REFERENCE_DB):
            await conn.execute(f"DROP DATABASE IF EXISTS {db} WITH (FORCE)")
    finally:
        await conn.close()


async def _execute_sql(database: str, sql: str) -> None:
    import asyncpg

    conn = await asyncpg.connect(_dsn_for(database))
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


async def _snapshot(database: str) -> dict[str, Any]:
    """Canonical description of the public schema: tables, columns, types,
    defaults, constraints and indexes, straight from pg_catalog."""
    import asyncpg

    conn = await asyncpg.connect(_dsn_for(database))
    try:
        tables = [
            r["relname"]
            for r in await conn.fetch(
                """
                SELECT c.relname FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relkind = 'r'
                  AND c.relname != ALL($1::text[])
                ORDER BY c.relname
                """,
                list(_EXCLUDED_TABLES),
            )
        ]
        columns = await conn.fetch(
            """
            SELECT c.relname AS table, a.attname AS column,
                   format_type(a.atttypid, a.atttypmod) AS type,
                   a.attnotnull AS not_null,
                   pg_get_expr(d.adbin, d.adrelid) AS default
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
            WHERE n.nspname = 'public' AND c.relkind = 'r'
              AND a.attnum > 0 AND NOT a.attisdropped
              AND c.relname != ALL($1::text[])
            ORDER BY c.relname, a.attnum
            """,
            list(_EXCLUDED_TABLES),
        )
        constraints = await conn.fetch(
            """
            SELECT c.relname AS table, con.conname AS name,
                   pg_get_constraintdef(con.oid) AS definition
            FROM pg_constraint con
            JOIN pg_class c ON c.oid = con.conrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relname != ALL($1::text[])
            ORDER BY c.relname, con.conname
            """,
            list(_EXCLUDED_TABLES),
        )
        indexes = await conn.fetch(
            """
            SELECT tablename AS table, indexname AS name, indexdef AS definition
            FROM pg_indexes
            WHERE schemaname = 'public' AND tablename != ALL($1::text[])
            ORDER BY tablename, indexname
            """,
            list(_EXCLUDED_TABLES),
        )
        extensions = [
            r["extname"]
            for r in await conn.fetch("SELECT extname FROM pg_extension ORDER BY extname")
        ]
    finally:
        await conn.close()

    return {
        "tables": tables,
        "columns": [dict(r) for r in columns],
        "constraints": [dict(r) for r in constraints],
        "indexes": [dict(r) for r in indexes],
        "extensions": extensions,
    }


def _alembic_config(database: str) -> Any:
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", _sqlalchemy_url_for(database))
    return cfg


@pytest.fixture(scope="module")
def postgres() -> Any:
    reason = _run(_try_connect())
    if reason is not None:
        pytest.skip(
            f"Postgres unavailable ({reason}) — start it with: docker compose up -d postgres"
        )
    _run(_recreate_databases())
    yield None
    _run(_drop_databases())


@pytest.mark.db
def test_migration_up_down_up_matches_normative_schema(postgres: Any) -> None:
    from alembic import command

    ddl = DDL_FILE.read_text()
    cfg = _alembic_config(ALEMBIC_DB)

    # Reference: the normative file executed directly.
    _run(_execute_sql(REFERENCE_DB, ddl))
    reference = _run(_snapshot(REFERENCE_DB))
    assert reference["tables"], "reference DDL created no tables?"

    # Up: alembic must produce the identical schema, postgis included.
    command.upgrade(cfg, "head")
    migrated = _run(_snapshot(ALEMBIC_DB))
    assert "postgis" in migrated["extensions"]
    for key in ("tables", "columns", "constraints", "indexes", "extensions"):
        assert migrated[key] == reference[key], f"schema mismatch in {key}"

    # Down: nothing of ours may remain. Reversibility is a hard requirement —
    # self-hosted users run old versions.
    command.downgrade(cfg, "base")
    downgraded = _run(_snapshot(ALEMBIC_DB))
    assert downgraded["tables"] == [], f"downgrade left tables behind: {downgraded['tables']}"
    assert "postgis" not in downgraded["extensions"]

    # Up again: the downgrade left a state a fresh upgrade fully rebuilds.
    command.upgrade(cfg, "head")
    remigrated = _run(_snapshot(ALEMBIC_DB))
    for key in ("tables", "columns", "constraints", "indexes", "extensions"):
        assert remigrated[key] == reference[key], f"schema mismatch after re-upgrade in {key}"
