"""Cases, assignment and the boundary between them — with the database deciding.

Item 2's analysis (docs/phase3-item2-sample-assignment.md §8) names eight
breaks. The ones the schema can carry are here, and defect 26 is the template
for what they must catch: a leak with every screen correct, found only by two
people in one team, on the path with no route. So the tests that matter run
through `/sync/pull` and `/sync/push` over real cookies as enumerators, and
through the person's real principal against the policy where no route exists
yet. Nothing here calls a service that filters, because there is none: the
two SQL functions the schema provides are the writers, and the policies are
the readers.

The fixture: a project with two teams; a programme manager over it; a
supervisor and two enumerators in team A, a supervisor and one enumerator in
team B; a device per enumerator, bound; one form.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from fastapi import Request
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.infrastructure.database import (
    Principal,
    admin_connection,
    admin_url,
    create_admin_engine,
    create_engine,
    session_as,
)
from app.modules.auth import service as auth
from app.modules.auth.passwords import hash_password

CASES_DB = "dcp_test_cases"
ORG_ID, ORG_SLUG = "01ORGCASE", "cases"
PROJECT_ID = "01PRJCASE"
PASSWORD = "correct horse"
TEAM_A, TEAM_B = "01TEAMCA", "01TEAMCB"
PM, SUP_A, SUP_B, ENUM_A, ENUM_A2, ENUM_B = (
    "01UCPM",
    "01UCSUPA",
    "01UCSUPB",
    "01UCENUMA",
    "01UCENUMA2",
    "01UCENUMB",
)
DEVICES = {ENUM_A: "dev-ca", ENUM_A2: "dev-ca2", ENUM_B: "dev-cb", SUP_A: "dev-csa"}
K1, K2, K3, K4 = "S1|1|1", "S1|1|2", "S2|1|1", "S2|2|1"
C1, C2, C3, C4 = "01CASE1", "01CASE2", "01CASE3", "01CASE4"


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

    engine = create_admin_engine(database=CASES_DB)
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            session.add(PlatformOrganization(id=ORG_ID, name="Cases", slug=ORG_SLUG))
            await session.flush()
            await session.execute(
                text(
                    "INSERT INTO role (id, organization_id, name, scope_kind, builtin) VALUES "
                    "(:o || '_pm', :o, 'Programme manager', 'project', true), "
                    "(:o || '_supervisor', :o, 'Supervisor', 'team', true), "
                    "(:o || '_enumerator', :o, 'Enumerator', 'team', true)"
                ),
                {"o": ORG_ID},
            )
            await session.execute(
                text(
                    "INSERT INTO role_permission (role_id, permission) "
                    "SELECT :o || '_pm', p FROM unnest(ARRAY['user.create', 'user.approve', "
                    "'user.assign_role', 'team.manage', 'sample.upload', 'sample.assign', "
                    "'submission.view', 'submission.review', 'export.download']) AS p "
                    "UNION ALL SELECT :o || '_supervisor', p FROM unnest(ARRAY['user.create', "
                    "'user.assign_role', 'sample.assign', 'submission.view']) AS p"
                ),
                {"o": ORG_ID},
            )
            session.add(Project(id=PROJECT_ID, organization_id=ORG_ID, name="P", slug="cases"))
            await session.flush()
            session.add(Environment(id="01ENVCASE", project_id=PROJECT_ID, kind="production"))
            session.add(Form(id="01FRMCASE", project_id=PROJECT_ID, form_key="hh", title="HH"))
            for team_id, name in ((TEAM_A, "Team A"), (TEAM_B, "Team B")):
                session.add(Team(id=team_id, project_id=PROJECT_ID, name=name))
            await session.flush()
            session.add(
                FormVersion(id="01VERCASE", form_id="01FRMCASE", version=1, ir={}, ir_checksum="x")
            )
            people = (
                (PM, "pm", "pm", "project", PROJECT_ID, None),
                (SUP_A, "sup-a", "supervisor", "team", None, TEAM_A),
                (SUP_B, "sup-b", "supervisor", "team", None, TEAM_B),
                (ENUM_A, "enum-a", "enumerator", "team", None, TEAM_A),
                (ENUM_A2, "enum-a2", "enumerator", "team", None, TEAM_A),
                (ENUM_B, "enum-b", "enumerator", "team", None, TEAM_B),
            )
            for user_id, username, _r, _s, _p, _t in people:
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
            for user_id, _u, role, scope, project_id, team_id in people:
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
                session.add(
                    ProjectMember(project_id=PROJECT_ID, user_id=user_id, team_id=team_id)
                )
            await session.flush()
            for user_id, device_id in DEVICES.items():
                session.add(
                    Device(
                        id=device_id,
                        project_id=PROJECT_ID,
                        platform="android",
                        user_id=user_id,
                        bound_at=func.now(),
                    )
                )
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def cases_app() -> Any:
    from alembic import command
    from alembic.config import Config

    from tests.test_migrations import BACKEND_DIR

    async def prepare() -> str | None:
        try:
            async with admin_connection(timeout=3) as conn:
                await conn.execute(f"DROP DATABASE IF EXISTS {CASES_DB} WITH (FORCE)")
                await conn.execute(f"CREATE DATABASE {CASES_DB}")
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
    cfg.set_main_option("sqlalchemy.url", admin_url(CASES_DB))
    command.upgrade(cfg, "head")
    _run(_seed())

    from app.api.access import organization_slug
    from app.api.deps import get_db
    from app.infrastructure.database import session_for_organization
    from app.main import app

    async def anonymous(request: Request) -> Any:
        engine = create_engine(database=CASES_DB)
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
            await conn.execute(f"DROP DATABASE IF EXISTS {CASES_DB} WITH (FORCE)")

    _run(drop())


# ---------------------------------------------------------------------------
# Helpers: a person's real principal, and what they see
# ---------------------------------------------------------------------------


async def _principal_of(engine: AsyncEngine, username: str) -> Principal:
    async with session_as(Principal(org_id=ORG_ID, org_slug=ORG_SLUG), engine=engine) as s:
        found = (
            await s.execute(text("SELECT * FROM dcp_login_lookup(:u)"), {"u": username})
        ).mappings().one()
        person = auth.Person(
            found["id"], found["organization_id"], found["username"], found["display_name"]
        )
        principal, _ = await auth.principal_for(s, person, ORG_SLUG)
        return principal


async def _cases_seen(engine: AsyncEngine, principal: Principal) -> set[str]:
    async with session_as(principal, engine=engine) as s:
        return set((await s.execute(text("SELECT id FROM case_record"))).scalars())


async def _submissions_seen(engine: AsyncEngine, principal: Principal) -> set[str]:
    from app.modules.submissions.models import Submission

    async with session_as(principal, engine=engine) as s:
        return set((await s.execute(select(Submission.id))).scalars())


async def _as(engine: AsyncEngine, principal: Principal, sql: str, **params: Any) -> Any:
    async with session_as(principal, engine=engine) as s, s.begin():
        result = await s.execute(text(sql), params)
        return result.mappings().all() if result.returns_rows else []


def _refused_by_policy(error: BaseException) -> bool:
    return isinstance(error, DBAPIError) and "row-level security" in str(error.orig)


async def _refused(engine: AsyncEngine, principal: Principal, sql: str, **params: Any) -> None:
    async with session_as(principal, engine=engine) as s:
        with pytest.raises(DBAPIError) as error:
            async with s.begin():
                await s.execute(text(sql), params)
        assert _refused_by_policy(error.value), str(error.value)[:200]


Scenario = Callable[[httpx.AsyncClient], Awaitable[None]]


def _with_client(app: Any, scenario: Scenario) -> None:
    async def main() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await scenario(client)

    _run(main())


async def _login(client: httpx.AsyncClient, username: str, user_id: str) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "username": username,
            "password": PASSWORD,
            "organization": ORG_SLUG,
            "kind": "app",
            "deviceId": DEVICES[user_id],
        },
    )
    assert response.status_code == 200, response.text


async def _owner(sql: str, *args: Any) -> Any:
    async with admin_connection(CASES_DB) as conn:
        return await conn.fetch(sql, *args)


ASSIGN = "SELECT dcp_assign_case(:c, :team, :person, :id)"
UPSERT = "SELECT * FROM dcp_upsert_cases(:p, :d, :keys, :ids)"


# ---------------------------------------------------------------------------
# 1. The sample becomes cases; nobody but the manager sees them yet
# ---------------------------------------------------------------------------


@pytest.mark.db
def test_01_the_upload_makes_cases_the_manager_sees_and_nobody_else(cases_app: Any) -> None:
    async def go() -> None:
        engine = create_engine(database=CASES_DB)
        try:
            pm = await _principal_of(engine, "pm")
            counts = await _as(
                engine, pm, UPSERT, p=PROJECT_ID, d="hh_sample", keys=[K1, K2, K3], ids=[C1, C2, C3]
            )
            assert dict(counts[0]) == {"created": 3, "reopened": 0, "withdrawn": 0}
            assert await _cases_seen(engine, pm) == {C1, C2, C3}
            # Unassigned: the pool the manager has not split is nobody else's (A6).
            assert await _cases_seen(engine, await _principal_of(engine, "sup-a")) == set()
            assert await _cases_seen(engine, await _principal_of(engine, "enum-a")) == set()
            # And a supervisor cannot make cases: sample.upload is the manager's.
            await _refused(
                engine,
                await _principal_of(engine, "sup-a"),
                UPSERT,
                p=PROJECT_ID,
                d="hh_sample",
                keys=["X"],
                ids=["01CASEX"],
            )
        finally:
            await engine.dispose()

    _run(go())


# ---------------------------------------------------------------------------
# 2. Two levels of assignment, and who sees what at each (break 5)
# ---------------------------------------------------------------------------


@pytest.mark.db
def test_02_the_manager_splits_by_team_and_the_supervisor_by_person(cases_app: Any) -> None:
    async def go() -> None:
        engine = create_engine(database=CASES_DB)
        try:
            pm = await _principal_of(engine, "pm")
            splits = ((C1, TEAM_A, "01ASG1"), (C2, TEAM_A, "01ASG2"), (C3, TEAM_B, "01ASG3"))
            for case, team, aid in splits:
                await _as(engine, pm, ASSIGN, c=case, team=team, person=None, id=aid)
            sup_a = await _principal_of(engine, "sup-a")
            sup_b = await _principal_of(engine, "sup-b")
            assert await _cases_seen(engine, sup_a) == {C1, C2}
            assert await _cases_seen(engine, sup_b) == {C3}
            # Held by the team, by nobody personally: no enumerator sees it yet.
            assert await _cases_seen(engine, await _principal_of(engine, "enum-a")) == set()

            await _as(engine, sup_a, ASSIGN, c=C1, team=None, person=ENUM_A, id="01ASG4")
            assert await _cases_seen(engine, await _principal_of(engine, "enum-a")) == {C1}
            assert await _cases_seen(engine, await _principal_of(engine, "enum-a2")) == set()
            # The supervisor still sees it: held by a person in their team.
            assert await _cases_seen(engine, sup_a) == {C1, C2}
        finally:
            await engine.dispose()

    _run(go())


# ---------------------------------------------------------------------------
# 3. Assignment outside the assigner's scope, and above the model (A3)
# ---------------------------------------------------------------------------


@pytest.mark.db
def test_03_an_assignment_outside_scope_or_beyond_the_model_is_refused(cases_app: Any) -> None:
    async def go() -> None:
        engine = create_engine(database=CASES_DB)
        try:
            sup_a = await _principal_of(engine, "sup-a")
            pm = await _principal_of(engine, "pm")
            # Team B's case is not sup-a's to touch.
            await _refused(engine, sup_a, ASSIGN, c=C3, team=None, person=ENUM_A, id="01ASGX")
            # A person sup-a cannot see (team B's enumerator).
            await _refused(engine, sup_a, ASSIGN, c=C2, team=None, person=ENUM_B, id="01ASGX")
            # A person not in the holding team, even for the manager (A3: a
            # person assignment lives under a live team assignment).
            await _refused(engine, pm, ASSIGN, c=C3, team=None, person=ENUM_A, id="01ASGX")
            # A supervisor cannot assign at the team level.
            await _refused(engine, sup_a, ASSIGN, c=C2, team=TEAM_A, person=None, id="01ASGX")
            # A person who cannot sign in cannot hold a case (014, found in
            # the browser run): a pending membership refuses the assignment,
            # for the manager too; approval makes the same assignment valid.
            await _owner(
                "UPDATE platform_org_membership SET status = 'pending_approval', "
                "approved_by = NULL, approved_at = NULL WHERE user_id = $1",
                ENUM_A2,
            )
            await _refused(engine, sup_a, ASSIGN, c=C2, team=None, person=ENUM_A2, id="01ASGX")
            await _refused(engine, pm, ASSIGN, c=C2, team=None, person=ENUM_A2, id="01ASGX")
            await _owner(
                "UPDATE platform_org_membership SET status = 'active', approved_by = $2, "
                "approved_at = now() WHERE user_id = $1",
                ENUM_A2,
                PM,
            )
            # (Approved again, enum-a2 holds C1 a few lines down — the same
            # assignment shape the pending membership just refused.)

            # At most one live holder per level: a second live person
            # assignment on C1 is refused by the index, not by a service.
            async with session_as(pm, engine=engine) as s:
                with pytest.raises(IntegrityError):
                    async with s.begin():
                        await s.execute(
                            text(
                                "INSERT INTO assignment (id, case_id, user_id) "
                                "VALUES ('01ASGDUP', :c, :u)"
                            ),
                            {"c": C1, "u": ENUM_A2},
                        )
            # Through the function, the old holder is released first.
            await _as(engine, sup_a, ASSIGN, c=C1, team=None, person=ENUM_A2, id="01ASG5")
            assert await _cases_seen(engine, await _principal_of(engine, "enum-a2")) == {C1}
            assert await _cases_seen(engine, await _principal_of(engine, "enum-a")) == set()
            live = await _owner(
                "SELECT user_id FROM assignment WHERE case_id = $1 AND released_at IS NULL "
                "AND user_id IS NOT NULL",
                C1,
            )
            assert [r["user_id"] for r in live] == [ENUM_A2]
            # Back to enum-a for the rest of the file.
            await _as(engine, sup_a, ASSIGN, c=C1, team=None, person=ENUM_A, id="01ASG6")
            await _as(engine, sup_a, ASSIGN, c=C2, team=None, person=ENUM_A, id="01ASG7")
        finally:
            await engine.dispose()

    _run(go())


# ---------------------------------------------------------------------------
# 4. Work on a case: mine to open, refused on one I do not hold (break 3)
# ---------------------------------------------------------------------------

NEW_SUBMISSION = (
    "INSERT INTO submission (id, project_id, environment_id, form_version_id, "
    "origin_device_id, created_by, case_id) "
    "VALUES (:id, :p, '01ENVCASE', '01VERCASE', :dev, :me, :c)"
)
NEW_OP = (
    "INSERT INTO submission_op (id, submission_id, op_kind, path, value, device_id, "
    "actor_id, counter, wall_clock) VALUES (:id, :sub, 'set', 'q', :v, :dev, :me, :n, now())"
)


@pytest.mark.db
def test_04_an_enumerator_opens_work_on_their_case_and_not_on_another(cases_app: Any) -> None:
    async def go() -> None:
        engine = create_engine(database=CASES_DB)
        try:
            enum_a = await _principal_of(engine, "enum-a")
            mine = {"p": PROJECT_ID, "dev": DEVICES[ENUM_A], "me": ENUM_A}
            await _as(engine, enum_a, NEW_SUBMISSION, id="01SUBC2", c=C2, **mine)
            await _as(
                engine, enum_a, NEW_OP, id="01OPC2A", sub="01SUBC2", v='"visit 1"',
                dev=DEVICES[ENUM_A], me=ENUM_A, n=1,
            )
            # C3 is team B's: new work on it is refused by the policy.
            await _refused(engine, enum_a, NEW_SUBMISSION, id="01SUBC3", c=C3, **mine)
            # Uncased work is always one's own to open.
            await _as(engine, enum_a, NEW_SUBMISSION, id="01SUBNONE", c=None, **mine)
            assert await _submissions_seen(engine, enum_a) == {"01SUBC2", "01SUBNONE"}
            # A teammate sees neither: an enumerator's work is their own (011).
            assert await _submissions_seen(engine, await _principal_of(engine, "enum-a2")) == set()
            # The supervisor sees both: the cased one through the case, the
            # uncased one through submission.view over the team.
            assert await _submissions_seen(engine, await _principal_of(engine, "sup-a")) == {
                "01SUBC2",
                "01SUBNONE",
            }
        finally:
            await engine.dispose()

    _run(go())


# ---------------------------------------------------------------------------
# 5. Reassignment: the view moves, the rows do not (breaks 1, 2), on the
#    path with no route — the handset pull — as well as the policies
# ---------------------------------------------------------------------------


@pytest.mark.db
def test_05_reassigning_a_case_moves_its_work_and_the_pull_follows(cases_app: Any) -> None:
    async def scenario(client: httpx.AsyncClient) -> None:
        engine = create_engine(database=CASES_DB)
        try:
            pm = await _principal_of(engine, "pm")
            sup_a = await _principal_of(engine, "sup-a")
            sup_b = await _principal_of(engine, "sup-b")

            # Before the move: B's side sees nothing of C2, on every path.
            assert "01SUBC2" not in await _submissions_seen(engine, sup_b)
            await _login(client, "enum-b", ENUM_B)
            before = await client.get("/api/v1/sync/pull", params={"cursor": 0, "limit": 100})
            assert "01OPC2A" not in {op["opId"] for op in before.json()["ops"]}

            # The move: team A -> team B by the manager, then to enum-b by B's
            # supervisor. Two statements; nothing under the case is touched.
            await _as(engine, pm, ASSIGN, c=C2, team=TEAM_B, person=None, id="01ASG8")
            await _as(engine, sup_b, ASSIGN, c=C2, team=None, person=ENUM_B, id="01ASG9")
            rows = await _owner("SELECT case_id, created_by FROM submission WHERE id = '01SUBC2'")
            assert (rows[0]["case_id"], rows[0]["created_by"]) == (C2, ENUM_A)

            # Break 1. Supervisor A: the case and its submission are gone.
            assert C2 not in await _cases_seen(engine, sup_a)
            assert "01SUBC2" not in await _submissions_seen(engine, sup_a)
            # Supervisor B: both are there, history included.
            assert C2 in await _cases_seen(engine, sup_b)
            assert "01SUBC2" in await _submissions_seen(engine, sup_b)
            # The enumerator who collected it keeps seeing it; the case, no.
            enum_a = await _principal_of(engine, "enum-a")
            assert "01SUBC2" in await _submissions_seen(engine, enum_a)
            assert C2 not in await _cases_seen(engine, enum_a)
            # A teammate of the collector never sees it, before or after.
            assert "01SUBC2" not in await _submissions_seen(
                engine, await _principal_of(engine, "enum-a2")
            )

            # The handset path: enum-b's pull now carries the case's op; enum-a2's does not.
            after = await client.get("/api/v1/sync/pull", params={"cursor": 0, "limit": 100})
            assert "01OPC2A" in {op["opId"] for op in after.json()["ops"]}, after.text
            await _login(client, "enum-a2", ENUM_A2)
            other = await client.get("/api/v1/sync/pull", params={"cursor": 0, "limit": 100})
            assert "01OPC2A" not in {op["opId"] for op in other.json()["ops"]}

            # Break 2. An op in flight from enum-a after the move: accepted,
            # attributed to them, visible to B's supervisor.
            await _login(client, "enum-a", ENUM_A)
            pushed = await client.post(
                "/api/v1/sync/push",
                json={
                    "deviceId": DEVICES[ENUM_A],
                    "ops": [
                        {
                            "opId": "01OPC2B",
                            "submissionId": "01SUBC2",
                            "formId": "hh",
                            "formVersion": 1,
                            "kind": "set",
                            "path": "q2",
                            "value": "after the move",
                            "deviceId": DEVICES[ENUM_A],
                            "actorId": "usr_local",
                            "counter": 2,
                            "wallClock": "2026-09-09T12:00:00Z",
                        }
                    ],
                },
            )
            assert pushed.status_code == 200, pushed.text
            assert pushed.json()["accepted"] == ["01OPC2B"], pushed.text
            async with session_as(sup_b, engine=engine) as s:
                ops = set(
                    (
                        await s.execute(
                            text("SELECT id FROM submission_op WHERE submission_id = '01SUBC2'")
                        )
                    ).scalars()
                )
            assert ops == {"01OPC2A", "01OPC2B"}

            # Break 3 on this path — the first op of a NEW submission naming the
            # moved case, rejected `not_assigned` — lands with the routes, when
            # the wire carries caseId. The policy that refuses it is test_04's.
        finally:
            await engine.dispose()

    _with_client(cases_app, scenario)


# ---------------------------------------------------------------------------
# 6. Re-upload of the sample (break 7): keys stay, keys go, keys come back
# ---------------------------------------------------------------------------


@pytest.mark.db
def test_06_a_reupload_keeps_withdraws_and_reopens_by_key(cases_app: Any) -> None:
    async def go() -> None:
        engine = create_engine(database=CASES_DB)
        try:
            pm = await _principal_of(engine, "pm")
            counts = await _as(
                engine, pm, UPSERT,
                p=PROJECT_ID, d="hh_sample", keys=[K1, K3, K4], ids=[C1, C3, C4],
            )
            assert dict(counts[0]) == {"created": 1, "reopened": 0, "withdrawn": 1}
            rows = await _owner(
                "SELECT id, status, closed_at IS NOT NULL AS closed FROM case_record ORDER BY id"
            )
            assert {(r["id"], r["status"], r["closed"]) for r in rows} == {
                (C1, "open", False),
                (C2, "withdrawn", True),
                (C3, "open", False),
                (C4, "open", False),
            }
            stones = await _owner(
                "SELECT subject_id FROM tombstone WHERE subject_type = 'case'"
            )
            assert [s["subject_id"] for s in stones] == [C2]
            # C1's assignment survived the re-upload; C2's is still there too,
            # released or not — the case is withdrawn, not gone, and its
            # submission is still its holder's to see.
            assert await _cases_seen(engine, await _principal_of(engine, "enum-a")) >= {C1}
            sup_b = await _principal_of(engine, "sup-b")
            assert "01SUBC2" in await _submissions_seen(engine, sup_b)
            # The row comes back: the same case reopens, nothing is duplicated.
            again = await _as(
                engine, pm, UPSERT,
                p=PROJECT_ID, d="hh_sample", keys=[K1, K2, K3, K4], ids=[C1, C2, C3, C4],
            )
            assert dict(again[0]) == {"created": 0, "reopened": 1, "withdrawn": 0}
            # And nobody can delete a case, the manager included.
            await _refused_delete(engine, pm)
        finally:
            await engine.dispose()

    _run(go())


async def _refused_delete(engine: AsyncEngine, principal: Principal) -> None:
    async with session_as(principal, engine=engine) as s, s.begin():
        result = await s.execute(text("DELETE FROM case_record WHERE id = :c"), {"c": C4})
        assert result.rowcount == 0, "a case was deleted"


# ---------------------------------------------------------------------------
# 7. The routes: the sample upload, the split, the statement a device pulls,
#    and the one scope refusal in the push path — named, not a 500
# ---------------------------------------------------------------------------


async def _console_login(client: httpx.AsyncClient, username: str) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORD, "organization": ORG_SLUG},
    )
    assert response.status_code == 200, response.text


SAMPLE_CSV = (
    "settlementCode,structureId,hhId,headName\n"
    "S3,1,1,Amina\n"
    "S3,1,2,Bakari\n"
    "S3,2,1,Chausiku\n"
)


@pytest.mark.db
def test_07_the_sample_upload_makes_cases_the_manager_splits_by_route(cases_app: Any) -> None:
    async def scenario(client: httpx.AsyncClient) -> None:
        # A supervisor cannot upload: the route refuses before the policy would.
        await _console_login(client, "sup-a")
        refused = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/samples",
            files={"file": ("sample.csv", SAMPLE_CSV, "text/csv")},
            data={"datasetKey": "village", "keyColumns": "settlementCode,structureId,hhId"},
        )
        assert refused.status_code == 403, refused.text

        await _console_login(client, "pm")
        uploaded = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/samples",
            files={"file": ("sample.csv", SAMPLE_CSV, "text/csv")},
            data={"datasetKey": "village", "keyColumns": "settlementCode,structureId,hhId"},
        )
        assert uploaded.status_code == 201, uploaded.text
        body = uploaded.json()
        assert (body["casesCreated"], body["casesWithdrawn"], body["rowCount"]) == (3, 0, 3)
        assert body["keyColumns"] == ["settlementCode", "structureId", "hhId"]

        listed = await client.get("/api/v1/cases", params={"projectId": PROJECT_ID})
        assert listed.status_code == 200, listed.text
        village = {c["caseKey"]: c for c in listed.json()["cases"] if c["datasetKey"] == "village"}
        assert set(village) == {"S3|1|1", "S3|1|2", "S3|2|1"}
        assert village["S3|1|1"]["data"]["headName"] == "Amina"
        assert village["S3|1|1"]["holder"]["teamId"] is None

        # A row with no identity in a key column refuses the upload, naming it.
        bad = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/samples",
            files={"file": ("bad.csv", "settlementCode,hhId\nS9,\n", "text/csv")},
            data={"datasetKey": "bad", "keyColumns": "settlementCode,hhId"},
        )
        assert bad.status_code == 400 and bad.json()["detail"]["reason"] == "bad_key_row"
        assert "hhId" in bad.json()["detail"]["message"]

        # The split by team, in one request; then supervisor A splits by person.
        ids = [village[k]["id"] for k in ("S3|1|1", "S3|1|2")]
        split = await client.post("/api/v1/cases/assign", json={"caseIds": ids, "teamId": TEAM_A})
        assert split.status_code == 200 and split.json()["assigned"] == 2
        other = await client.post(
            "/api/v1/cases/assign", json={"caseIds": [village["S3|2|1"]["id"]], "teamId": TEAM_B}
        )
        assert other.status_code == 200

        await _console_login(client, "sup-a")
        mine = await client.get("/api/v1/cases", params={"projectId": PROJECT_ID})
        seen = {c["caseKey"] for c in mine.json()["cases"] if c["datasetKey"] == "village"}
        assert seen == {"S3|1|1", "S3|1|2"}, "supervisor A sees another team's or the pool"
        assigned = await client.post(
            f"/api/v1/cases/{ids[0]}/assign",
            params={"projectId": PROJECT_ID},
            json={"userId": ENUM_A},
        )
        assert assigned.status_code == 200, assigned.text
        holder = next(c for c in assigned.json()["cases"] if c["id"] == ids[0])["holder"]
        assert (holder["teamName"], holder["userName"]) == ("Team A", "enum-a")
        # Outside their team: refused by the database, named.
        outside = await client.post(
            f"/api/v1/cases/{village['S3|2|1']['id']}/assign",
            params={"projectId": PROJECT_ID},
            json={"userId": ENUM_A},
        )
        assert outside.status_code == 403
        assert outside.json()["detail"]["reason"] == "outside_your_authority"

    _with_client(cases_app, scenario)


@pytest.mark.db
def test_08_a_device_pulls_its_assignments_as_a_statement_and_notices_a_release(
    cases_app: Any,
) -> None:
    """The piece §4.3 of the analysis rests on: a release is an absence."""

    async def scenario(client: httpx.AsyncClient) -> None:
        await _login(client, "enum-a", ENUM_A)
        pulled = await client.get(
            "/api/v1/sync/pull", params={"cursor": 0, "limit": 10, "scope": "assignments"}
        )
        assert pulled.status_code == 200, pulled.text
        statement = pulled.json()["assignments"]
        assert statement is not None
        held = {a["caseKey"]: a for a in statement}
        assert "S3|1|1" in held and held["S3|1|1"]["data"]["headName"] == "Amina"
        assert "S3|1|2" not in held  # team A's, but nobody's personally
        # Without the scope: null, not an empty statement.
        plain = await client.get("/api/v1/sync/pull", params={"cursor": 0, "limit": 10})
        assert plain.json()["assignments"] is None

        # Opening work against a held case, over push, with caseId on the wire.
        case_id = held["S3|1|1"]["caseId"]
        opened = await client.post(
            "/api/v1/sync/push",
            json={
                "deviceId": DEVICES[ENUM_A],
                "ops": [
                    {
                        "opId": "01OPS311",
                        "submissionId": "01SUBS311",
                        "formId": "hh",
                        "formVersion": 1,
                        "kind": "set",
                        "path": "q",
                        "value": "first",
                        "deviceId": DEVICES[ENUM_A],
                        "actorId": "usr_local",
                        "caseId": case_id,
                        "counter": 10,
                        "wallClock": "2026-09-09T13:00:00Z",
                    }
                ],
            },
        )
        assert opened.status_code == 200 and opened.json()["accepted"] == ["01OPS311"], opened.text
        rows = await _owner("SELECT case_id FROM submission WHERE id = '01SUBS311'")
        assert rows[0]["case_id"] == case_id

        # The supervisor moves the case to enum-a2. The next statement lacks
        # it; the submission and its op are still enum-a's to see and push.
        engine = create_engine(database=CASES_DB)
        try:
            sup_a = await _principal_of(engine, "sup-a")
            await _as(engine, sup_a, ASSIGN, c=case_id, team=None, person=ENUM_A2, id="01ASGS")
        finally:
            await engine.dispose()
        after = await client.get(
            "/api/v1/sync/pull", params={"cursor": 0, "limit": 10, "scope": "assignments"}
        )
        assert "S3|1|1" not in {a["caseKey"] for a in after.json()["assignments"]}
        assert "01OPS311" in {op["opId"] for op in after.json()["ops"]}
        more = await client.post(
            "/api/v1/sync/push",
            json={
                "deviceId": DEVICES[ENUM_A],
                "ops": [
                    {
                        "opId": "01OPS311B",
                        "submissionId": "01SUBS311",
                        "formId": "hh",
                        "formVersion": 1,
                        "kind": "set",
                        "path": "q2",
                        "value": "finished after the move",
                        "deviceId": DEVICES[ENUM_A],
                        "actorId": "usr_local",
                        "caseId": case_id,
                        "counter": 11,
                        "wallClock": "2026-09-09T13:05:00Z",
                    }
                ],
            },
        )
        assert more.json()["accepted"] == ["01OPS311B"], more.text

        # New work against the moved case: the named refusal, not a 500, and
        # the rest of the batch is untouched.
        fresh = await client.post(
            "/api/v1/sync/push",
            json={
                "deviceId": DEVICES[ENUM_A],
                "ops": [
                    {
                        "opId": "01OPNEW1",
                        "submissionId": "01SUBNEW1",
                        "formId": "hh",
                        "formVersion": 1,
                        "kind": "set",
                        "path": "q",
                        "value": "x",
                        "deviceId": DEVICES[ENUM_A],
                        "actorId": "usr_local",
                        "caseId": case_id,
                        "counter": 12,
                        "wallClock": "2026-09-09T13:06:00Z",
                    },
                    {
                        "opId": "01OPNEW2",
                        "submissionId": "01SUBNEW2",
                        "formId": "hh",
                        "formVersion": 1,
                        "kind": "set",
                        "path": "q",
                        "value": "uncased, still mine to open",
                        "deviceId": DEVICES[ENUM_A],
                        "actorId": "usr_local",
                        "counter": 13,
                        "wallClock": "2026-09-09T13:07:00Z",
                    },
                ],
            },
        )
        assert fresh.status_code == 200, fresh.text
        assert fresh.json()["rejected"] == [{"opId": "01OPNEW1", "reason": "not_assigned"}]
        assert fresh.json()["accepted"] == ["01OPNEW2"]

        # The statement is the live assignments, not the visible ones. An
        # enumerator loses sight of a released case with the release; a
        # supervisor who held one personally still sees the case through the
        # team — and must still notice the release by its absence.
        rows = await _owner("SELECT id FROM case_record WHERE case_key = 'S3|1|2'")
        team_case = rows[0]["id"]
        engine = create_engine(database=CASES_DB)
        try:
            pm = await _principal_of(engine, "pm")
            await _as(engine, pm, ASSIGN, c=team_case, team=None, person=SUP_A, id="01ASGSA")
        finally:
            await engine.dispose()
        await _login(client, "sup-a", SUP_A)
        held_by_sup = await client.get(
            "/api/v1/sync/pull", params={"cursor": 0, "limit": 10, "scope": "assignments"}
        )
        assert {a["caseKey"] for a in held_by_sup.json()["assignments"]} == {"S3|1|2"}
        engine = create_engine(database=CASES_DB)
        try:
            pm = await _principal_of(engine, "pm")
            await _as(engine, pm, ASSIGN, c=team_case, team=None, person=ENUM_A2, id="01ASGSB")
        finally:
            await engine.dispose()
        released = await client.get(
            "/api/v1/sync/pull", params={"cursor": 0, "limit": 10, "scope": "assignments"}
        )
        assert released.json()["assignments"] == [], "a released case is still in the statement"

    _with_client(cases_app, scenario)
