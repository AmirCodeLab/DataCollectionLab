"""Installing the builtin roles for one organisation (gate 1, A7).

The grants themselves are in `builtin_roles.sql` beside this file, and that is
the only place they are written. This module is how the two callers reach it —
`scripts/provision.py` for a real deployment and `scripts/seed_dev.py` for the
development database — so that "the same roles, everywhere" is one file being
executed twice rather than two lists being kept in step by hand.

`backend/tests/test_builtin_roles_have_one_definition.py` is what makes that
structural: it fails if any other file in `app/` or `scripts/` writes `role` or
`role_permission`.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

#: The one definition. Read at call time rather than import time so a test can
#: point at it, and so an error in the file surfaces where it is used.
DEFINITION = Path(__file__).with_name("builtin_roles.sql")


def statements() -> list[str]:
    """The file's statements, comments stripped.

    Split on `;` at the end of a line: these are two flat INSERTs with no
    function bodies and no string literals containing a semicolon, so the
    quote-and-dollar-aware splitter the migrations need would be ceremony
    here. If that stops being true this needs that splitter, and the test that
    executes this file is what would say so.
    """
    body = "\n".join(
        line for line in DEFINITION.read_text().splitlines() if not line.lstrip().startswith("--")
    )
    return [statement.strip() for statement in body.split(";") if statement.strip()]


async def install(connection: AsyncConnection | AsyncSession, organization_id: str) -> None:
    """Create the builtin roles and their grants for one organisation.

    Idempotent — every statement is `ON CONFLICT DO NOTHING` — so it is safe to
    re-run after a permission is added to the file, which is how an existing
    organisation gets one.

    Runs as whoever the caller is. `010_people.sql` makes `role` and
    `role_permission` the one thing no application principal may write, so in
    practice the caller holds the owner connection: standing up an
    organisation is provisioning, not a request (A1).
    """
    for statement in statements():
        await connection.execute(text(statement), {"org": organization_id})
