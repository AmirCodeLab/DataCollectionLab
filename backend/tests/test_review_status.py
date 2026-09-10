"""The status machine, and the policies on the three review tables (item 6).

Two halves, and they defend different things.

**The machine** is defect 27. `submission.status` used to be written by a
condition at one call site — `if submission.status in ("draft", "finalized")` —
which stated which states *sync* may leave and thereby decided, silently, which
states *anything* may leave. A submission a reviewer sent back for correction
could never come back: the enumerator's ops were accepted, the fold ran, the
data updated, the status stayed put, and nothing errored at any step. The
round-trip test below is that defect, watched.

**The policies** are the ordinary rule, applied to three tables that have had
none since 001 because nothing wrote them. A rule is written by somebody who
manages the project; a decision by somebody holding `submission.review`; a
flag by whoever may see the submission, which is deliberately *not* gated on
`submission.review`, because flags are raised by the push that carries the
work and an enumerator holds no permission at all.

The principals here are built literally rather than through
`dcp_principal_for`. What is under test is the policy, and a fixture that also
had to seed the identity graph would be testing item 1 again — but note the
consequence, which is the rule from `docs/project-conventions.md`: a principal
this file builds is only as narrow as it says it is, so every assertion names
the fields it is relying on.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.infrastructure.database import (
    Principal,
    admin_connection,
    admin_url,
    create_engine,
    session_as,
)
from app.modules.submissions import status as machine

REVIEW_DB = "dcp_test_review"
ORG_ID, ORG_SLUG = "01ORGREV", "review"
PROJECT_ID = "01PRJREV"
SUB_ID = "01SUBREV"
DEVICE_ID = "dev-rev"
SUPERVISOR, ENUMERATOR = "01USRREVS", "01USRREVE"


# ---------------------------------------------------------------------------
# The machine, with no database in sight
# ---------------------------------------------------------------------------


def test_the_table_covers_every_status_the_constraint_admits() -> None:
    """A status the database allows and the machine has never heard of would
    refuse every transition out of it — which is defect 27 with a different
    spelling."""
    assert set(machine.STATUSES) == set(machine._TABLE), (
        "submission_status_check and the transition table disagree"
    )


def test_a_submission_sent_back_and_redone_returns_to_finalized() -> None:
    """Defect 27, at the unit."""
    assert machine.next_status("correction_required", "finalize") == "finalized"


def test_reopening_something_already_sent_back_does_not_erase_that_it_was() -> None:
    """A correction request reopens the submission, so the log's net status is
    `draft` for as long as the enumerator is working. Writing that through
    would lose the one fact that separates "sent back, being redone" from
    "never finished"."""
    assert machine.next_status("correction_required", "reopen") == "correction_required"


def test_the_closed_states_accept_nothing_and_say_why() -> None:
    assert machine.CLOSED == frozenset({"approved", "rejected"})
    for event in machine.EVENTS:
        for closed in machine.CLOSED:
            with pytest.raises(machine.Refused) as refused:
                machine.next_status(closed, event)
            assert refused.value.message, "a refusal with no sentence is a 500 waiting to happen"


def test_a_reviewer_cannot_judge_a_draft() -> None:
    """Nothing has been submitted yet. The refusal names the state and the ask."""
    with pytest.raises(machine.Refused) as refused:
        machine.next_status("draft", "approve")
    assert "draft" in refused.value.message and "approved" in refused.value.message


def test_the_fold_is_read_as_an_event_and_never_as_a_status() -> None:
    assert machine.event_for_folded(None) is None
    assert machine.event_for_folded("finalized") == "finalize"
    assert machine.event_for_folded("draft") == "reopen"


def test_the_sync_service_takes_its_closed_set_from_the_machine() -> None:
    """Two copies of "which states accept no ops" is how they drift."""
    from app.modules.sync import service as sync_service

    assert sync_service._CLOSED_STATUSES is machine.CLOSED


# ---------------------------------------------------------------------------
# The database
# ---------------------------------------------------------------------------


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


async def _seed_organization() -> None:
    """The organisation and its builtin roles, as 008 would have made them —
    including the Supervisor's permissions exactly as 008 and 010 left them,
    which is the state 016 is expected to widen."""
    async with admin_connection(REVIEW_DB) as conn:
        await conn.execute(
            "INSERT INTO platform_organization (id, name, slug) VALUES ($1, 'Review Org', $2)",
            ORG_ID,
            ORG_SLUG,
        )
        await conn.execute(
            "INSERT INTO role (id, organization_id, name, scope_kind, builtin) "
            "SELECT $1 || '_' || r.suffix, $1, r.name, r.scope_kind, true "
            "FROM (VALUES ('admin', 'Admin', 'organization'),"
            "             ('pm', 'Programme manager', 'project'),"
            "             ('supervisor', 'Supervisor', 'team'),"
            "             ('enumerator', 'Enumerator', 'team'))"
            "     AS r(suffix, name, scope_kind)",
            ORG_ID,
        )
        await conn.execute(
            "INSERT INTO role_permission (role_id, permission) "
            "SELECT r.id, p.name FROM role r, "
            "(VALUES ('submission.view'), ('submission.review'), ('sample.assign'),"
            "        ('project.manage')) AS p(name) "
            "WHERE r.organization_id = $1 AND r.builtin AND ("
            "  r.name = 'Admin'"
            "  OR (r.name = 'Programme manager')"
            "  OR (r.name = 'Supervisor' AND p.name IN ('sample.assign', 'submission.view')))",
            ORG_ID,
        )


async def _seed() -> None:
    """The smallest world the policies need: one org, one project, one form,
    one device, a supervisor and an enumerator, and one finalised submission
    with a log behind it."""
    async with admin_connection(REVIEW_DB) as conn:
        await conn.execute(
            "INSERT INTO platform_user (id, organization_id, display_name, username) "
            "VALUES ($1, $3, 'Sup', 'sup'), ($2, $3, 'Enum', 'enum')",
            SUPERVISOR,
            ENUMERATOR,
            ORG_ID,
        )
        await conn.execute(
            "INSERT INTO project (id, organization_id, name, slug) VALUES ($1, $2, 'P', 'rev')",
            PROJECT_ID,
            ORG_ID,
        )
        await conn.execute(
            "INSERT INTO environment (id, project_id, kind) "
            "VALUES ('01ENVREV', $1, 'production')",
            PROJECT_ID,
        )
        await conn.execute(
            "INSERT INTO form (id, project_id, form_key, title) "
            "VALUES ('01FRMREV', $1, 'hh', 'HH')",
            PROJECT_ID,
        )
        await conn.execute(
            "INSERT INTO form_version (id, form_id, version, ir, ir_checksum) "
            "VALUES ('01VERREV', '01FRMREV', 1, '{}'::jsonb, 'x')"
        )
        await conn.execute(
            "INSERT INTO device (id, project_id, user_id, bound_at, platform) "
            "VALUES ($1, $2, $3, now(), 'android')",
            DEVICE_ID,
            PROJECT_ID,
            ENUMERATOR,
        )
        await conn.execute(
            "INSERT INTO submission (id, project_id, environment_id, form_version_id,"
            " origin_device_id, created_by, status) "
            "VALUES ($1, $2, '01ENVREV', '01VERREV', $3, $4, 'finalized')",
            SUB_ID,
            PROJECT_ID,
            DEVICE_ID,
            ENUMERATOR,
        )
        await conn.execute(
            "INSERT INTO submission_op (id, submission_id, op_kind, path, value, device_id,"
            " actor_id, counter, wall_clock) VALUES "
            "('01OPREV1', $1, 'set', 'name', '\"A\"'::jsonb, $2, $3, 1, now()),"
            "('01OPREV2', $1, 'finalize', NULL, NULL, $2, $3, 2, now())",
            SUB_ID,
            DEVICE_ID,
            ENUMERATOR,
        )
        await conn.execute(
            "INSERT INTO quality_rule (id, project_id, name, definition) "
            "VALUES ('01QRREV', $1, 'age in range', '{}'::jsonb)",
            PROJECT_ID,
        )


@pytest.fixture(scope="module")
def review_db() -> Any:
    from alembic import command
    from alembic.config import Config

    from tests.test_migrations import BACKEND_DIR

    async def prepare() -> str | None:
        try:
            async with admin_connection() as conn:
                await conn.execute(f"DROP DATABASE IF EXISTS {REVIEW_DB} WITH (FORCE)")
                await conn.execute(f"CREATE DATABASE {REVIEW_DB}")
        except Exception as exc:  # noqa: BLE001 - any failure means "not available"
            return f"{type(exc).__name__}: {exc}"
        return None

    reason = _run(prepare())
    if reason is not None:
        pytest.skip(f"postgres not available: {reason}")

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", admin_url(REVIEW_DB))

    # 008 seeds the builtin roles over the organisations that exist when it
    # runs, and 016's grant does the same. So the organisation has to be here
    # BEFORE 0016 — otherwise the grant has nothing to grant to and the test
    # would pass on an empty set. Stop at 0015, make the world, then finish.
    command.upgrade(cfg, "0015")
    _run(_seed_organization())
    command.upgrade(cfg, "head")
    _run(_seed())
    yield REVIEW_DB

    async def drop() -> None:
        async with admin_connection() as conn:
            await conn.execute(f"DROP DATABASE IF EXISTS {REVIEW_DB} WITH (FORCE)")

    _run(drop())


def _reviewer() -> Principal:
    return Principal(
        org_id=ORG_ID,
        org_slug=ORG_SLUG,
        user_id=SUPERVISOR,
        scope_kind="team",
        visible_user_ids=(SUPERVISOR, ENUMERATOR),
        permissions=("submission.view", "submission.review"),
    )


def _enumerator() -> Principal:
    return Principal(
        org_id=ORG_ID,
        org_slug=ORG_SLUG,
        user_id=ENUMERATOR,
        scope_kind="team",
        visible_user_ids=(ENUMERATOR,),
        permissions=(),
    )


async def _status(engine: AsyncEngine) -> str:
    async with session_as(Principal.organization(ORG_ID, slug=ORG_SLUG), engine=engine) as s:
        return str(
            (
                await s.execute(
                    text("SELECT status FROM submission WHERE id = :s"), {"s": SUB_ID}
                )
            ).scalar_one()
        )


async def _set_status(engine: AsyncEngine, value: str) -> None:
    """The reviewer's half, before the route that will do it exists."""
    async with admin_connection(REVIEW_DB) as conn:
        await conn.execute("UPDATE submission SET status = $1 WHERE id = $2", value, SUB_ID)


async def _refold(engine: AsyncEngine, sync_service: Any) -> None:
    """What push does after admitting a batch, on this submission alone."""
    from app.modules.submissions.models import Submission

    async with session_as(_enumerator(), engine=engine) as s, s.begin():
        submission = await s.get(Submission, SUB_ID)
        assert submission is not None
        await sync_service._fold_submission(s, submission)


@pytest.mark.db
def test_a_correction_pushed_back_returns_the_submission_to_the_queue(review_db: str) -> None:
    """**Defect 27, end to end.** The submission is sent back, the enumerator
    appends a correction and finalises again, and the status returns to
    `finalized` — so it re-enters the review queue and re-covers its case on
    item 5's dashboard.

    Watched to fail before the status machine existed: the old guard wrote a
    status only while the current one was `draft` or `finalized`, so this
    submission stayed `correction_required` with the corrected answers sitting
    in `submission_state` behind it.
    """

    async def go() -> None:
        from app.modules.sync import service as sync_service

        engine = create_engine(database=review_db)
        try:
            await _set_status(engine, "correction_required")

            # The reviewer's correction request reopens the work, then the
            # enumerator corrects and finalises again.
            async with session_as(_enumerator(), engine=engine) as s, s.begin():
                await s.execute(
                    text(
                        "INSERT INTO submission_op (id, submission_id, op_kind, path, value,"
                        " device_id, actor_id, counter, wall_clock) VALUES "
                        "('01OPREV3', :s, 'reopen', NULL, NULL, :d, :e, 3, now()),"
                        "('01OPREV4', :s, 'set', 'name', '\"B\"'::jsonb, :d, :e, 4, now()),"
                        "('01OPREV5', :s, 'finalize', NULL, NULL, :d, :e, 5, now())"
                    ),
                    {"s": SUB_ID, "d": DEVICE_ID, "e": ENUMERATOR},
                )

            await _refold(engine, sync_service)

            assert await _status(engine) == "finalized", (
                "a submission sent back, corrected and finalised again never returned "
                "to the queue — defect 27"
            )
        finally:
            await engine.dispose()

    _run(go())


@pytest.mark.db
def test_work_in_progress_on_a_correction_does_not_look_finished(review_db: str) -> None:
    """While the enumerator is redoing it the log's net status is `draft`, and
    writing that through would lose the fact that it was sent back."""

    async def go() -> None:
        from app.modules.sync import service as sync_service

        engine = create_engine(database=review_db)
        try:
            await _set_status(engine, "correction_required")
            async with session_as(_enumerator(), engine=engine) as s, s.begin():
                await s.execute(
                    text(
                        "INSERT INTO submission_op (id, submission_id, op_kind, path, value,"
                        " device_id, actor_id, counter, wall_clock) VALUES "
                        "('01OPREV6', :s, 'reopen', NULL, NULL, :d, :e, 6, now())"
                    ),
                    {"s": SUB_ID, "d": DEVICE_ID, "e": ENUMERATOR},
                )
            await _refold(engine, sync_service)
            assert await _status(engine) == "correction_required"
        finally:
            await engine.dispose()

    _run(go())


@pytest.mark.db
def test_only_a_reviewer_may_record_a_decision(review_db: str) -> None:
    """The console will check `submission.review` before showing the control.
    A check in a screen is not a guarantee — defect 26, one surface up."""

    async def go() -> None:
        engine = create_engine(database=review_db)
        try:
            async with session_as(_enumerator(), engine=engine) as s:
                with pytest.raises(DBAPIError) as refused:
                    await s.execute(
                        text(
                            "INSERT INTO review (id, submission_id, reviewer_id, decision) "
                            "VALUES ('01RVREV0', :s, :u, 'approved')"
                        ),
                        {"s": SUB_ID, "u": ENUMERATOR},
                    )
                    await s.commit()
            assert "row-level security" in str(refused.value.orig)

            async with session_as(_reviewer(), engine=engine) as s, s.begin():
                await s.execute(
                    text(
                        "INSERT INTO review (id, submission_id, reviewer_id, decision, comment) "
                        "VALUES ('01RVREV1', :s, :u, 'correction_required', 'age looks wrong')"
                    ),
                    {"s": SUB_ID, "u": SUPERVISOR},
                )
        finally:
            await engine.dispose()

    _run(go())


@pytest.mark.db
def test_a_decision_cannot_be_edited_or_deleted_afterwards(review_db: str) -> None:
    """A trail that can be rewritten is not a trail, and "who decided what,
    when" is the only reason these rows exist."""

    async def go() -> None:
        engine = create_engine(database=review_db)
        try:
            async with session_as(_reviewer(), engine=engine) as s, s.begin():
                await s.execute(
                    text(
                        "INSERT INTO review (id, submission_id, reviewer_id, decision) "
                        "VALUES ('01RVREV2', :s, :u, 'approved')"
                    ),
                    {"s": SUB_ID, "u": SUPERVISOR},
                )
            for statement in (
                "UPDATE review SET comment = 'actually fine' WHERE id = '01RVREV2'",
                "DELETE FROM review WHERE id = '01RVREV2'",
            ):
                async with session_as(_reviewer(), engine=engine) as s, s.begin():
                    await s.execute(text(statement))
                async with session_as(_reviewer(), engine=engine) as s:
                    still = (
                        await s.execute(
                            text("SELECT count(*) FROM review WHERE id = '01RVREV2'")
                        )
                    ).scalar_one()
                assert still == 1, f"a restrictive policy did not stop: {statement}"
        finally:
            await engine.dispose()

    _run(go())


@pytest.mark.db
def test_an_enumerator_may_record_what_the_rules_said_about_their_own_work(
    review_db: str,
) -> None:
    """Flags are raised by the push that carries the work, under the
    enumerator's own principal, and an enumerator holds no permission at all.
    Gating `quality_flag` on `submission.review` would mean no flag is ever
    raised — the failure would be an empty queue, which reads as good news."""

    async def go() -> None:
        engine = create_engine(database=review_db)
        try:
            async with session_as(_enumerator(), engine=engine) as s, s.begin():
                await s.execute(
                    text(
                        "INSERT INTO quality_flag "
                        "(id, submission_id, rule_id, severity, outcome, rule_name,"
                        " rule_definition) VALUES "
                        "('01QFREV1', :s, '01QRREV', 'warning', 'violation', 'age in range',"
                        " '{}'::jsonb)"
                    ),
                    {"s": SUB_ID},
                )
            async with session_as(_reviewer(), engine=engine) as s:
                seen = (
                    await s.execute(
                        text("SELECT count(*) FROM quality_flag WHERE submission_id = :s"),
                        {"s": SUB_ID},
                    )
                ).scalar_one()
            assert seen == 1, "a supervisor could not see a flag on work they may review"
        finally:
            await engine.dispose()

    _run(go())


@pytest.mark.db
def test_a_rule_that_could_not_run_is_not_counted_as_an_outstanding_flag(
    review_db: str,
) -> None:
    """Item 5's count reads the open-flag index. A rule the server could not
    evaluate — an encrypted answer it holds no key for — is recorded, and is
    not a violation. Counting it as one would put a number on a check that
    never happened, which is the same lie in the other direction."""

    async def go() -> None:
        engine = create_engine(database=review_db)
        try:
            async with session_as(_enumerator(), engine=engine) as s, s.begin():
                await s.execute(
                    text(
                        "INSERT INTO quality_flag "
                        "(id, submission_id, rule_id, severity, outcome, rule_name,"
                        " rule_definition) VALUES "
                        "('01QFREV2', :s, '01QRREV', 'warning', 'not_evaluated',"
                        " 'age in range', '{}'::jsonb)"
                    ),
                    {"s": SUB_ID},
                )
            async with session_as(_reviewer(), engine=engine) as s:
                counts = (
                    (
                        await s.execute(
                            text(
                                "SELECT count(*) FILTER (WHERE outcome = 'violation') AS open,"
                                " count(*) FILTER (WHERE outcome = 'not_evaluated') AS unknown "
                                "FROM quality_flag "
                                "WHERE submission_id = :s AND resolved_at IS NULL"
                            ),
                            {"s": SUB_ID},
                        )
                    )
                    .mappings()
                    .one()
                )
            assert counts["unknown"] == 1
            assert counts["open"] == 1, "the violation from the previous test, and not the other"
        finally:
            await engine.dispose()

    _run(go())


@pytest.mark.db
def test_the_supervisor_role_now_holds_submission_review(review_db: str) -> None:
    """A9. The pilot's reviewers are supervisors: the supervisor gets the list
    and reviews as they go, which is where they already are during fieldwork.
    Admin and Programme manager keep it."""

    async def go() -> None:
        async with admin_connection(review_db) as conn:
            holders = await conn.fetch(
                "SELECT r.name FROM role r JOIN role_permission p ON p.role_id = r.id "
                "WHERE r.builtin AND p.permission = 'submission.review' ORDER BY r.name"
            )
        assert {row["name"] for row in holders} == {
            "Admin",
            "Programme manager",
            "Supervisor",
        }

    _run(go())
