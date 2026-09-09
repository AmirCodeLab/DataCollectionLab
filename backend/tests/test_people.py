"""People, teams and roles — over cookies, with the database deciding.

The question asked before the screens were written: a role or permission
editable in the UI that the policy does not read. So these tests do not call
the service with a fabricated principal; they log in, and they assert what
the *database* does when a screen would have offered something it should not
— because the route's courtesy check is not what is being tested, the policy
is. Where a route would refuse first, the test goes under it, with the
person's real principal on the connection, to show the refusal is the
database's own.

The fixture: two supervisors with a team each, a PM over the project, an
admin, an enumerator in team A, and the roles 008/010 seed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from fastapi import Request
from sqlalchemy import insert, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.infrastructure.database import (
    admin_connection,
    admin_url,
    create_admin_engine,
    create_engine,
    session_as,
)
from app.modules.auth import service as auth
from app.modules.auth.models import PlatformOrgMembership, RolePermission, UserRole
from app.modules.auth.passwords import hash_password
from app.modules.people import service as people

PEOPLE_DB = "dcp_test_people"
ORG_ID, ORG_SLUG = "01ORGPPL", "ppl"
PROJECT_ID = "01PRJPPL"
PASSWORD = "correct horse"
TEAM_A, TEAM_B = "01TEAMPA", "01TEAMPB"
ADMIN, PM, SUP_A, SUP_B, ENUM_A = "01UADMIN", "01UPM", "01USUPA", "01USUPB", "01UENUMA"


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


async def _seed() -> None:
    from app.modules.auth.models import PlatformOrganization, PlatformUser
    from app.modules.projects.models import Project, ProjectMember, Team

    engine = create_admin_engine(database=PEOPLE_DB)
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            session.add(PlatformOrganization(id=ORG_ID, name="People", slug=ORG_SLUG))
            await session.flush()
            # The standard roles, as 008 seeds them for an organisation and
            # 009/010 amend them.
            await session.execute(
                text(
                    "INSERT INTO role (id, organization_id, name, scope_kind, builtin) VALUES "
                    "(:o || '_admin', :o, 'Admin', 'organization', true), "
                    "(:o || '_pm', :o, 'Programme manager', 'project', true), "
                    "(:o || '_supervisor', :o, 'Supervisor', 'team', true), "
                    "(:o || '_enumerator', :o, 'Enumerator', 'team', true)"
                ),
                {"o": ORG_ID},
            )
            await session.execute(
                text(
                    "INSERT INTO role_permission (role_id, permission) "
                    "SELECT r.id, p.name FROM role r, (VALUES ('user.create'), ('user.approve'), "
                    "('user.deactivate'), ('user.assign_role'), ('team.manage'), "
                    "('sample.upload'), ('sample.assign'), ('form.edit'), ('form.publish'), "
                    "('form.deploy'), ('submission.view'), ('submission.review'), "
                    "('export.download'), ('device.revoke'), ('project.manage')) AS p(name) "
                    "WHERE r.organization_id = :o AND r.builtin AND ("
                    "  r.name = 'Admin' "
                    "  OR (r.name = 'Programme manager' AND p.name <> 'device.revoke') "
                    "  OR (r.name = 'Supervisor' AND p.name IN ('user.create', 'user.assign_role', "
                    "      'sample.assign', 'submission.view')))"
                ),
                {"o": ORG_ID},
            )
            session.add(Project(id=PROJECT_ID, organization_id=ORG_ID, name="P", slug="ppl"))
            await session.flush()
            for team_id, name in ((TEAM_A, "Team A"), (TEAM_B, "Team B")):
                session.add(Team(id=team_id, project_id=PROJECT_ID, name=name))
            people_rows = (
                (ADMIN, "admin", "admin", "organization", None, None),
                (PM, "pm", "pm", "project", PROJECT_ID, None),
                (SUP_A, "sup-a", "supervisor", "team", None, TEAM_A),
                (SUP_B, "sup-b", "supervisor", "team", None, TEAM_B),
                (ENUM_A, "enum-a", "enumerator", "team", None, TEAM_A),
            )
            for user_id, username, _r, _s, _p, _t in people_rows:
                session.add(
                    PlatformUser(
                        id=user_id,
                        organization_id=ORG_ID,
                        username=username,
                        display_name=username,
                        password_hash=hash_password(PASSWORD),
                    )
                )
            await session.flush()
            for user_id, _u, role, scope, project_id, team_id in people_rows:
                session.add(
                    PlatformOrgMembership(
                        organization_id=ORG_ID, user_id=user_id, org_role="member", status="active"
                    )
                )
                session.add(
                    UserRole(
                        id=f"{user_id}_R",
                        user_id=user_id,
                        role_id=f"{ORG_ID}_{role}",
                        scope_kind=scope,
                        project_id=project_id,
                        team_id=team_id,
                    )
                )
                if scope != "organization":
                    session.add(
                        ProjectMember(project_id=PROJECT_ID, user_id=user_id, team_id=team_id)
                    )
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def people_app() -> Any:
    from alembic import command
    from alembic.config import Config

    from tests.test_migrations import BACKEND_DIR

    async def prepare() -> str | None:
        try:
            async with admin_connection(timeout=3) as conn:
                await conn.execute(f"DROP DATABASE IF EXISTS {PEOPLE_DB} WITH (FORCE)")
                await conn.execute(f"CREATE DATABASE {PEOPLE_DB}")
        except Exception as exc:  # noqa: BLE001 - any failure means "not available"
            return f"{type(exc).__name__}: {exc}"
        return None

    reason = _run(prepare())
    if reason is not None:
        pytest.skip(
            f"Postgres unavailable ({reason}) — start it with: docker compose up -d postgres"
        )
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", admin_url(PEOPLE_DB))
    command.upgrade(cfg, "head")
    _run(_seed())

    from app.api.access import organization_slug
    from app.api.deps import get_db
    from app.infrastructure.database import session_for_organization
    from app.main import app

    async def anonymous(request: Request) -> Any:
        engine = create_engine(database=PEOPLE_DB)
        try:
            async with session_for_organization(organization_slug(request), engine=engine) as s:
                yield s
        finally:
            await engine.dispose()

    app.dependency_overrides[get_db] = anonymous
    yield app
    app.dependency_overrides.pop(get_db, None)

    async def drop() -> None:
        async with admin_connection() as conn:
            await conn.execute(f"DROP DATABASE IF EXISTS {PEOPLE_DB} WITH (FORCE)")

    _run(drop())


Scenario = Callable[[httpx.AsyncClient], Awaitable[None]]


def _with_client(app: Any, scenario: Scenario) -> None:
    async def main() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await scenario(client)

    _run(main())


async def _login(client: httpx.AsyncClient, username: str) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORD, "organization": ORG_SLUG},
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


async def _principal_of(username: str) -> Any:
    """The person's real principal, as a request would carry it — for going
    under the route's courtesy check to the policy."""
    engine = create_engine(database=PEOPLE_DB)
    try:
        from app.infrastructure.database import Principal

        async with session_as(Principal(org_id=ORG_ID, org_slug=ORG_SLUG), engine=engine) as s:
            found = (
                await s.execute(
                    text("SELECT * FROM dcp_login_lookup(:u)"), {"u": username}
                )
            ).mappings().one()
            person = auth.Person(
                found["id"], found["organization_id"], found["username"], found["display_name"]
            )
            principal, _ = await auth.principal_for(s, person, ORG_SLUG)
            return principal
    finally:
        await engine.dispose()


def _refused_by_policy(error: BaseException) -> bool:
    return isinstance(error, DBAPIError) and "row-level security" in str(error.orig)


# ---------------------------------------------------------------------------
# §4.2: a supervisor sees their team's people, and nobody else's
# ---------------------------------------------------------------------------


@pytest.mark.db
def test_01_a_supervisor_lists_their_own_team_only(people_app: Any) -> None:
    async def scenario(client: httpx.AsyncClient) -> None:
        await _login(client, "sup-a")
        listed = await client.get("/api/v1/people")
        assert listed.status_code == 200, listed.text
        assert {p["username"] for p in listed.json()["people"]} == {"sup-a", "enum-a"}

        await _login(client, "sup-b")
        listed = await client.get("/api/v1/people")
        assert {p["username"] for p in listed.json()["people"]} == {"sup-b"}

        await _login(client, "pm")
        listed = await client.get("/api/v1/people")
        assert {p["username"] for p in listed.json()["people"]} == {
            "pm", "sup-a", "sup-b", "enum-a"
        }

        await _login(client, "admin")
        listed = await client.get("/api/v1/people")
        assert len(listed.json()["people"]) == 5

    _with_client(people_app, scenario)


# ---------------------------------------------------------------------------
# §3.2, §3.3: the approval flow falls out of the model
# ---------------------------------------------------------------------------


@pytest.mark.db
def test_02_a_supervisors_enumerator_waits_and_a_pm_approves(people_app: Any) -> None:
    async def scenario(client: httpx.AsyncClient) -> None:
        me = await _login(client, "sup-a")
        assert me["teamIds"] == [TEAM_A]
        created = await client.post(
            "/api/v1/people",
            json={
                "username": "new-enum",
                "displayName": "New Enumerator",
                "password": "eight chars",
                "roleId": f"{ORG_ID}_enumerator",
            },
        )
        assert created.status_code == 201, created.text
        person = created.json()
        # The database chose: a supervisor holds no user.approve.
        assert person["membershipStatus"] == "pending_approval"
        assert person["createdByName"] == "sup-a"
        # Landed in the supervisor's team without naming it (§3.2).
        assert [t["teamId"] for t in person["teams"]] == [TEAM_A]
        assert [g["roleName"] for g in person["grants"]] == ["Enumerator"]

        # Waiting: the supervisor sees them, at the top, as waiting.
        listed = (await client.get("/api/v1/people")).json()["people"]
        assert listed[0]["username"] == "new-enum"
        assert listed[0]["membershipStatus"] == "pending_approval"

        # Cannot log in yet — the session policy's refusal, named.
        refused = await client.post(
            "/api/v1/auth/login",
            json={"username": "new-enum", "password": "eight chars", "organization": ORG_SLUG},
        )
        assert refused.status_code == 403
        assert refused.json()["detail"]["reason"] == "pending_approval"

        # The supervisor may not approve: the route says so...
        await _login(client, "sup-a")
        route = await client.post(f"/api/v1/people/{person['id']}/approve")
        assert route.status_code == 403
        assert route.json()["detail"]["reason"] == "permission_denied"

        # A PM approves, and the same login succeeds.
        await _login(client, "pm")
        approved = await client.post(f"/api/v1/people/{person['id']}/approve")
        assert approved.status_code == 200, approved.text
        assert approved.json()["membershipStatus"] == "active"
        assert approved.json()["approvedByName"] == "pm"
        assert (
            await client.post(
                "/api/v1/auth/login",
                json={"username": "new-enum", "password": "eight chars", "organization": ORG_SLUG},
            )
        ).status_code == 200

    _with_client(people_app, scenario)


@pytest.mark.db
def test_03_the_database_refuses_the_approval_under_the_route(people_app: Any) -> None:
    """...and the database says so too, with the supervisor's real principal
    on the connection and no route in the way. The screen and the policy read
    the same list; this is the half a screen cannot fake."""

    async def go() -> None:
        principal = await _principal_of("sup-a")
        assert "user.approve" not in principal.permissions
        engine = create_engine(database=PEOPLE_DB)
        try:
            async with session_as(principal, engine=engine) as s:
                # A pending person of their own to approve.
                async with s.begin():
                    created = await people.create_person(
                        s,
                        people.CreatePersonRequest(
                            username="under-route",
                            displayName="Under Route",
                            password="eight chars",
                            roleId=f"{ORG_ID}_enumerator",
                        ),
                        principal,
                    )
                assert created.membership_status == "pending_approval"
                async with s.begin():
                    with pytest.raises(people.Refused) as refusal:
                        await people.approve(s, created.id, principal)
                assert refusal.value.reason == "outside_your_authority"
                # And a bare UPDATE, not even the service: the policy's own no.
                async with s.begin():
                    with pytest.raises(DBAPIError) as raw:
                        await s.execute(
                            text(
                                "UPDATE platform_org_membership SET status = 'active' "
                                "WHERE user_id = :u"
                            ),
                            {"u": created.id},
                        )
                assert _refused_by_policy(raw.value)
        finally:
            await engine.dispose()

    _run(go())


@pytest.mark.db
def test_04_a_pm_creates_active_directly_and_an_admin_deactivates(people_app: Any) -> None:
    async def scenario(client: httpx.AsyncClient) -> None:
        await _login(client, "pm")
        created = await client.post(
            "/api/v1/people",
            json={
                "username": "pm-made",
                "displayName": "PM Made",
                "password": "eight chars",
                "roleId": f"{ORG_ID}_supervisor",
                "teamId": TEAM_B,
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["membershipStatus"] == "active"  # the DEFAULT: user.approve held

        await _login(client, "admin")
        gone = await client.post(f"/api/v1/people/{created.json()['id']}/deactivate")
        assert gone.status_code == 200 and gone.json()["membershipStatus"] == "deactivated"
        back = await client.post(f"/api/v1/people/{created.json()['id']}/reactivate")
        assert back.status_code == 200 and back.json()["membershipStatus"] == "active"

    _with_client(people_app, scenario)


# ---------------------------------------------------------------------------
# §3.2: nobody creates a role above their own, or outside their scope
# ---------------------------------------------------------------------------


@pytest.mark.db
def test_05_a_grant_above_or_outside_the_grantors_authority_is_refused(people_app: Any) -> None:
    async def scenario(client: httpx.AsyncClient) -> None:
        await _login(client, "sup-a")
        # A supervisor granting Programme manager: a role above their own.
        above = await client.post(
            f"/api/v1/people/{ENUM_A}/grants",
            json={"roleId": f"{ORG_ID}_pm", "projectId": PROJECT_ID},
        )
        assert above.status_code == 403, above.text
        assert above.json()["detail"]["reason"] == "outside_your_authority"
        # The Enumerator role in team B: outside their scope.
        outside = await client.post(
            f"/api/v1/people/{ENUM_A}/grants",
            json={"roleId": f"{ORG_ID}_enumerator", "teamId": TEAM_B},
        )
        assert outside.status_code == 403, outside.text
        # The Enumerator role in their own team: inside it.
        inside = await client.post(
            f"/api/v1/people/{ENUM_A}/grants",
            json={"roleId": f"{ORG_ID}_supervisor", "teamId": TEAM_A},
        )
        assert inside.status_code == 200, inside.text
        assert {g["roleName"] for g in inside.json()["grants"]} == {"Enumerator", "Supervisor"}

    _with_client(people_app, scenario)


# ---------------------------------------------------------------------------
# §3.5: a role editable in the UI is a role the policy reads
# ---------------------------------------------------------------------------


@pytest.mark.db
def test_06_a_role_carries_only_permissions_its_editor_holds(people_app: Any) -> None:
    async def scenario(client: httpx.AsyncClient) -> None:
        await _login(client, "sup-a")
        roles = (await client.get("/api/v1/roles")).json()["roles"]
        grantable = {r["name"] for r in roles if r["grantable"]}
        assert "Enumerator" in grantable and "Admin" not in grantable

        # A supervisor minting a role with export.download: refused by the
        # database — the screen's checkbox list says the same, from the same list.
        minted = await client.post(
            "/api/v1/roles",
            json={"name": "Exporter", "scopeKind": "team", "permissions": ["export.download"]},
        )
        assert minted.status_code == 403, minted.text
        assert minted.json()["detail"]["reason"] == "outside_your_authority"
        # Within their own permissions: fine.
        own = await client.post(
            "/api/v1/roles",
            json={"name": "Viewer", "scopeKind": "team", "permissions": ["submission.view"]},
        )
        assert own.status_code == 201, own.text
        viewer_id = own.json()["id"]

        # An admin can widen it; a supervisor cannot widen it past themself.
        await _login(client, "admin")
        widened = await client.put(
            f"/api/v1/roles/{viewer_id}/permissions",
            json={"permissions": ["submission.view", "export.download"]},
        )
        assert widened.status_code == 200, widened.text
        await _login(client, "sup-a")
        narrowed = await client.put(
            f"/api/v1/roles/{viewer_id}/permissions", json={"permissions": ["submission.view"]}
        )
        # Removing export.download is editing a permission they do not hold.
        assert narrowed.status_code == 403, narrowed.text

        # The standard roles are not editable, by anyone.
        await _login(client, "admin")
        builtin = await client.put(
            f"/api/v1/roles/{ORG_ID}_supervisor/permissions",
            json={"permissions": ["submission.view"]},
        )
        assert builtin.status_code == 403, builtin.text

    _with_client(people_app, scenario)


@pytest.mark.db
def test_07_the_database_refuses_a_role_edit_under_the_route(people_app: Any) -> None:
    """The half a screen cannot fake: a supervisor's principal, no route,
    an INSERT of a permission they do not hold."""

    async def go() -> None:
        principal = await _principal_of("sup-a")
        engine = create_engine(database=PEOPLE_DB)
        try:
            async with session_as(principal, engine=engine) as s:
                async with s.begin():
                    role = await people.create_role(
                        s,
                        people.CreateRoleRequest(name="Raw", scopeKind="team", permissions=[]),
                        principal,
                    )
                async with s.begin():
                    with pytest.raises(DBAPIError) as raw:
                        await s.execute(
                            insert(RolePermission).values(
                                role_id=role.id, permission="export.download"
                            )
                        )
                assert _refused_by_policy(raw.value)
        finally:
            await engine.dispose()

    _run(go())


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------


@pytest.mark.db
def test_08_teams_are_the_pms_to_make_and_a_supervisors_to_fill(people_app: Any) -> None:
    async def scenario(client: httpx.AsyncClient) -> None:
        await _login(client, "sup-a")
        made = await client.post("/api/v1/teams", json={"projectId": PROJECT_ID, "name": "Team C"})
        assert made.status_code == 403  # no team.manage: the route
        teams = await client.get("/api/v1/teams", params={"projectId": PROJECT_ID})
        assert teams.status_code == 200, teams.text
        # Team B exists, but its members are not the supervisor's to see.
        by_name = {t["name"]: t for t in teams.json()["teams"]}
        assert {m["displayName"] for m in by_name["Team A"]["members"]} >= {"sup-a", "enum-a"}
        assert by_name["Team B"]["members"] == []

        await _login(client, "pm")
        made = await client.post("/api/v1/teams", json={"projectId": PROJECT_ID, "name": "Team C"})
        assert made.status_code == 201, made.text
        # Selecting an existing person into a team: no approval involved.
        moved = await client.post(
            f"/api/v1/teams/{made.json()['id']}/members", json={"userId": ENUM_A}
        )
        assert moved.status_code == 200, moved.text
        assert {m["displayName"] for m in moved.json()["members"]} == {"enum-a"}

    _with_client(people_app, scenario)
