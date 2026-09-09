"""There is one connection factory, and this is what says so.

ERD §1: every table is behind a policy that reads a principal the connection
sets, and the application connects as a role the policies bind. Both are
properties of *the* connection — so a second way to make one is a route
around every policy at once, and it is the shape the repository has already
paid for once: an export script with its own engine is "the one report
nobody thought of".

The lint is in the shape of `test_form_version_has_one_writer.py`: walk the
source, name the file and line, and refuse where the second route is
written rather than find it where it leaks. Three things count as a route:
importing an engine constructor from SQLAlchemy, importing asyncpg at all,
and a `postgresql://` literal — the last because a URL nobody can connect
with is not a URL anyone writes down.

The named exemptions are the factory itself, the settings module that holds
the default URLs the factory reads, and `migrations/env.py`, which runs as
the owner by design and is outside the scanned roots.
"""

from __future__ import annotations

import ast
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]

#: The roots the rule applies to. Tests provision scratch databases as the
#: owner and are not a request; they are held to the rule differently — the
#: API under test connects through the factory (`identity_fixtures`).
ROOTS = (REPO / "backend" / "app", REPO / "scripts")

THE_FACTORY = "backend/app/infrastructure/database.py"

#: An exemption is a decision with a reason beside it.
EXEMPT = {
    THE_FACTORY: "the factory",
    "backend/app/core/config.py": "the default URLs are settings; the factory reads them",
}

_ENGINE_CONSTRUCTORS = {"create_async_engine", "create_engine"}
_URL_SCHEMES = ("postgresql://", "postgresql+asyncpg://", "postgres://")


def _routes_in(tree: ast.AST) -> list[tuple[int, str]]:
    """(line, what) for every second route to a connection in one module."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.split(".")[0] == "sqlalchemy":
                for alias in node.names:
                    if alias.name in _ENGINE_CONSTRUCTORS:
                        found.append((node.lineno, f"imports {alias.name} from {module}"))
            if module.split(".")[0] == "asyncpg":
                found.append((node.lineno, f"imports from {module}"))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "asyncpg":
                    found.append((node.lineno, f"imports {alias.name}"))
        elif isinstance(node, ast.Attribute) and node.attr in _ENGINE_CONSTRUCTORS:
            if isinstance(node.value, ast.Name) and node.value.id == "sqlalchemy":
                found.append((node.lineno, f"calls sqlalchemy.{node.attr}"))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if any(scheme in node.value for scheme in _URL_SCHEMES):
                found.append((node.lineno, "holds a postgresql:// literal"))
    # ast.walk is breadth-first; a finding is reported in source order.
    return sorted(found)


def _second_routes() -> list[str]:
    offenders: list[str] = []
    for root in ROOTS:
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            relative = str(path.relative_to(REPO))
            if relative in EXEMPT:
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            offenders += [f"{relative}:{line} {what}" for line, what in _routes_in(tree)]
    return offenders


def test_no_connection_is_made_outside_the_factory() -> None:
    offenders = _second_routes()
    assert offenders == [], (
        "a connection to the database is made outside the factory:\n  "
        + "\n  ".join(offenders)
        + f"\n\nEvery policy in the schema reads a principal that {THE_FACTORY} sets, on a "
        "role that it checks. A second engine, a raw asyncpg connection or a URL of its "
        "own is a route around all of them at once. Use create_engine / session_as / "
        "session_for_organization for a request, and create_admin_engine / "
        "admin_connection for provisioning (ERD §1)."
    )


def test_the_exemptions_exist() -> None:
    """An exemption naming a file that is gone is a stale decision, and the
    lint would quietly stop guarding whatever replaced it."""
    for relative in EXEMPT:
        assert (REPO / relative).is_file(), f"exempt file does not exist: {relative}"


def test_this_lint_can_see_every_shape_it_forbids() -> None:
    """A lint that matches nothing is indistinguishable from a clean tree."""
    snippet = (
        "import asyncpg\n"
        "from asyncpg import connect\n"
        "from sqlalchemy.ext.asyncio import create_async_engine\n"
        "from sqlalchemy import create_engine\n"
        "import sqlalchemy\n"
        "engine = sqlalchemy.create_engine('sqlite://')\n"
        "URL = 'postgresql+asyncpg://dcp:dcp@localhost/dcp'\n"
        "OTHER = 'postgresql://x'\n"
    )
    seen = [what for _line, what in _routes_in(ast.parse(snippet))]
    assert seen == [
        "imports asyncpg",
        "imports from asyncpg",
        "imports create_async_engine from sqlalchemy.ext.asyncio",
        "imports create_engine from sqlalchemy",
        "calls sqlalchemy.create_engine",
        "holds a postgresql:// literal",
        "holds a postgresql:// literal",
    ]

    # ...and the factory's own function, imported from the factory, is not a route.
    clean = "from app.infrastructure.database import create_engine, session_as\n"
    assert _routes_in(ast.parse(clean)) == []
