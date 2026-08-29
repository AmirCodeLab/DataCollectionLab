#!/usr/bin/env python3
"""TEST ONLY — install a fixed project keypair so encryption can be exercised.

    python scripts/dev_project_key.py                      # dev project, primary
    python scripts/dev_project_key.py --role backup
    python scripts/dev_project_key.py --project 01PROJDEV --database dcp_dev_e2e
    python scripts/dev_project_key.py --print-private       # to decrypt locally

################################################################################
#  THE PRIVATE KEY BELOW IS FIXED, PUBLIC, AND IN VERSION CONTROL.             #
#  Anything encrypted to it is readable by anyone with this repository.        #
#  It exists so a developer can drive the encrypted path end to end without    #
#  the console. It must never reach a machine holding real data.               #
################################################################################

The real flow is the console page: the keypair is generated in the browser with
WebCrypto and the private half is downloaded by the user and never transmitted
(encryption envelope §4.1). This script exists because that flow deliberately
cannot be automated — the whole point is that no program on the server side ever
holds the private key — and a developer still needs to exercise encryption
locally.

The guard rails are real, not decorative: the script refuses to run against a
non-development environment, refuses a project that already holds a key it did
not install, and labels every key it writes so anyone reading the database or
the console sees what it is. The server enforces the same rule from its side —
`app/modules/crypto/published_test_keys.py` lists these public halves and
refuses to register or hand out one of them outside development, which is what
catches a development database that later gets promoted.

To read back what was encrypted to these keys:

    python scripts/decrypt_submission.py <submission-id> --test-key primary

Envelope §12 requires fixed conformance keys to stay inside conformance/. This
key is NOT one of those — it is distinct from every vector key, and is confined
to this development script, which is the same rule applied to the same hazard.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"

sys.path.insert(0, str(BACKEND_DIR))


def _reexec_in_backend_venv() -> None:
    """Re-run under backend/.venv when the current interpreter lacks the deps."""
    try:
        import sqlalchemy  # noqa: F401
    except ModuleNotFoundError:
        pass
    else:
        return

    venv_python = BACKEND_DIR / ".venv" / "bin" / "python"
    already_tried = os.environ.get("DCP_DEVKEY_REEXEC") == "1"
    if already_tried or not venv_python.exists() or Path(sys.executable) == venv_python:
        sys.exit(
            "Cannot import sqlalchemy, and no usable backend/.venv to fall back on.\n"
            "    cd backend && pip install -e '.[dev]'"
        )
    print(f"Re-running under {venv_python.relative_to(REPO_ROOT)}", flush=True)
    os.execve(
        str(venv_python),
        [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]],
        {**os.environ, "DCP_DEVKEY_REEXEC": "1"},
    )


# TEST ONLY. Fixed X25519 private scalars, public by design — that is what makes
# a local encrypted round trip reproducible. One per role so multi-recipient
# wrapping (§4.3) can be exercised too.
TEST_ONLY_PRIVATE_KEYS: dict[str, str] = {
    "primary": "a0c1d2e3f405162738495a6b7c8d9eaf b0c1d2e3f405162738495a6b7c8d9ea0".replace(
        " ", ""
    ),
    "backup": "b1d2e3f405162738495a6b7c8d9eafb0 c1d2e3f405162738495a6b7c8d9eafb1".replace(
        " ", ""
    ),
    "recovery": "c2e3f405162738495a6b7c8d9eafb0c1 d2e3f405162738495a6b7c8d9eafb0c2".replace(
        " ", ""
    ),
}

LABEL_PREFIX = "TEST ONLY — scripts/dev_project_key.py"

BANNER = """
================================================================================
  TEST ONLY KEY INSTALLED
  The private key is fixed and lives in scripts/dev_project_key.py, which is in
  version control. Anything encrypted to it is readable by anyone with a copy
  of this repository. Never point a device holding real data at this project.
================================================================================
"""


def _public_hex(private_hex: str) -> str:
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

    private = X25519PrivateKey.from_private_bytes(bytes.fromhex(private_hex))
    return private.public_key().public_bytes_raw().hex()


async def install(project_id: str | None, roles: list[str], database: str | None) -> None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import app.infrastructure.registry  # noqa: F401  (completes Base.metadata)
    from app.core.config import get_settings
    from app.core.ulid import new_ulid
    from app.modules.crypto.models import ProjectKey
    from app.modules.projects.models import Project

    settings = get_settings()
    if settings.environment != "development":
        sys.exit(
            f"Refusing to run: environment is {settings.environment!r}, not 'development'.\n"
            "This installs a private key that is published in the repository."
        )

    url = settings.database_url
    if database is not None:
        from urllib.parse import urlsplit, urlunsplit

        url = urlunsplit(urlsplit(url)._replace(path=f"/{database}"))
    print(f"Database: {url.rsplit('@', 1)[-1]}")

    engine = create_async_engine(url)
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            if project_id is None:
                projects = (
                    (
                        await session.execute(
                            select(Project)
                            .where(Project.archived_at.is_(None))
                            .order_by(Project.created_at, Project.id)
                        )
                    )
                    .scalars()
                    .all()
                )
                if not projects:
                    sys.exit("No active project. Run scripts/seed_dev.py first.")
                if len(projects) > 1:
                    listed = "\n".join(f"    {p.id}  {p.slug}  ({p.security_mode})" for p in projects)
                    sys.exit(
                        f"Several active projects; name one with --project:\n{listed}"
                    )
                project = projects[0]
            else:
                project = await session.get(Project, project_id)
                if project is None:
                    sys.exit(f"No project {project_id}.")

            print(f"Project:  {project.id}  {project.slug}  (mode: {project.security_mode})")
            if project.security_mode == "standard":
                print(
                    "  NOTE: this project is in 'standard' mode, so nothing will be\n"
                    "        encrypted. The mode is fixed at creation — to exercise\n"
                    "        encryption, create a project in field_level or project_e2e."
                )

            existing = (
                (
                    await session.execute(
                        select(ProjectKey).where(
                            ProjectKey.project_id == project.id,
                            ProjectKey.revoked_at.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            foreign = [k for k in existing if not k.label.startswith(LABEL_PREFIX)]
            if foreign:
                # A project with a real recipient is a project someone may be
                # trusting. Adding a published private key to its set would make
                # every future submission readable, silently.
                listed = "\n".join(f"    {k.id}  {k.key_role}  {k.label!r}" for k in foreign)
                sys.exit(
                    "Refusing to run: this project already holds keys this script did "
                    f"not install:\n{listed}\n"
                    "Wrapping to a published test key beside a real one would make "
                    "every future submission readable by anyone."
                )

            by_public = {bytes(k.public_key).hex(): k for k in existing}
            for role in roles:
                public_hex = _public_hex(TEST_ONLY_PRIVATE_KEYS[role])
                if public_hex in by_public:
                    key = by_public[public_hex]
                    print(f"  exists   {role:<8} {key.id}  {public_hex}")
                    continue
                key = ProjectKey(
                    id=new_ulid(),
                    project_id=project.id,
                    public_key=bytes.fromhex(public_hex),
                    key_role=role,
                    label=f"{LABEL_PREFIX} ({role})",
                )
                session.add(key)
                await session.flush()
                print(f"  created  {role:<8} {key.id}  {public_hex}")
    finally:
        await engine.dispose()


def main() -> None:
    # Both of these belong to running as a program, not to importing the module:
    # scripts/decrypt_submission.py reads TEST_ONLY_PRIVATE_KEYS from here, and
    # an import that re-executes a different interpreter — with the importer's
    # own argv — would run this installer when nobody asked for it. The chdir is
    # here for the same reason; it exists so pydantic-settings finds backend/.env.
    os.chdir(BACKEND_DIR)
    _reexec_in_backend_venv()

    parser = argparse.ArgumentParser(
        description="TEST ONLY: install a fixed project keypair for local development.",
    )
    parser.add_argument("--project", help="project id (default: the sole active project)")
    parser.add_argument(
        "--role",
        action="append",
        choices=sorted(TEST_ONLY_PRIVATE_KEYS),
        help="repeatable; default installs all three so multi-recipient wrapping works",
    )
    parser.add_argument("--database", help="override the database name from .env")
    parser.add_argument(
        "--print-private",
        action="store_true",
        help="print the fixed private keys, for decrypting locally",
    )
    args = parser.parse_args()

    roles = args.role or sorted(TEST_ONLY_PRIVATE_KEYS)
    print(BANNER)
    asyncio.run(install(args.project, roles, args.database))

    if args.print_private:
        print("\nTEST ONLY private keys (hex, raw 32-byte X25519 scalars):")
        for role in roles:
            print(f"  {role:<8} {TEST_ONLY_PRIVATE_KEYS[role]}")
    else:
        print("\nPrivate keys not printed. Re-run with --print-private to decrypt locally.")


if __name__ == "__main__":
    main()
