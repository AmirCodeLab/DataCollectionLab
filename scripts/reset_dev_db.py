#!/usr/bin/env python3
"""Recreate the development database from nothing: drop, create, migrate,
give the application role its login, and optionally seed.

    python scripts/reset_dev_db.py            # drop, create, upgrade head
    python scripts/reset_dev_db.py --seed     # ...and scripts/seed_dev.py

## Why recreate rather than migrate

A development database drifts. Migrations get run from a branch and then the
branch is rebased; a column is added by hand to try something; a downgrade
half-fails and leaves the stamp behind the schema. The local `dcp` database
was found on 9 September 2026 stamped at 0002 while already holding columns
from 0003 onward, so `alembic upgrade` failed on a duplicate column and
`alembic downgrade` failed on a foreign key — both directions closed, and the
first person to meet it would read it as a broken migration rather than a
stale database. There is nothing in a development database worth reconciling
by hand: the seed recreates everything it should hold. So the fix is to
recreate it, and this script is that fix written down, because the next
drift is a matter of time.

Runs as the owner (`DATABASE_ADMIN_URL`), from the maintenance database,
because the one being dropped may be the one the admin URL names. The one
thing it does that a migration cannot is give `dcp_app` LOGIN with the
password `DATABASE_URL` carries: roles are cluster-wide and a migration is a
fact about one database, so the login is a deployment decision, made here
for development and in `scripts/db_app_role.sql` for a fresh compose volume.
"""

from __future__ import annotations

import argparse
import asyncio
import pathlib
import sys
from urllib.parse import urlsplit

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seed", action="store_true", help="run scripts/seed_dev.py afterwards")
    parser.add_argument(
        "--database",
        default=None,
        help="database to recreate (default: the one DATABASE_ADMIN_URL names)",
    )
    arguments = parser.parse_args()

    from alembic import command
    from alembic.config import Config

    from app.core.config import get_settings
    from app.infrastructure.database import (
        admin_url,
        ensure_app_role_can_login,
        recreate_database,
    )

    settings = get_settings()
    if settings.environment != "development":
        sys.exit(
            f"Refusing to run: environment is {settings.environment!r}, not 'development'.\n"
            "This drops a database."
        )
    database = arguments.database or urlsplit(settings.database_admin_url).path.lstrip("/")

    print(f"recreating {database} on {urlsplit(settings.database_admin_url).hostname}")
    asyncio.run(recreate_database(database))

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", admin_url(database))
    command.upgrade(cfg, "head")
    print("  migrated to head")

    asyncio.run(ensure_app_role_can_login(database=database))
    print("  dcp_app can log in with the password in DATABASE_URL")

    if arguments.seed:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from seed_dev import seed

        asyncio.run(seed(database=database))
    return 0


if __name__ == "__main__":
    sys.exit(main())
