#!/usr/bin/env python3
"""Seed the minimum development data a fresh checkout needs.

Creates exactly: one organisation, one project with its development, staging
and production environments, and the household_survey form with version 1
loaded from the same JSON the app bundles
(clients/composeApp/src/commonMain/composeResources/files/household_survey.json).
Nothing else — no devices (they self-register on first sync, sync §4) and no
users.

Idempotent: rows are matched by natural key (slug, environment kind, form key,
version number) and only created when missing, so running it twice is safe.
A published form version is immutable; if the bundled JSON no longer matches
the stored version, the script warns instead of updating — publish a new
version deliberately.

Run it after migrating. Any working directory and any interpreter will do —
the script finds the backend venv itself:

    alembic upgrade head   # from backend/
    python scripts/seed_dev.py
"""

from __future__ import annotations

import asyncio
import hashlib
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
    REPO_ROOT / "clients/composeApp/src/commonMain/composeResources/files/household_survey.json"
)

# Fixed ids so every developer's database reads the same; creation is guarded
# by natural-key lookups, never by these ids.
ORG_ID, ORG_SLUG = "01ORGDEV", "dev"
PROJECT_ID, PROJECT_SLUG = "01PROJDEV", "dev"
ENVIRONMENT_IDS = {"development": "01ENVDEV", "staging": "01ENVSTG", "production": "01ENVPROD"}
FORM_ID = "01FORMHH"
FORM_VERSION_ID = "01FORMHHV1"


def _checksum(ir: dict[str, Any]) -> str:
    canonical = json.dumps(ir, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def _report(created: bool, kind: str, name: str) -> None:
    print(f"  {'created' if created else 'exists '}  {kind}: {name}")


async def seed() -> None:
    # Deferred so sys.path points at backend/ before app imports resolve.
    from sqlalchemy import func, select

    import app.infrastructure.registry  # noqa: F401  (completes Base.metadata)
    from app.infrastructure.database import create_engine, create_session_factory
    from app.modules.auth.models import PlatformOrganization
    from app.modules.forms.models import Form, FormVersion
    from app.modules.projects.models import Environment, Project

    ir: dict[str, Any] = json.loads(FORM_JSON.read_text())
    form_key, version = str(ir["formId"]), int(ir["version"])
    checksum = _checksum(ir)

    engine = create_engine()
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
                project = Project(id=PROJECT_ID, name="Dev Project", slug=PROJECT_SLUG)
                session.add(project)
            _report(project in session.new, "project", PROJECT_SLUG)
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

            form = (
                await session.execute(
                    select(Form).where(Form.project_id == project.id, Form.form_key == form_key)
                )
            ).scalar_one_or_none()
            if form is None:
                title = ir["title"].get(ir.get("defaultLanguage", "en"), form_key)
                form = Form(id=FORM_ID, project_id=project.id, form_key=form_key, title=title)
                session.add(form)
            _report(form in session.new, "form", form_key)
            await session.flush()

            form_version = (
                await session.execute(
                    select(FormVersion).where(
                        FormVersion.form_id == form.id, FormVersion.version == version
                    )
                )
            ).scalar_one_or_none()
            if form_version is None:
                session.add(
                    FormVersion(
                        id=FORM_VERSION_ID,
                        form_id=form.id,
                        version=version,
                        ir=ir,
                        ir_checksum=checksum,
                        published_at=func.now(),
                        published_by=None,
                    )
                )
                _report(True, "form_version", f"{form_key} v{version}")
            else:
                _report(False, "form_version", f"{form_key} v{version}")
                if form_version.ir_checksum != checksum:
                    # Published versions are immutable (forms/models.py); the
                    # bundle has drifted and needs a new version, not an edit.
                    print(
                        f"  WARNING: stored {form_key} v{version} does not match the bundled "
                        f"JSON ({form_version.ir_checksum} != {checksum}). Publish a new "
                        "version instead of editing v1."
                    )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    print(f"Seeding {FORM_JSON.relative_to(REPO_ROOT)} into the development database")
    asyncio.run(seed())
    print("Done. Devices self-register on first sync; no further setup needed.")
