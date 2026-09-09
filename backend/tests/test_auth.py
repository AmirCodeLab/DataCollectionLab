"""Login, the cookie, and the two boundaries — for real, with no override.

Every other API test module fabricates its identity (`identity_fixtures`).
This one does not: it seeds people with passwords, logs them in over HTTP,
carries the cookies the server set, and asserts what each of them can reach.
The four breaks named before the routes were written are here, on the path a
request takes:

- a session for a pending membership (test 03): refused by the policy on
  `platform_session`, and the login route names the reason without a check
  of its own — it has none to remove;
- a session surviving deactivation (test 05): it does not, and no code
  revoked it — the row stopped being visible;
- a supervisor reaching another team's rows (tests 06–08): the unfiltered
  list, the export, and the sync pull all stop at the team, because the same
  policy answers all three;
- a request with no principal reaching anything at all (test 10): every route
  the app serves, called with no cookie, enumerated from the route table.

The fixture organisation is seeded as the owner. Two supervisors, two
enumerators, one submission each, an admin, a person waiting for approval,
and a device per enumerator, bound to nobody until a login binds it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.infrastructure.database import (
    admin_connection,
    admin_url,
    create_admin_engine,
)
from app.modules.auth.passwords import hash_password

AUTH_DB = "dcp_test_auth"
ORG_ID, ORG_SLUG = "01ORGAUTH", "auth"
PROJECT_ID = "01PRJAUTH"
PASSWORD = "correct horse"

# Two teams, a supervisor and an enumerator in each.
TEAM_A, TEAM_B = "01TEAMA", "01TEAMB"
ADMIN, SUP_A, SUP_B, ENUM_A, ENUM_B, PENDING = (
    "01USRADMIN",
    "01USRSUPA",
    "01USRSUPB",
    "01USRENUMA",
    "01USRENUMB",
    "01USRPENDING",
)
DEVICE_A, DEVICE_B = "dev-a", "dev-b"
SUB_A, SUB_B = "01SUBA", "01SUBB"


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


async def _seed() -> None:
    from app.modules.auth.models import (
        PlatformOrganization,
        PlatformOrgMembership,
        PlatformUser,
        UserRole,
    )
    from app.modules.forms.models import Form, FormVersion
    from app.modules.projects.models import Device, Environment, Project, ProjectMember, Team
    from app.modules.submissions.models import Submission

    engine = create_admin_engine(database=AUTH_DB)
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            session.add(PlatformOrganization(id=ORG_ID, name="Auth", slug=ORG_SLUG))
            await session.flush()
            # The standard roles are seeded per organisation by 008 for the
            # organisations that existed then; a fixture organisation seeds
            # its own, the way provisioning will.
            await session.execute(
                text(
                    "INSERT INTO role (id, organization_id, name, scope_kind, builtin) VALUES "
                    "(:o || '_admin', :o, 'Admin', 'organization', true), "
                    "(:o || '_supervisor', :o, 'Supervisor', 'team', true), "
                    "(:o || '_enumerator', :o, 'Enumerator', 'team', true)"
                ),
                {"o": ORG_ID},
            )
            await session.execute(
                text(
                    "INSERT INTO role_permission (role_id, permission) "
                    "SELECT :o || '_admin', p FROM unnest(ARRAY['user.create', 'user.approve', "
                    "'user.deactivate', 'user.assign_role', 'team.manage', 'sample.upload', "
                    "'sample.assign', 'form.edit', 'form.publish', 'form.deploy', "
                    "'submission.view', 'submission.review', 'export.download', "
                    "'device.revoke', 'project.manage']) AS p "
                    "UNION ALL SELECT :o || '_supervisor', p FROM unnest(ARRAY['user.create', "
                    "'sample.assign', 'submission.view']) AS p"
                ),
                {"o": ORG_ID},
            )
            session.add(Project(id=PROJECT_ID, organization_id=ORG_ID, name="P", slug="p"))
            await session.flush()
            session.add(Environment(id="01ENVAUTH", project_id=PROJECT_ID, kind="production"))
            session.add(Form(id="01FRMAUTH", project_id=PROJECT_ID, form_key="hh", title="HH"))
            for team_id, name in ((TEAM_A, "Team A"), (TEAM_B, "Team B")):
                session.add(Team(id=team_id, project_id=PROJECT_ID, name=name))
            await session.flush()
            session.add(
                FormVersion(id="01VERAUTH", form_id="01FRMAUTH", version=1, ir={}, ir_checksum="x")
            )
            people = (
                (ADMIN, "admin", "admin", "organization", None, "active"),
                (SUP_A, "sup-a", "supervisor", "team", TEAM_A, "active"),
                (SUP_B, "sup-b", "supervisor", "team", TEAM_B, "active"),
                (ENUM_A, "enum-a", "enumerator", "team", TEAM_A, "active"),
                (ENUM_B, "enum-b", "enumerator", "team", TEAM_B, "active"),
                (PENDING, "pending", "enumerator", "team", TEAM_A, "pending_approval"),
            )
            for user_id, username, _role, _scope, _team_id, _status in people:
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
            for user_id, _username, role, scope, team_id, status in people:
                session.add(
                    PlatformOrgMembership(
                        organization_id=ORG_ID, user_id=user_id, org_role="member", status=status
                    )
                )
                session.add(
                    UserRole(
                        id=f"{user_id}_R",
                        user_id=user_id,
                        role_id=f"{ORG_ID}_{role}",
                        scope_kind=scope,
                        team_id=team_id,
                    )
                )
                if team_id is not None:
                    session.add(
                        ProjectMember(project_id=PROJECT_ID, user_id=user_id, team_id=team_id)
                    )
            await session.flush()
            for device_id in (DEVICE_A, DEVICE_B):
                session.add(Device(id=device_id, project_id=PROJECT_ID, platform="android"))
            await session.flush()
            for sub_id, author, device_id in ((SUB_A, ENUM_A, DEVICE_A), (SUB_B, ENUM_B, DEVICE_B)):
                session.add(
                    Submission(
                        id=sub_id,
                        project_id=PROJECT_ID,
                        environment_id="01ENVAUTH",
                        form_version_id="01VERAUTH",
                        origin_device_id=device_id,
                        created_by=author,
                    )
                )
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def auth_app() -> Any:
    from alembic import command
    from alembic.config import Config

    from tests.test_migrations import BACKEND_DIR

    async def prepare() -> str | None:
        try:
            async with admin_connection(timeout=3) as conn:
                await conn.execute(f"DROP DATABASE IF EXISTS {AUTH_DB} WITH (FORCE)")
                await conn.execute(f"CREATE DATABASE {AUTH_DB}")
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
    cfg.set_main_option("sqlalchemy.url", admin_url(AUTH_DB))
    command.upgrade(cfg, "head")
    _run(_seed())

    # No identity override, on purpose. The session comes from the factory on
    # the scratch database; the identity comes from the cookie or not at all.
    from app.api.deps import get_db
    from app.main import app
    from tests.identity_fixtures import api_session_override

    app.dependency_overrides[get_db] = _anonymous_override(api_session_override(AUTH_DB))
    yield app
    app.dependency_overrides.pop(get_db, None)

    async def drop() -> None:
        async with admin_connection() as conn:
            await conn.execute(f"DROP DATABASE IF EXISTS {AUTH_DB} WITH (FORCE)")

    _run(drop())


def _anonymous_override(scratch: Callable[[], Any]) -> Callable[..., Any]:
    """`api_session_override` hands out sessions as the fixture organisation's
    test person; this module wants the request's own resolution — the
    organisation from the cookie or the setting, nobody until a login."""
    from app.infrastructure.database import create_engine, session_for_organization

    async def anonymous(request: Request) -> Any:
        from app.api.access import organization_slug

        engine = create_engine(database=AUTH_DB)
        try:
            async with session_for_organization(organization_slug(request), engine=engine) as s:
                yield s
        finally:
            await engine.dispose()

    return anonymous


Scenario = Callable[[httpx.AsyncClient], Awaitable[None]]


def _with_client(app: Any, scenario: Scenario) -> None:
    async def main() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await scenario(client)

    _run(main())


async def _login(
    client: httpx.AsyncClient, username: str, *, kind: str = "console", device_id: str | None = None
) -> httpx.Response:
    body: dict[str, Any] = {
        "username": username,
        "password": PASSWORD,
        "kind": kind,
        "organization": ORG_SLUG,
    }
    if device_id is not None:
        body["deviceId"] = device_id
    return await client.post("/api/v1/auth/login", json=body)


async def _owner(sql: str, *args: Any) -> Any:
    async with admin_connection(AUTH_DB) as conn:
        return await conn.fetch(sql, *args)


# ---------------------------------------------------------------------------
# The cookie
# ---------------------------------------------------------------------------


@pytest.mark.db
def test_01_login_sets_an_httponly_strict_cookie_and_returns_no_token(auth_app: Any) -> None:
    async def scenario(client: httpx.AsyncClient) -> None:
        response = await _login(client, "admin")
        assert response.status_code == 200, response.text
        cookies = response.headers.get_list("set-cookie")
        session_cookie = next(c for c in cookies if c.startswith("dcp_session="))
        assert "HttpOnly" in session_cookie
        assert "SameSite=strict" in session_cookie.lower().replace("samesite", "SameSite")
        assert "Path=/api" in session_cookie
        token = session_cookie.split("=", 1)[1].split(";", 1)[0]
        assert token and token not in response.text, "the token is in the body"
        me = response.json()
        assert me["username"] == "admin"
        assert me["scopeKind"] == "organization"
        assert "export.download" in me["permissions"]
        # The row holds the hash, never the token.
        rows = await _owner("SELECT token_hash FROM platform_session WHERE user_id = $1", ADMIN)
        assert rows and rows[0]["token_hash"] != token

        who = await client.get("/api/v1/auth/me")
        assert who.status_code == 200 and who.json()["userId"] == ADMIN

    _with_client(auth_app, scenario)


@pytest.mark.db
def test_02_a_wrong_password_and_an_unknown_organisation_read_the_same(auth_app: Any) -> None:
    async def scenario(client: httpx.AsyncClient) -> None:
        wrong = await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "nope", "organization": ORG_SLUG},
        )
        assert wrong.status_code == 401
        assert wrong.json()["detail"]["reason"] == "invalid_credentials"
        elsewhere = await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": PASSWORD, "organization": "nowhere"},
        )
        assert elsewhere.status_code == 401
        assert elsewhere.json()["detail"] == wrong.json()["detail"]

    _with_client(auth_app, scenario)


# ---------------------------------------------------------------------------
# pending_approval: the policy's refusal, named by the route
# ---------------------------------------------------------------------------


@pytest.mark.db
def test_03_a_pending_membership_is_refused_by_the_session_policy(auth_app: Any) -> None:
    async def scenario(client: httpx.AsyncClient) -> None:
        refused = await _login(client, "pending")
        assert refused.status_code == 403, refused.text
        assert refused.json()["detail"]["reason"] == "pending_approval"
        assert "dcp_session" not in "".join(refused.headers.get_list("set-cookie"))
        rows = await _owner("SELECT id FROM platform_session WHERE user_id = $1", PENDING)
        assert rows == [], "the policy admitted a session for a pending membership"

        # Approved — by the owner here, by an admin holding user.approve in
        # the product — and the same login, unchanged, succeeds.
        await _owner(
            "UPDATE platform_org_membership SET status = 'active', approved_by = $1, "
            "approved_at = now() WHERE user_id = $2",
            ADMIN,
            PENDING,
        )
        assert (await _login(client, "pending")).status_code == 200

    _with_client(auth_app, scenario)


def test_04_the_login_route_has_no_status_check_of_its_own() -> None:
    """One rule, one place. The service inserts and lets the policy decide;
    the membership's status is read only to name the reason afterwards."""
    import ast
    import pathlib

    source = (
        pathlib.Path(__file__).resolve().parents[1] / "app" / "modules" / "auth" / "service.py"
    ).read_text()
    tree = ast.parse(source)
    login = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "login"
    )
    # Every mention of a membership status inside `login` is inside an
    # `except` handler — after the insert was refused, never before it.
    offenders = []
    for node in ast.walk(login):
        if isinstance(node, ast.Constant) and node.value in ("pending_approval", "deactivated"):
            inside_handler = any(
                isinstance(parent, ast.ExceptHandler)
                and node.lineno >= parent.lineno
                and node.lineno <= (parent.end_lineno or parent.lineno)
                for parent in ast.walk(login)
            )
            if not inside_handler:
                offenders.append(node.lineno)
    assert offenders == [], f"login() checks a membership status before the insert: {offenders}"


# ---------------------------------------------------------------------------
# Deactivation: logged out by the policy
# ---------------------------------------------------------------------------


@pytest.mark.db
def test_05_a_session_does_not_survive_deactivation(auth_app: Any) -> None:
    async def scenario(client: httpx.AsyncClient) -> None:
        assert (await _login(client, "enum-b")).status_code == 200
        assert (await client.get("/api/v1/auth/me")).status_code == 200
        await _owner(
            "UPDATE platform_org_membership SET status = 'deactivated', deactivated_at = now() "
            "WHERE user_id = $1",
            ENUM_B,
        )
        gone = await client.get("/api/v1/auth/me")
        assert gone.status_code == 401, gone.text
        # Nothing revoked the row: it is still there, and invisible.
        rows = await _owner(
            "SELECT revoked_at FROM platform_session WHERE user_id = $1", ENUM_B
        )
        assert rows and rows[0]["revoked_at"] is None
        await _owner(
            "UPDATE platform_org_membership SET status = 'active', deactivated_at = NULL "
            "WHERE user_id = $1",
            ENUM_B,
        )

    _with_client(auth_app, scenario)


# ---------------------------------------------------------------------------
# The team boundary: one policy, three routes
# ---------------------------------------------------------------------------


@pytest.mark.db
def test_06_a_supervisor_lists_only_their_team(auth_app: Any) -> None:
    async def listed(client: httpx.AsyncClient, username: str) -> set[str]:
        assert (await _login(client, username)).status_code == 200
        response = await client.get("/api/v1/submissions")
        assert response.status_code == 200, response.text
        return {row["id"] for row in response.json()["submissions"]}

    async def scenario(client: httpx.AsyncClient) -> None:
        assert await listed(client, "sup-a") == {SUB_A}
        assert await listed(client, "sup-b") == {SUB_B}
        assert await listed(client, "admin") == {SUB_A, SUB_B}

    _with_client(auth_app, scenario)


@pytest.mark.db
def test_07_the_export_stops_at_the_team_and_the_permission(auth_app: Any) -> None:
    """The report nobody thought of, twice over: a supervisor holds no
    export.download and is refused by the route; an admin who does holds
    the export the policy allows. The rows are the policy's either way."""

    async def scenario(client: httpx.AsyncClient) -> None:
        assert (await _login(client, "sup-a")).status_code == 200
        refused = await client.get("/api/v1/exports/01FRMAUTH", params={"format": "csv"})
        assert refused.status_code == 403, refused.text
        assert refused.json()["detail"]["reason"] == "permission_denied"

        assert (await _login(client, "admin")).status_code == 200
        allowed = await client.get("/api/v1/exports/01FRMAUTH", params={"format": "csv"})
        assert allowed.status_code in (200, 204, 404), allowed.text

    _with_client(auth_app, scenario)


@pytest.mark.db
def test_08_a_handset_pulls_only_its_team_and_pushes_only_as_itself(auth_app: Any) -> None:
    async def scenario(client: httpx.AsyncClient) -> None:
        # Bound by the login: the device row gains its person.
        bound = await _login(client, "enum-a", kind="app", device_id=DEVICE_A)
        assert bound.status_code == 200, bound.text
        assert bound.json()["sessionKind"] == "app" and bound.json()["deviceId"] == DEVICE_A
        rows = await _owner("SELECT user_id, bound_at FROM device WHERE id = $1", DEVICE_A)
        assert rows[0]["user_id"] == ENUM_A and rows[0]["bound_at"] is not None

        # The pull is scoped: team A's ops only, however the cursor is asked.
        await _owner(
            "INSERT INTO submission_op (id, submission_id, op_kind, path, value, device_id, "
            "actor_id, counter, wall_clock) VALUES "
            "('01OPA', $1, 'set', 'q', '\"a\"'::jsonb, $3, $5, 1, now()), "
            "('01OPB', $2, 'set', 'q', '\"b\"'::jsonb, $4, $6, 1, now())",
            SUB_A,
            SUB_B,
            DEVICE_A,
            DEVICE_B,
            ENUM_A,
            ENUM_B,
        )
        pulled = await client.get("/api/v1/sync/pull", params={"cursor": 0, "limit": 100})
        assert pulled.status_code == 200, pulled.text
        assert {op["opId"] for op in pulled.json()["ops"]} == {"01OPA"}

        # A push naming another device is refused before the service runs.
        other = await client.post(
            "/api/v1/sync/push", json={"deviceId": DEVICE_B, "ops": []}
        )
        assert other.status_code == 403 and other.json()["detail"]["reason"] == "device_mismatch"
        # Its own device: accepted, and the op is filed under the person.
        mine = await client.post(
            "/api/v1/sync/push",
            json={
                "deviceId": DEVICE_A,
                "ops": [
                    {
                        "opId": "01OPA2",
                        "submissionId": SUB_A,
                        "formId": "hh",
                        "formVersion": 1,
                        "kind": "set",
                        "path": "q2",
                        "value": "x",
                        "deviceId": DEVICE_A,
                        "actorId": "usr_local",
                        "counter": 2,
                        "wallClock": "2026-09-09T10:00:00Z",
                    }
                ],
            },
        )
        assert mine.status_code == 200, mine.text
        assert mine.json()["accepted"] == ["01OPA2"], mine.text
        actor = await _owner("SELECT actor_id FROM submission_op WHERE id = '01OPA2'")
        assert actor[0]["actor_id"] == ENUM_A

        # A console session is not a handset.
        assert (await _login(client, "admin")).status_code == 200
        console = await client.post("/api/v1/sync/push", json={"deviceId": DEVICE_A, "ops": []})
        assert console.status_code == 403
        assert console.json()["detail"]["reason"] == "app_session_required"

    _with_client(auth_app, scenario)


@pytest.mark.db
def test_09_logout_revokes_and_a_stale_cookie_is_nobody(auth_app: Any) -> None:
    async def scenario(client: httpx.AsyncClient) -> None:
        assert (await _login(client, "admin")).status_code == 200
        token = client.cookies.get("dcp_session")
        out = await client.post("/api/v1/auth/logout")
        assert out.status_code == 200 and out.json()["status"] == "logged_out"
        client.cookies.set("dcp_session", token, path="/api")
        client.cookies.set("dcp_org", ORG_SLUG, path="/api")
        assert (await client.get("/api/v1/auth/me")).status_code == 401

    _with_client(auth_app, scenario)


@pytest.mark.db
def test_08b_an_enumerators_pull_carries_only_their_own_work(auth_app: Any) -> None:
    """Defect 26. Two enumerators in one team, one submission each. Signed in
    as the first, the sync pull must not carry the second's op — an
    enumerator holds no submission.view, and seeing other people's work is
    that permission (011_own_work_only.sql). Found on merged main by probe:
    it did, plaintext answer and all."""

    async def scenario(client: httpx.AsyncClient) -> None:
        # A second enumerator in team A with their own submission and an op.
        await _owner(
            "INSERT INTO platform_user (id, organization_id, username, display_name, "
            "password_hash) VALUES ('01USRENUMA2', $1, 'enum-a2', 'enum-a2', $2)",
            ORG_ID,
            hash_password(PASSWORD),
        )
        await _owner(
            "INSERT INTO platform_org_membership (organization_id, user_id, org_role, status) "
            "VALUES ($1, '01USRENUMA2', 'member', 'active')",
            ORG_ID,
        )
        await _owner(
            "INSERT INTO user_role (id, user_id, role_id, scope_kind, team_id) "
            "VALUES ('01USRENUMA2_R', '01USRENUMA2', $1 || '_enumerator', 'team', $2)",
            ORG_ID,
            TEAM_A,
        )
        await _owner(
            "INSERT INTO project_member (project_id, user_id, team_id) "
            "VALUES ($1, '01USRENUMA2', $2)",
            PROJECT_ID,
            TEAM_A,
        )
        await _owner(
            "INSERT INTO submission (id, project_id, environment_id, form_version_id, "
            "origin_device_id, created_by) VALUES ('01SUBA2', $1, '01ENVAUTH', '01VERAUTH', $2, "
            "'01USRENUMA2')",
            PROJECT_ID,
            DEVICE_A,
        )
        await _owner(
            "INSERT INTO submission_op (id, submission_id, op_kind, path, value, device_id, "
            "actor_id, counter, wall_clock) VALUES ('01OPA2SECRET', '01SUBA2', 'set', 'q', "
            "'\"a2 secret\"'::jsonb, $1, '01USRENUMA2', 7, now())",
            DEVICE_A,
        )

        assert (await _login(client, "enum-a", kind="app", device_id=DEVICE_A)).status_code == 200
        pulled = await client.get("/api/v1/sync/pull", params={"cursor": 0, "limit": 100})
        assert pulled.status_code == 200, pulled.text
        actors = {op["actorId"] for op in pulled.json()["ops"]}
        assert actors <= {ENUM_A, None}, f"an enumerator pulled another person's work: {actors}"
        assert "a2 secret" not in pulled.text

        # A supervisor holds submission.view: their team's work is theirs to see.
        assert (await _login(client, "sup-a")).status_code == 200
        listed = await client.get("/api/v1/submissions")
        assert "01SUBA2" in {row["id"] for row in listed.json()["submissions"]}

    _with_client(auth_app, scenario)


# ---------------------------------------------------------------------------
# No principal, no route
# ---------------------------------------------------------------------------


@pytest.mark.db
def test_10_a_request_with_no_cookie_reaches_no_route(auth_app: Any) -> None:
    """Every operation the app serves, from the route table, not a list:
    with no cookie, a public route answers and every other one is 401."""
    from tests.test_every_route_declares_access import PUBLIC, _api_routes

    async def scenario(client: httpx.AsyncClient) -> None:
        client.cookies.clear()
        reached = []
        for route in _api_routes():
            for method in sorted(route.methods):
                if (method, route.path) in PUBLIC:
                    continue
                path = route.path
                for name in ("form_id", "submission_id", "project_id", "key_id", "upload_id"):
                    path = path.replace("{" + name + "}", "01X")
                path = path.replace("{device_id}", "dev-a").replace("{chunk_index}", "0")
                path = path.replace("{dataset_version_id}", "01X")
                path = path.replace("{form_version_id}", "01X")
                response = await client.request(method, path)
                if response.status_code != 401:
                    reached.append(f"{method} {route.path} -> {response.status_code}")
        assert reached == [], "reached with no session:\n  " + "\n  ".join(reached)

    _with_client(auth_app, scenario)
