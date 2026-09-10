"""What a supervisor may count, and that it is the same thing they may list.

Item 5's guard, and the whole item rests on it: every number a monitoring
screen shows is a `COUNT` over the same policy-carrying table its list reads,
on the same connection under the same principal. Row-level security filters an
aggregate exactly as it filters a select, so the two agree by construction —
until somebody writes a second query "for counting", which is what this
catches.

**Agreement alone proves nothing**, and that is why a supervisor carries this
file. A policy that showed everything to everyone would satisfy "aggregate
equals enumeration" for every principal: both numbers would be the project's
total, and they would match. An admin and a programme manager pass such a
policy by definition. So each assertion comes in three parts:

1. the aggregate equals the enumeration, per principal;
2. a supervisor's figure is strictly less than the organisation-wide figure —
   which fails the moment a policy starts showing everything;
3. a supervisor's figure equals the fixture's known subset exactly — which
   fails if a policy starts showing too little, the failure "strictly less"
   would otherwise reward.

The fixture: two teams; an org-wide admin, a project-scoped manager, a
supervisor and an enumerator in each team. One case per team, plus **a case in
neither team's hands**. One submission per enumerator. Three devices: one per
enumerator, and **one registered and never signed in on**, which belongs to
nobody and is visible only org-wide (015). That last row is the reason this
fixture is not item 2's: the device panel's count and its list must agree
about the rows nobody owns, and only a fixture that has some can say so.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
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

MON_DB = "dcp_test_monitor"
ORG_ID, ORG_SLUG = "01ORGMON", "monitor"
PROJECT_ID = "01PRJMON"
PASSWORD = "correct horse"
TEAM_A, TEAM_B = "01TEAMMA", "01TEAMMB"
ADMIN, PM, SUP_A, SUP_B, ENUM_A, ENUM_B = (
    "01UMADMIN",
    "01UMPM",
    "01UMSUPA",
    "01UMSUPB",
    "01UMENUMA",
    "01UMENUMB",
)
DEV_A, DEV_B, DEV_UNBOUND = "dev-ma", "dev-mb", "dev-unclaimed"
CASE_A, CASE_B, CASE_NOBODY = "01CASEMA", "01CASEMB", "01CASEMN"
SUB_A, SUB_B, SUB_NOBODY = "01SUBMA", "01SUBMB", "01SUBMN"


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

    engine = create_admin_engine(database=MON_DB)
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            session.add(PlatformOrganization(id=ORG_ID, name="Monitor", slug=ORG_SLUG))
            await session.flush()
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
                    "SELECT :o || '_admin', p FROM unnest(ARRAY['user.create', 'user.approve', "
                    "'team.manage', 'sample.upload', 'sample.assign', 'submission.view']) AS p "
                    "UNION ALL SELECT :o || '_pm', p FROM unnest(ARRAY['sample.upload', "
                    "'sample.assign', 'submission.view']) AS p "
                    "UNION ALL SELECT :o || '_supervisor', p FROM unnest(ARRAY['sample.assign', "
                    "'submission.view']) AS p"
                ),
                {"o": ORG_ID},
            )
            session.add(Project(id=PROJECT_ID, organization_id=ORG_ID, name="P", slug="monitor"))
            await session.flush()
            session.add(Environment(id="01ENVMON", project_id=PROJECT_ID, kind="production"))
            session.add(Form(id="01FRMMON", project_id=PROJECT_ID, form_key="hh", title="HH"))
            for team_id, name in ((TEAM_A, "Team A"), (TEAM_B, "Team B")):
                session.add(Team(id=team_id, project_id=PROJECT_ID, name=name))
            await session.flush()
            session.add(
                FormVersion(id="01VERMON", form_id="01FRMMON", version=1, ir={}, ir_checksum="x")
            )
            people = (
                (ADMIN, "admin", "admin", "organization", None, None),
                (PM, "pm", "pm", "project", PROJECT_ID, None),
                (SUP_A, "sup-a", "supervisor", "team", None, TEAM_A),
                (SUP_B, "sup-b", "supervisor", "team", None, TEAM_B),
                (ENUM_A, "enum-a", "enumerator", "team", None, TEAM_A),
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
                if team_id is not None or role in ("pm",):
                    session.add(
                        ProjectMember(project_id=PROJECT_ID, user_id=user_id, team_id=team_id)
                    )
            await session.flush()
            for device_id, user_id in ((DEV_A, ENUM_A), (DEV_B, ENUM_B)):
                session.add(
                    Device(
                        id=device_id,
                        project_id=PROJECT_ID,
                        platform="android",
                        user_id=user_id,
                        bound_at=func.now(),
                    )
                )
            # Registered and never signed in on: nobody's, and the row the
            # device panel's count and list must agree about.
            session.add(
                Device(id=DEV_UNBOUND, project_id=PROJECT_ID, platform="android", user_id=None)
            )
            await session.flush()
            # Two cases held, one held by nobody.
            await session.execute(
                text(
                    "INSERT INTO case_record (id, project_id, dataset_key, case_key, status) "
                    "VALUES (:a, :p, 'hh', 'A|1', 'open'), (:b, :p, 'hh', 'B|1', 'open'), "
                    "(:n, :p, 'hh', 'N|1', 'open')"
                ),
                {"a": CASE_A, "b": CASE_B, "n": CASE_NOBODY, "p": PROJECT_ID},
            )
            await session.execute(
                text(
                    "INSERT INTO assignment (id, case_id, team_id) "
                    "VALUES ('01ASGMA', :a, :ta), ('01ASGMB', :b, :tb)"
                ),
                {"a": CASE_A, "b": CASE_B, "ta": TEAM_A, "tb": TEAM_B},
            )
            await session.execute(
                text(
                    "INSERT INTO assignment (id, case_id, user_id) "
                    "VALUES ('01ASGMAU', :a, :ea), ('01ASGMBU', :b, :eb)"
                ),
                {"a": CASE_A, "b": CASE_B, "ea": ENUM_A, "eb": ENUM_B},
            )
            await session.execute(
                text(
                    "INSERT INTO submission (id, project_id, environment_id, form_version_id, "
                    "case_id, created_by, status) VALUES "
                    "(:sa, :p, '01ENVMON', '01VERMON', :ca, :ea, 'finalized'), "
                    "(:sb, :p, '01ENVMON', '01VERMON', :cb, :eb, 'finalized'), "
                    # On the case nobody holds, by the manager: in neither
                    # supervisor's scope by case and by creator. Without a row
                    # like this the two supervisors' figures add to the whole
                    # and a widened policy would pass unnoticed — which is what
                    # the assertion below found the first time it ran.
                    "(:sn, :p, '01ENVMON', '01VERMON', :cn, :pm, 'finalized')"
                ),
                {
                    "sa": SUB_A,
                    "sb": SUB_B,
                    "sn": SUB_NOBODY,
                    "p": PROJECT_ID,
                    "ca": CASE_A,
                    "cb": CASE_B,
                    "cn": CASE_NOBODY,
                    "ea": ENUM_A,
                    "eb": ENUM_B,
                    "pm": PM,
                },
            )
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def monitor_db() -> Any:
    from alembic import command
    from alembic.config import Config

    from tests.test_migrations import BACKEND_DIR

    async def prepare() -> str | None:
        try:
            async with admin_connection() as conn:
                await conn.execute(f"DROP DATABASE IF EXISTS {MON_DB} WITH (FORCE)")
                await conn.execute(f"CREATE DATABASE {MON_DB}")
        except Exception as exc:  # noqa: BLE001 - any failure means "not available"
            return f"{type(exc).__name__}: {exc}"
        return None

    reason = _run(prepare())
    if reason is not None:
        pytest.skip(f"postgres not available: {reason}")

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", admin_url(MON_DB))
    command.upgrade(cfg, "head")
    _run(_seed())

    yield MON_DB

    async def drop() -> None:
        async with admin_connection() as conn:
            await conn.execute(f"DROP DATABASE IF EXISTS {MON_DB} WITH (FORCE)")

    _run(drop())


async def _principal_of(engine: AsyncEngine, username: str) -> Principal:
    async with session_as(Principal(org_id=ORG_ID, org_slug=ORG_SLUG), engine=engine) as s:
        found = (
            (await s.execute(text("SELECT * FROM dcp_login_lookup(:u)"), {"u": username}))
            .mappings()
            .one()
        )
        person = auth.Person(
            found["id"], found["organization_id"], found["username"], found["display_name"]
        )
        principal, _ = await auth.principal_for(s, person, ORG_SLUG)
        return principal


async def _agree(engine: AsyncEngine, principal: Principal, table: str) -> tuple[int, list[str]]:
    """The count and the enumeration, asked the way a screen asks them.

    Same connection, same principal, same table: the two questions a dashboard
    and the list under it put to the database.
    """
    async with session_as(principal, engine=engine) as s:
        total = (await s.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
        rows = list((await s.execute(text(f"SELECT id FROM {table} ORDER BY id"))).scalars())
    return int(total), rows


TABLES = ("submission", "case_record", "device")

#: What each principal may see, exactly. Written out rather than derived, so a
#: policy change has to disagree with a number somebody chose.
EXPECTED = {
    "admin": {"submission": 3, "case_record": 3, "device": 3},
    "pm": {"submission": 3, "case_record": 3, "device": 2},
    "sup-a": {"submission": 1, "case_record": 1, "device": 1},
    "sup-b": {"submission": 1, "case_record": 1, "device": 1},
    "enum-a": {"submission": 1, "case_record": 1, "device": 1},
}


@pytest.mark.db
def test_every_count_agrees_with_the_list_it_summarises(monitor_db: str) -> None:
    async def go() -> None:
        engine = create_engine(database=monitor_db)
        try:
            for username, expected in EXPECTED.items():
                principal = await _principal_of(engine, username)
                for table in TABLES:
                    total, rows = await _agree(engine, principal, table)
                    assert total == len(rows), (
                        f"{username}: {table} counted {total} and listed {len(rows)} — "
                        "a dashboard and the list under it would disagree"
                    )
                    assert total == expected[table], (
                        f"{username}: {table} is {total}, expected {expected[table]}"
                    )

        finally:
            await engine.dispose()

    _run(go())


@pytest.mark.db
def test_a_supervisor_sees_strictly_less_than_the_organisation(monitor_db: str) -> None:
    """The assertion that makes the one above worth anything.

    "Aggregate equals enumeration" is satisfied by a policy that shows
    everything to everyone — both numbers become the project's total and they
    match. So a supervisor's figure has to be strictly smaller than the
    org-wide figure on every table, and the sum of the two supervisors' figures
    has to be smaller still than the project's, because a case and a device
    belong to neither of them.
    """

    async def go() -> None:
        engine = create_engine(database=monitor_db)
        try:
            admin = await _principal_of(engine, "admin")
            sup_a = await _principal_of(engine, "sup-a")
            sup_b = await _principal_of(engine, "sup-b")
            for table in TABLES:
                whole, _ = await _agree(engine, admin, table)
                a_total, a_rows = await _agree(engine, sup_a, table)
                b_total, b_rows = await _agree(engine, sup_b, table)
                assert a_total < whole, (
                    f"{table}: a supervisor sees {a_total} of {whole} — a policy that "
                    "shows everything would pass the agreement test and fail here"
                )
                assert b_total < whole
                assert set(a_rows).isdisjoint(b_rows), f"{table}: the two teams overlap"
                assert a_total + b_total < whole, (
                    f"{table}: the supervisors' figures add to {a_total + b_total} of "
                    f"{whole}, so nothing is held by neither of them and this fixture "
                    "cannot catch a widened policy"
                )
        finally:
            await engine.dispose()

    _run(go())


@pytest.mark.db
def test_a_device_nobody_has_signed_in_on_belongs_to_nobody(monitor_db: str) -> None:
    """The row the device panel is most likely to disagree about.

    An unbound device is visible org-wide and to no one else — right, because
    nobody owns it. The risk is a panel that lists it "helpfully" for everybody
    while counting it for nobody, or the reverse. Both halves come from the one
    policy, so both are asserted here against the same fixture.
    """

    async def go() -> None:
        engine = create_engine(database=monitor_db)
        try:
            admin = await _principal_of(engine, "admin")
            total, rows = await _agree(engine, admin, "device")
            assert DEV_UNBOUND in rows and total == 3

            for username in ("pm", "sup-a", "sup-b", "enum-a"):
                principal = await _principal_of(engine, username)
                total, rows = await _agree(engine, principal, "device")
                assert DEV_UNBOUND not in rows, (
                    f"{username} sees a device nobody has signed in on"
                )
                assert total == len(rows), (
                    f"{username}: the device count and the device list disagree about "
                    "the rows nobody owns"
                )
        finally:
            await engine.dispose()

    _run(go())


@pytest.mark.db
def test_a_supervisor_sees_their_own_enumerators_handsets_and_no_others(monitor_db: str) -> None:
    async def go() -> None:
        engine = create_engine(database=monitor_db)
        try:
            sup_a = await _principal_of(engine, "sup-a")
            sup_b = await _principal_of(engine, "sup-b")
            _, a_rows = await _agree(engine, sup_a, "device")
            _, b_rows = await _agree(engine, sup_b, "device")
            assert a_rows == [DEV_A]
            assert b_rows == [DEV_B]

            # And what hangs off a device narrows with it.
            async with session_as(sup_a, engine=engine) as s:
                await s.execute(
                    text("INSERT INTO sync_cursor (device_id, scope) VALUES (:d, 'ops')"),
                    {"d": DEV_A},
                )
                await s.commit()
                seen = list(
                    (await s.execute(text("SELECT device_id FROM sync_cursor"))).scalars()
                )
            assert seen == [DEV_A]
            async with session_as(sup_b, engine=engine) as s:
                seen_b = list(
                    (await s.execute(text("SELECT device_id FROM sync_cursor"))).scalars()
                )
            assert seen_b == [], "a cursor for another team's device is visible"
        finally:
            await engine.dispose()

    _run(go())


@pytest.mark.db
def test_a_new_handset_can_still_register_with_nobody_signed_in(monitor_db: str) -> None:
    """The failure a strict read policy invites, and the reason `WITH CHECK`
    is written separately from `USING` in 015.

    `POST /api/v1/devices` is public: it runs with the organisation resolved
    and no person at all, because nobody has signed in on the handset yet. A
    check that demanded the row belong to the principal would refuse every
    first registration.
    """

    async def go() -> None:
        engine = create_engine(database=monitor_db)
        try:
            nobody = Principal(org_id=ORG_ID, org_slug=ORG_SLUG)
            async with session_as(nobody, engine=engine) as s:
                await s.execute(
                    text(
                        "INSERT INTO device (id, project_id, platform) "
                        "VALUES ('dev-fresh', :p, 'android')"
                    ),
                    {"p": PROJECT_ID},
                )
                await s.commit()

            # It exists, and it belongs to nobody until a login binds it.
            admin = await _principal_of(engine, "admin")
            _, rows = await _agree(engine, admin, "device")
            assert "dev-fresh" in rows
            sup_a = await _principal_of(engine, "sup-a")
            _, a_rows = await _agree(engine, sup_a, "device")
            assert "dev-fresh" not in a_rows

            # A supervisor still cannot hand a device to somebody else by
            # writing the row: that is what the check is for.
            async with session_as(sup_a, engine=engine) as s:
                with pytest.raises(DBAPIError) as refused:
                    await s.execute(
                        text(
                            "INSERT INTO device (id, project_id, platform, user_id, bound_at) "
                            "VALUES ('dev-forged', :p, 'android', :u, now())"
                        ),
                        {"p": PROJECT_ID, "u": ENUM_B},
                    )
                    await s.commit()
            assert "row-level security" in str(refused.value.orig)
        finally:
            await engine.dispose()

    _run(go())


@pytest.mark.db
def test_the_reported_backlog_is_the_devices_word_and_carries_its_time(monitor_db: str) -> None:
    """`reported_pending_ops` is not this server's count and is not named as
    if it were (015).

    The column exists so a panel can say "12 waiting, as of 09:14". Nothing
    computes it here, and `last_counter` — which this server does compute —
    says only what was accepted.
    """

    async def go() -> None:
        engine = create_engine(database=monitor_db)
        try:
            admin = await _principal_of(engine, "admin")
            async with session_as(admin, engine=engine) as s:
                await s.execute(
                    text(
                        "UPDATE device SET reported_pending_ops = 12, reported_at = now() "
                        "WHERE id = :d"
                    ),
                    {"d": DEV_A},
                )
                await s.commit()
                row = (
                    (
                        await s.execute(
                            text(
                                "SELECT reported_pending_ops, reported_at, last_counter "
                                "FROM device WHERE id = :d"
                            ),
                            {"d": DEV_A},
                        )
                    )
                    .mappings()
                    .one()
                )
            assert row["reported_pending_ops"] == 12
            assert row["reported_at"] is not None, "a backlog with no date on it is a claim"
            assert row["last_counter"] == 0, (
                "last_counter is what this server accepted and must not be confused "
                "with what the device says is queued"
            )
        finally:
            await engine.dispose()

    _run(go())


@pytest.mark.db
def test_the_aggregate_and_the_list_are_asked_of_the_same_table(monitor_db: str) -> None:
    """The rule D1 states, at the level it is true.

    A `COUNT` and a `SELECT` over one table on one connection are filtered by
    one policy. This is the property every monitoring figure will rest on, and
    the reason no summary table, cache or admin connection is allowed to
    produce one.
    """

    async def go() -> None:
        from app.modules.submissions.models import Submission

        engine = create_engine(database=monitor_db)
        try:
            sup_a = await _principal_of(engine, "sup-a")
            async with session_as(sup_a, engine=engine) as s:
                orm_count = (
                    await s.execute(select(func.count()).select_from(Submission))
                ).scalar_one()
                orm_rows = list((await s.execute(select(Submission.id))).scalars())
                sql_count = (
                    await s.execute(text("SELECT count(*) FROM submission"))
                ).scalar_one()
            assert orm_count == len(orm_rows) == sql_count == 1

        finally:
            await engine.dispose()

    _run(go())
