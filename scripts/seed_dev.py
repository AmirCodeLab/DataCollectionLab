#!/usr/bin/env python3
"""Seed the minimum development data a fresh checkout needs.

Creates exactly: one organisation, one project with its development, staging
and production environments, and the household_survey form with version 1
loaded from specs/examples/household_survey.json, **deployed to all three
environments**.

That file used to live in the app's own resources, because the app compiled it
at startup. It does not any more — a device gets its forms from this server
(sync §5), which is the whole point of form delivery — so the example lives
beside the specification it exercises and reaches a phone the way a customer's
form does. Nothing else — no devices (they
self-register on first sync, sync §4) and no users.

The deployment is not decoration. A published version that nothing deploys
appears in no device's manifest (sync §5), so a freshly seeded database would
hand every phone an empty form list and look, from the phone, exactly like a
broken sync.

Idempotent: rows are matched by natural key (slug, environment kind, form key,
version number) and only created when missing, so running it twice is safe.

The form goes through `forms.service.publish_version`, the same gate the API
uses, so the seed cannot install a form the publish endpoint would refuse. A
published version is immutable: if the bundled JSON no longer matches the
stored version, the script stops rather than updating — publish a new version
deliberately.

Run it after migrating. Any working directory and any interpreter will do —
the script finds the backend venv itself:

    alembic upgrade head   # from backend/
    python scripts/seed_dev.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"

# Settings resolve `.env` relative to the working directory, so run as if from
# backend/ no matter where the developer invoked this. Without it, seeding from
# the repo root would silently read a different .env — or none — and could
# migrate one database while seeding another.
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))


def _reexec_in_backend_venv() -> None:
    """Re-run under backend/.venv when the current interpreter lacks the deps.

    `python scripts/seed_dev.py` from the repo root would otherwise die on
    ModuleNotFoundError, because the dependencies live in backend/.venv. An
    interpreter that can already import them — an activated venv of the
    developer's own — is left alone.
    """
    try:
        import sqlalchemy  # noqa: F401
    except ModuleNotFoundError:
        pass
    else:
        return

    venv_python = BACKEND_DIR / ".venv" / "bin" / "python"
    already_tried = os.environ.get("DCP_SEED_REEXEC") == "1"
    if already_tried or not venv_python.exists() or Path(sys.executable) == venv_python:
        sys.exit(
            "Cannot import sqlalchemy, and no usable backend/.venv to fall back on.\n"
            "Install the backend dependencies first:\n"
            "    cd backend && pip install -e '.[dev]'"
        )
    # execve replaces the process image without flushing Python's buffers, so
    # this line is lost on a pipe unless it is flushed first.
    print(f"Re-running under {venv_python.relative_to(REPO_ROOT)}", flush=True)
    os.execve(  # noqa: S606 - fixed path, no shell
        str(venv_python),
        [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]],
        {**os.environ, "DCP_SEED_REEXEC": "1"},
    )


_reexec_in_backend_venv()

FORM_JSON = (
    REPO_ROOT / "specs/examples/household_survey.json"
)

# Fixed ids so every developer's database reads the same; creation is guarded
# by natural-key lookups, never by these ids.
ORG_ID, ORG_SLUG = "01ORGDEV", "dev"
PROJECT_ID, PROJECT_SLUG = "01PROJDEV", "dev"
ENVIRONMENT_IDS = {"development": "01ENVDEV", "staging": "01ENVSTG", "production": "01ENVPROD"}
FORM_ID = "01FORMHH"
FORM_VERSION_ID = "01FORMHHV1"


def _report(created: bool, kind: str, name: str) -> None:
    print(f"  {'created' if created else 'exists '}  {kind}: {name}")


async def seed(security_mode: str = "standard", database: str | None = None) -> None:
    # Deferred so sys.path points at backend/ before app imports resolve.
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import create_async_engine

    import app.infrastructure.registry  # noqa: F401  (completes Base.metadata)
    from app.core.config import get_settings
    from app.infrastructure.database import create_session_factory
    from app.modules.auth.models import PlatformOrganization
    from app.modules.forms import service as forms_service
    from app.modules.projects.models import Environment, Project

    ir: dict[str, Any] = json.loads(FORM_JSON.read_text())
    form_key, version = str(ir["formId"]), int(ir["version"])

    # A project's security mode is fixed at creation (encryption envelope §1),
    # so an encrypting project is a DIFFERENT project, not this one changed.
    # Seeding it into its own database also keeps device self-registration
    # unambiguous: a deployment with two active projects refuses to guess.
    url = get_settings().database_url
    if database is not None:
        from urllib.parse import urlsplit, urlunsplit

        url = urlunsplit(urlsplit(url)._replace(path=f"/{database}"))
    engine = create_async_engine(url)
    try:
        async with create_session_factory(engine)() as session, session.begin():
            org = (
                await session.execute(
                    select(PlatformOrganization).where(PlatformOrganization.slug == ORG_SLUG)
                )
            ).scalar_one_or_none()
            if org is None:
                # Isolation is by schema and tenant tables carry no
                # organization_id (ERD §1), so the organisation is not linked
                # to the project by a column — schema_name is the link. Phase 0
                # migrates everything into public, so that is where it points.
                org = PlatformOrganization(
                    id=ORG_ID, name="Dev Organisation", slug=ORG_SLUG, schema_name="public"
                )
                session.add(org)
            _report(org in session.new, "organisation", ORG_SLUG)

            project = (
                await session.execute(select(Project).where(Project.slug == PROJECT_SLUG))
            ).scalar_one_or_none()
            if project is None:
                project = Project(
                    id=PROJECT_ID,
                    name="Dev Project",
                    slug=PROJECT_SLUG,
                    security_mode=security_mode,
                )
                session.add(project)
            _report(project in session.new, "project", f"{PROJECT_SLUG} ({project.security_mode})")
            if project.security_mode != security_mode:
                # Never silently "fix" it: the mode decides whether everything
                # already collected is readable, and changing it would mean
                # re-encrypting or decrypting all of it.
                print(
                    f"  WARNING: project {PROJECT_SLUG} exists in "
                    f"{project.security_mode!r} mode, not {security_mode!r}. The mode is "
                    "fixed at creation — seed a fresh database to change it."
                )
            # The models carry no relationship()s, so flush between dependency
            # levels to control insert order.
            await session.flush()

            existing_kinds = set(
                (
                    await session.execute(
                        select(Environment.kind).where(Environment.project_id == project.id)
                    )
                ).scalars()
            )
            for kind, env_id in ENVIRONMENT_IDS.items():
                if kind not in existing_kinds:
                    session.add(Environment(id=env_id, project_id=project.id, kind=kind))
                _report(kind not in existing_kinds, "environment", kind)

            # Through the same gate the API uses, so the seed cannot install a
            # form the publish endpoint would refuse — including one with a
            # sensitivity leak (encryption envelope §5.2). A published version
            # is immutable, so drifted content is reported, never overwritten.
            try:
                published = await forms_service.publish_version(
                    session,
                    project_id=project.id,
                    ir=ir,
                    form_id=FORM_ID,
                    form_version_id=FORM_VERSION_ID,
                    # Every environment, because a dev device resolves to
                    # whichever the project has (production first) and nothing
                    # yet enrols one deliberately.
                    deploy_to=["development", "staging", "production"],
                )
            except forms_service.PublishRefused as refusal:
                print(f"  REFUSED  form_version: {form_key} v{version}")
                for violation in refusal.violations:
                    print(f"    - {violation}")
                raise SystemExit(
                    "The bundled form cannot be published. Fix it, or publish a new version."
                ) from refusal

            _report(published.created, "form_version", f"{form_key} v{version}")
            _report(True, "deployment", ", ".join(published.deployments) or "NONE")
            for warning in published.warnings:
                print(f"    warning: {warning}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--security-mode",
        default="standard",
        choices=["standard", "field_level", "project_e2e"],
        help="mode for the project when it is CREATED; fixed thereafter",
    )
    parser.add_argument("--database", help="override the database name from .env")
    args = parser.parse_args()

    target = args.database or "the development database"
    print(f"Seeding {FORM_JSON.relative_to(REPO_ROOT)} into {target}")
    asyncio.run(seed(args.security_mode, args.database))
    print("Done. Devices self-register on first sync; no further setup needed.")
