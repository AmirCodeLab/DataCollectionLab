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
TEAM_ID, TEAM_NAME = "01TEAMDEV", "Team A"
TEAM_B_ID, TEAM_B_NAME = "01TEAMDEVB", "Team B"
#: A third team exists so that "team A plus team B is less than the project"
#: can fail. With two teams every row is inside one of them, their figures
#: add to the project's exactly, and a policy that showed a supervisor
#: everything would pass the check unnoticed — the fixture rule in
#: docs/project-conventions.md, applied to the seed a run is walked on.
TEAM_C_ID, TEAM_C_NAME = "01TEAMDEVC", "Team C"

#: The people the chain is walked with (proposal §9): one of each role, and
#: one waiting for approval. The password is published — it is the same kind
#: of default as `dcp:dcp` — and the seed refuses to run outside development
#: for exactly that reason.
DEV_PASSWORD = "dcp-dev"
PEOPLE: tuple[tuple[str, str, str, str, str | None, str], ...] = (
    # id, username, display name, role suffix, team, membership status
    ("01USRADMIN", "admin", "Dev Admin", "admin", None, "active"),
    ("01USRPM", "pm", "Dev Programme Manager", "pm", None, "active"),
    ("01USRSUPER", "supervisor", "Dev Supervisor", "supervisor", TEAM_ID, "active"),
    ("01USRENUM", "enumerator", "Dev Enumerator", "enumerator", TEAM_ID, "active"),
    ("01USRPENDING", "pending", "Waiting Enumerator", "enumerator", TEAM_ID, "pending_approval"),
    # A second team, so that "a supervisor sees only their team" has a team
    # not to see, and an admin has both to see (pilot scope §4.2).
    ("01USRSUPERB", "supervisor-b", "Dev Supervisor B", "supervisor", TEAM_B_ID, "active"),
    ("01USRENUMB", "enumerator-b", "Dev Enumerator B", "enumerator", TEAM_B_ID, "active"),
    # Neither supervisor can see this one. Their dashboards must add up to
    # less than the project's, and they only can if somebody holds work
    # outside both teams.
    ("01USRENUMC", "enumerator-c", "Dev Enumerator C", "enumerator", TEAM_C_ID, "active"),
)
FORM_ID = "01FORMHH"
FORM_VERSION_ID = "01FORMHHV1"


def _report(created: bool, kind: str, name: str) -> None:
    print(f"  {'created' if created else 'exists '}  {kind}: {name}")


async def _provision_organization(database: str | None) -> None:
    """The organisation and its standard roles, as the owner.

    Provisioning is the owner's job (ERD §1): the standard roles are seeded
    per organisation at its creation — by 008 for the organisation that
    existed then, here for a fresh database — and 010_people.sql makes them
    the one thing no application principal may write. Idempotent by id.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.infrastructure.database import create_admin_engine

    engine = create_admin_engine(database=database)
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            created = await session.execute(
                text(
                    "INSERT INTO platform_organization (id, name, slug) "
                    "VALUES (:id, 'Dev Organisation', :slug) ON CONFLICT (id) DO NOTHING"
                ),
                {"id": ORG_ID, "slug": ORG_SLUG},
            )
            _report(bool(getattr(created, "rowcount", 0)), "organisation", ORG_SLUG)
            await session.execute(
                text(
                    """
                    INSERT INTO role (id, organization_id, name, scope_kind, builtin)
                    SELECT :org || '_' || r.suffix, :org, r.name, r.scope_kind, true
                    FROM (VALUES ('admin', 'Admin', 'organization'),
                                 ('pm', 'Programme manager', 'project'),
                                 ('supervisor', 'Supervisor', 'team'),
                                 ('enumerator', 'Enumerator', 'team'))
                         AS r(suffix, name, scope_kind)
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {"org": ORG_ID},
            )
            # Admin: everything. PM: everything but device.revoke. Supervisor
            # (§3.2, 010 §3, 016 §1): creates enumerators in their own team,
            # assigns sample, sees submissions — and reviews them, because in
            # RCons the supervisor is the reviewer. Enumerator: nothing —
            # their access is their device's session.
            await session.execute(
                text(
                    """
                    INSERT INTO role_permission (role_id, permission)
                    SELECT r.id, p.name
                    FROM role r,
                         (VALUES ('user.create'), ('user.approve'), ('user.deactivate'),
                                 ('user.assign_role'), ('team.manage'), ('sample.upload'),
                                 ('sample.assign'), ('form.edit'), ('form.publish'),
                                 ('form.deploy'), ('submission.view'), ('submission.review'),
                                 ('export.download'), ('device.revoke'), ('project.manage'))
                         AS p(name)
                    WHERE r.organization_id = :org AND r.builtin AND (
                        r.name = 'Admin'
                        OR (r.name = 'Programme manager' AND p.name <> 'device.revoke')
                        OR (r.name = 'Supervisor' AND p.name IN
                            ('user.create', 'user.assign_role', 'sample.assign',
                             'submission.view', 'submission.review'))
                    )
                    ON CONFLICT DO NOTHING
                    """
                ),
                {"org": ORG_ID},
            )
    finally:
        await engine.dispose()


async def seed(security_mode: str = "standard", database: str | None = None) -> None:
    # Deferred so sys.path points at backend/ before app imports resolve.
    from sqlalchemy import select

    import app.infrastructure.registry  # noqa: F401  (completes Base.metadata)
    from app.core.config import get_settings
    from app.infrastructure.database import (
        Principal,
        create_engine,
        session_as,
    )
    from app.modules.auth.models import (
        PlatformOrganization,
        PlatformOrgMembership,
        PlatformUser,
        UserRole,
    )
    from app.modules.auth.passwords import hash_password
    from app.modules.auth.schemas import PERMISSIONS
    from app.modules.forms import service as forms_service
    from app.modules.projects.models import Environment, Project, ProjectMember, Team

    if get_settings().environment != "development":
        raise SystemExit(
            f"Refusing to seed: environment is {get_settings().environment!r}, not "
            "'development'. The seed creates people whose password is published."
        )

    ir: dict[str, Any] = json.loads(FORM_JSON.read_text())
    form_key, version = str(ir["formId"]), int(ir["version"])

    # A project's security mode is fixed at creation (encryption envelope §1),
    # so an encrypting project is a DIFFERENT project, not this one changed.
    # Seeding it into its own database also keeps device self-registration
    # unambiguous: a deployment with two active projects refuses to guess.
    # Two halves. The organisation and its standard roles are provisioning,
    # which is the owner's job (ERD §1; 010_people.sql: the standard roles
    # are not the application's to make). Everything after — project,
    # environments, people, form — runs as the application role with an
    # administrator's authority, through the policies rather than around
    # them: provisioning that cannot pass them is a finding.
    await _provision_organization(database)
    engine = create_engine(database=database)
    principal = Principal.organization(ORG_ID, slug=ORG_SLUG, permissions=tuple(PERMISSIONS))
    try:
        async with session_as(principal, engine=engine) as session, session.begin():
            (
                await session.execute(
                    select(PlatformOrganization).where(PlatformOrganization.slug == ORG_SLUG)
                )
            ).scalar_one()

            project = (
                await session.execute(select(Project).where(Project.slug == PROJECT_SLUG))
            ).scalar_one_or_none()
            if project is None:
                project = Project(
                    id=PROJECT_ID,
                    organization_id=ORG_ID,
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

            await session.flush()

            # The people. Created the way provisioning will create them — as
            # rows under the policies — and matched by username so a re-run
            # changes nothing. The pending one is the approval flow's fixture:
            # refused at login by the session policy, approved by an admin,
            # then pushing.
            for seed_team_id, team_name in (
                (TEAM_ID, TEAM_NAME),
                (TEAM_B_ID, TEAM_B_NAME),
                (TEAM_C_ID, TEAM_C_NAME),
            ):
                team = await session.get(Team, seed_team_id)
                team_created = team is None
                if team is None:
                    session.add(Team(id=seed_team_id, project_id=project.id, name=team_name))
                    await session.flush()
                _report(team_created, "team", team_name)
            for user_id, username, display_name, role_suffix, team_id, status in PEOPLE:
                user = (
                    await session.execute(
                        select(PlatformUser).where(PlatformUser.username == username)
                    )
                ).scalar_one_or_none()
                created = user is None
                if user is None:
                    user = PlatformUser(
                        id=user_id,
                        organization_id=ORG_ID,
                        username=username,
                        display_name=display_name,
                        password_hash=hash_password(DEV_PASSWORD),
                    )
                    session.add(user)
                    await session.flush()
                    session.add(
                        PlatformOrgMembership(
                            organization_id=ORG_ID,
                            user_id=user.id,
                            org_role="admin" if role_suffix == "admin" else "member",
                            status=status,
                        )
                    )
                    role_id = f"{ORG_ID}_{role_suffix}"
                    scope_kind = {"admin": "organization", "pm": "project"}.get(
                        role_suffix, "team"
                    )
                    session.add(
                        UserRole(
                            id=f"{user.id}_ROLE",
                            user_id=user.id,
                            role_id=role_id,
                            scope_kind=scope_kind,
                            project_id=project.id if scope_kind == "project" else None,
                            team_id=team_id if scope_kind == "team" else None,
                        )
                    )
                    if role_suffix != "admin":
                        session.add(
                            ProjectMember(project_id=project.id, user_id=user.id, team_id=team_id)
                        )
                    await session.flush()
                _report(created, "user", f"{username} ({role_suffix}, {status})")

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
    print(
        f"  sign in as any of {', '.join(p[1] for p in PEOPLE)} with the password "
        f"{DEV_PASSWORD!r} (published; development only)"
    )


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
