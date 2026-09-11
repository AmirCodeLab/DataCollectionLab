#!/usr/bin/env python
"""Stand up an organisation and its first administrator (gate 1).

Run **on the server**, the way `alembic upgrade` is run, by a person at a
terminal. This is the one act in the system that cannot be a request: an
organisation cannot be created under row-level security, because there is no
principal until it exists (gate 1, A1). So it holds the owner connection, and
it is a command rather than a route for exactly that reason.

    python scripts/provision.py --slug rcons --name "RCons" \\
        --admin-username fatima --admin-name "Fatima Iqbal"

It creates four things and stops:

  1. the organisation;
  2. its four builtin roles and their permissions, from the one definition in
     `app/modules/auth/builtin_roles.sql`;
  3. the first administrator, with an active membership and the
     organisation-wide Admin grant;
  4. an `audit_event` recording that it ran.

**Not** a project, its environments or its keys. Those are ordinary
authenticated routes, because by then an administrator exists and can be
refused like anybody else (A2). `POST /api/v1/projects`, or the console's
New project.

--------------------------------------------------------------------------
What stops this being run casually against production (A10, analysis §3.4)
--------------------------------------------------------------------------

**It cannot run without a terminal.** The password is read from a TTY and is
never an argument, never an environment variable, never printed. With no TTY
it refuses. That single property takes out the whole class of accidents: a
convenience wrapper cannot supply the password, nor can a CI step, nor
`ssh host 'provision …'`, nor cron. Automating it means first defeating it,
which turns an accident into a decision somebody made.

**It is a no-op on an organisation that already exists.** Creating is all it
does. Pointed at a live database it finds the organisation, says so, and
changes nothing — so the worst case of the mistake this section is about is a
message on a terminal.

**It refuses a database that is not at migration head**, and **refuses a slug
that does not match `ORGANIZATION_SLUG`**, naming both. A laptop's stack is
rarely at production's revision, and a production deployment's slug is not
`dev`.

**And what none of that buys.** A person holding `DATABASE_ADMIN_URL` for
production can do anything to it with or without this script. That credential
is the boundary; no script can be the thing that protects it. These guards make
the careless path fail closed and the deliberate path visible.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.ulid import new_ulid  # noqa: E402
from app.infrastructure.database import create_admin_engine  # noqa: E402
from app.modules.auth import builtin_roles  # noqa: E402
from app.modules.auth.passwords import hash_password  # noqa: E402


class Refused(Exception):
    """A refusal with a sentence saying what to do about it."""


def _password_from_a_terminal() -> str:
    """The A10 guard, and the only one that takes out automation wholesale.

    `getpass` reads `/dev/tty` where it can. `sys.stdin.isatty()` is the check
    that matters: a pipe, a heredoc, a CI runner and a detached ssh command all
    fail it, and none of them can be talked out of failing it by an argument
    this script accepts — because it accepts none.
    """
    if not sys.stdin.isatty():
        raise Refused(
            "This is not a terminal.\n"
            "The administrator's password is typed, never passed — there is no "
            "flag and no environment variable for it. That is deliberate: it is "
            "what stops this being wrapped in a convenience script and pointed "
            "at production by accident. Run it in an interactive shell on the "
            "server."
        )
    first = getpass.getpass("Password for the first administrator: ")
    if len(first) < 12:
        raise Refused("That is shorter than twelve characters. Use a longer one.")
    if first != getpass.getpass("Again: "):
        raise Refused("The two did not match.")
    return first


async def _check_and_provision(
    *, slug: str, name: str, username: str, display_name: str, password: str, database: str | None
) -> str:
    engine = create_admin_engine(database=database)
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            revision = (
                await session.execute(text("SELECT max(version_num) FROM alembic_version"))
            ).scalar_one_or_none()
            head = _head_revision()
            if revision != head:
                raise Refused(
                    f"This database is at migration {revision or 'nothing'} and the "
                    f"repository's head is {head}.\n"
                    "Provisioning a database whose schema is not the one this code "
                    "expects makes rows that may not survive the next upgrade. Run "
                    "`alembic upgrade head` first — and if that is a surprise, check "
                    "which database this is pointed at."
                )

            existing = (
                await session.execute(
                    text("SELECT id FROM platform_organization WHERE slug = :slug"),
                    {"slug": slug},
                )
            ).scalar_one_or_none()
            if existing is not None:
                raise Refused(
                    f"An organisation with the slug {slug!r} already exists "
                    f"({existing}). This script only creates; it will not touch it.\n"
                    "Add people through the console, or with the People API."
                )

            organization_id = new_ulid()
            await session.execute(
                text(
                    "INSERT INTO platform_organization (id, name, slug) "
                    "VALUES (:id, :name, :slug)"
                ),
                {"id": organization_id, "name": name, "slug": slug},
            )
            # The one definition (A7). Never a copy of the list.
            await builtin_roles.install(session, organization_id)

            person_id = new_ulid()
            await session.execute(
                text(
                    "INSERT INTO platform_user "
                    "(id, organization_id, username, display_name, password_hash) "
                    "VALUES (:id, :org, :username, :display_name, :hash)"
                ),
                {
                    "id": person_id,
                    "org": organization_id,
                    "username": username,
                    "display_name": display_name,
                    "hash": hash_password(password),
                },
            )
            # No `id`: the membership is keyed on (organization, person).
            # `org_role` predates item 1's roles and is not what grants
            # anything — `user_role` below is. `status` active because this
            # person is the one who approves everybody else.
            await session.execute(
                text(
                    "INSERT INTO platform_org_membership "
                    "(organization_id, user_id, org_role, status) "
                    "VALUES (:org, :user, 'owner', 'active')"
                ),
                {"org": organization_id, "user": person_id},
            )
            await session.execute(
                text(
                    "INSERT INTO user_role (id, user_id, role_id, scope_kind) "
                    "VALUES (:id, :user, :role, 'organization')"
                ),
                {
                    "id": new_ulid(),
                    "user": person_id,
                    "role": f"{organization_id}_admin",
                },
            )
            # `audit_event` has existed since 001 with no writer. Provisioning
            # is the right first one: a run nobody can find afterwards is how
            # two administrators appear and nobody knows which is which.
            await session.execute(
                text(
                    "INSERT INTO audit_event "
                    "(id, organization_id, subject_type, subject_id, action, detail) "
                    "VALUES (:id, :org, 'platform_organization', :org, "
                    "'organization.provisioned', CAST(:detail AS jsonb))"
                ),
                {
                    "id": new_ulid(),
                    "org": organization_id,
                    "detail": json.dumps(
                        {
                            "slug": slug,
                            "administrator": username,
                            "administratorId": person_id,
                            "by": "scripts/provision.py",
                        }
                    ),
                },
            )
            return organization_id
    finally:
        await engine.dispose()


def _head_revision() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    backend = Path(__file__).resolve().parents[1] / "backend"
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "migrations"))
    return ScriptDirectory.from_config(config).get_current_head() or "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create an organisation and its first administrator.",
        epilog="The password is typed, not passed. There is no flag for it.",
    )
    parser.add_argument("--slug", required=True, help="must match ORGANIZATION_SLUG")
    parser.add_argument("--name", required=True, help="the organisation's display name")
    parser.add_argument("--admin-username", required=True)
    parser.add_argument("--admin-name", required=True, help="the person's display name")
    parser.add_argument("--database", default=None, help="override the database name")
    arguments = parser.parse_args()

    configured = get_settings().organization_slug
    try:
        if arguments.slug != configured:
            raise Refused(
                f"--slug is {arguments.slug!r} and ORGANIZATION_SLUG is {configured!r}.\n"
                "This deployment resolves one organisation, from that setting. An "
                "organisation provisioned under any other slug exists, holds a "
                "working administrator, and cannot be reached by the login.\n"
                "Set ORGANIZATION_SLUG to match, or pass the slug this deployment "
                "is configured for."
            )
        password = _password_from_a_terminal()
        organization_id = asyncio.run(
            _check_and_provision(
                slug=arguments.slug,
                name=arguments.name,
                username=arguments.admin_username,
                display_name=arguments.admin_name,
                password=password,
                database=arguments.database,
            )
        )
    except Refused as refusal:
        print(f"\nRefused. {refusal}", file=sys.stderr)
        return 2

    print(f"\norganisation  {arguments.name} ({arguments.slug})  {organization_id}")
    print(f"administrator {arguments.admin_name} ({arguments.admin_username})")
    print("roles         Admin, Programme manager, Supervisor, Enumerator")
    print("\nSign in as that administrator and create the project from the console.")
    print("Before it collects real data in an encrypting mode, read docs/key-custody.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
