"""Sync API tests (specs/sync-protocol-v0.1.md).

The db-marked tests run the real endpoints against a scratch database migrated
to head: push idempotency, per-op rejection, cross-device convergence, cursor
pulls and tombstone delivery. They skip when Postgres is unreachable
(docker compose up -d postgres) and are deselectable with -m "not db".
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pytest
from pydantic import ValidationError

from app.modules.sync.schemas import PushRequest, SyncOp

SYNC_DB = "dcp_test_sync"

FORM_KEY = "household_survey"
FORM_VERSION = 3


# ---------------------------------------------------------------------------
# Wire-level validation — no database needed
# ---------------------------------------------------------------------------


def _op(
    op_id: str,
    submission_id: str,
    device_id: str,
    counter: int,
    kind: str = "set",
    path: str | None = "name",
    value: Any = None,
    form_version: int = FORM_VERSION,
    wall_clock: str = "2026-08-28T09:14:22Z",
) -> dict[str, Any]:
    return {
        "opId": op_id,
        "submissionId": submission_id,
        "formId": FORM_KEY,
        "formVersion": form_version,
        "kind": kind,
        "path": path,
        "value": value,
        "deviceId": device_id,
        "counter": counter,
        "wallClock": wall_clock,
    }


def test_op_validation_rejects_malformed_shapes() -> None:
    SyncOp.model_validate(_op("01OP", "01SUB", "dev-a", 1, value="x"))  # valid

    with pytest.raises(ValidationError):
        SyncOp.model_validate(_op("01OP", "01SUB", "dev-a", 1, kind="explode"))
    with pytest.raises(ValidationError):
        SyncOp.model_validate(_op("01OP", "01SUB", "dev-a", 1, path=None))  # set needs a path
    with pytest.raises(ValidationError):
        SyncOp.model_validate(_op("01OP", "01SUB", "dev-a", -1))  # negative counter
    with pytest.raises(ValidationError):
        SyncOp.model_validate({"opId": "01OP"})  # missing almost everything


def test_push_batches_are_bounded() -> None:
    ops = [_op(f"OP{i}", "01SUB", "dev-a", i) for i in range(501)]
    with pytest.raises(ValidationError):
        PushRequest.model_validate({"deviceId": "dev-a", "ops": ops})


# ---------------------------------------------------------------------------
# Live tests against the real endpoints
# ---------------------------------------------------------------------------


def _admin_dsn() -> str:
    from app.core.config import get_settings

    return get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")


def _sync_db_url() -> str:
    parts = urlsplit(_admin_dsn())
    return urlunsplit(parts._replace(scheme="postgresql+asyncpg", path=f"/{SYNC_DB}"))


async def _seed() -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.modules.forms.models import Form, FormVersion
    from app.modules.projects.models import Device, Environment, Project

    engine = create_async_engine(_sync_db_url())
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            # The models carry no relationship()s, so flush between dependency
            # levels to control insert order.
            session.add(Project(id="01PROJECT", name="Household Study", slug="household-study"))
            await session.flush()
            session.add(
                Environment(id="01ENVPROD", project_id="01PROJECT", kind="production")
            )
            session.add(
                Form(id="01FORM", project_id="01PROJECT", form_key=FORM_KEY, title="Household")
            )
            for device_id in ("dev-a", "dev-b"):
                session.add(
                    Device(
                        id=device_id,
                        project_id="01PROJECT",
                        user_id="usr-1",
                        platform="android",
                    )
                )
            await session.flush()
            session.add(
                FormVersion(
                    id="01FORMV3",
                    form_id="01FORM",
                    version=FORM_VERSION,
                    ir={},
                    ir_checksum="test",
                )
            )
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def sync_api() -> Any:
    import asyncpg
    from alembic import command
    from alembic.config import Config

    from tests.test_migrations import BACKEND_DIR

    async def prepare() -> str | None:
        try:
            conn = await asyncpg.connect(_admin_dsn(), timeout=3)
        except Exception as exc:  # noqa: BLE001 - any failure means "not available"
            return f"{type(exc).__name__}: {exc}"
        try:
            await conn.execute(f"DROP DATABASE IF EXISTS {SYNC_DB} WITH (FORCE)")
            await conn.execute(f"CREATE DATABASE {SYNC_DB}")
        finally:
            await conn.close()
        return None

    reason = asyncio.run(prepare())
    if reason is not None:
        pytest.skip(
            f"Postgres unavailable ({reason}) — start it with: docker compose up -d postgres"
        )

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", _sync_db_url())
    command.upgrade(cfg, "head")

    asyncio.run(_seed())

    from app.api.deps import get_db
    from app.main import app

    async def scratch_db() -> AsyncIterator[Any]:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        # One engine per request: each test runs in its own event loop, and
        # pooled asyncpg connections cannot cross loops.
        engine = create_async_engine(_sync_db_url())
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                yield session
        finally:
            await engine.dispose()

    app.dependency_overrides[get_db] = scratch_db
    yield app
    app.dependency_overrides.pop(get_db, None)

    async def drop() -> None:
        conn = await asyncpg.connect(_admin_dsn())
        try:
            await conn.execute(f"DROP DATABASE IF EXISTS {SYNC_DB} WITH (FORCE)")
        finally:
            await conn.close()

    asyncio.run(drop())


def _run_with_client(app: Any, scenario: Callable[[Any], Awaitable[None]]) -> None:
    import httpx

    async def main() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await scenario(client)

    asyncio.run(main())


async def _push(client: Any, device_id: str, ops: list[dict[str, Any]]) -> dict[str, Any]:
    response = await client.post("/api/v1/sync/push", json={"deviceId": device_id, "ops": ops})
    assert response.status_code == 200, response.text
    return response.json()


async def _pull(client: Any, cursor: int = 0, limit: int = 200) -> dict[str, Any]:
    response = await client.get("/api/v1/sync/pull", params={"cursor": cursor, "limit": limit})
    assert response.status_code == 200, response.text
    return response.json()


async def _db_snapshot(query: str) -> Any:
    import asyncpg

    parts = urlsplit(_admin_dsn())
    conn = await asyncpg.connect(urlunsplit(parts._replace(path=f"/{SYNC_DB}")))
    try:
        return await conn.fetch(query)
    finally:
        await conn.close()


async def _state(submission_id: str) -> dict[str, Any]:
    import json

    rows = await _db_snapshot(
        f"SELECT data FROM submission_state WHERE submission_id = '{submission_id}'"
    )
    assert rows, f"no folded state for {submission_id}"
    return json.loads(rows[0]["data"])


@pytest.mark.db
def test_pushing_the_same_batch_twice_changes_nothing(sync_api: Any) -> None:
    async def scenario(client: Any) -> None:
        sub = "01SUBIDEMPOTENT"
        ops = [
            _op("01OPIDEM1", sub, "dev-a", 100, value="Amina"),
            _op("01OPIDEM2", sub, "dev-a", 101, path="age", value=34),
            _op("01OPIDEM3", sub, "dev-a", 102, kind="finalize", path=None),
        ]
        first = await _push(client, "dev-a", ops)
        assert sorted(first["accepted"]) == sorted(o["opId"] for o in ops)
        assert first["rejected"] == []

        counts = await _db_snapshot(
            "SELECT (SELECT count(*) FROM submission_op) AS ops,"
            " (SELECT count(*) FROM outbox_event) AS outbox"
        )
        state = await _state(sub)
        assert state == {"name": "Amina", "age": 34}

        second = await _push(client, "dev-a", ops)
        assert sorted(second["accepted"]) == sorted(first["accepted"])
        assert second["rejected"] == []
        assert second["serverCursor"] == first["serverCursor"]

        counts_after = await _db_snapshot(
            "SELECT (SELECT count(*) FROM submission_op) AS ops,"
            " (SELECT count(*) FROM outbox_event) AS outbox"
        )
        assert counts_after == counts
        assert await _state(sub) == state

    _run_with_client(sync_api, scenario)


@pytest.mark.db
def test_malformed_op_does_not_block_the_rest_of_the_batch(sync_api: Any) -> None:
    async def scenario(client: Any) -> None:
        sub = "01SUBMIXEDBATCH"
        good_1 = _op("01OPGOOD1", sub, "dev-a", 200, value="ok-1")
        bad_kind = _op("01OPBADKIND", sub, "dev-a", 201, kind="explode")
        missing_id = {"submissionId": sub, "kind": "set"}
        wrong_version = _op("01OPBADFORM", sub, "dev-a", 202, form_version=99)
        good_2 = _op("01OPGOOD2", sub, "dev-a", 203, path="age", value=7)

        result = await _push(client, "dev-a", [good_1, bad_kind, missing_id, wrong_version, good_2])

        assert sorted(result["accepted"]) == ["01OPGOOD1", "01OPGOOD2"]
        rejected = {r["opId"]: r["reason"] for r in result["rejected"]}
        assert rejected == {
            "01OPBADKIND": "malformed",
            None: "malformed",
            "01OPBADFORM": "unknown_form_version",
        }
        assert await _state(sub) == {"name": "ok-1", "age": 7}

    _run_with_client(sync_api, scenario)


@pytest.mark.db
def test_two_devices_converge_regardless_of_arrival_order(sync_api: Any) -> None:
    """Field-level LWW by (counter, deviceId): same ops, opposite arrival
    order, identical folded state (spec §6). Never wall clock (spec §3).

    The wallClocks are arranged so that ordering by wall clock picks the
    WRONG winner in both cases — the real-world case of a device with a
    wrong clock. A fold that orders by wallClock cannot pass this test:

      name: dev-a counter+5 @ 10:00  vs  dev-b counter+3 @ 11:00
            (counter, deviceId) -> dev-a wins; wall clock -> dev-b.
      age:  dev-a counter+7 @ 12:00  vs  dev-b counter+7 @ 09:00
            counters tie, deviceId decides -> dev-b wins; wall clock -> dev-a.
    """

    async def scenario(client: Any) -> None:
        def edits(sub: str, tag: str, counter_base: int) -> tuple[dict[str, Any], ...]:
            return (
                _op(f"01A{tag}NAME", sub, "dev-a", counter_base + 5,
                    value="from-a", wall_clock="2026-08-28T10:00:00Z"),
                _op(f"01B{tag}NAME", sub, "dev-b", counter_base + 3,
                    value="from-b", wall_clock="2026-08-28T11:00:00Z"),
                _op(f"01A{tag}AGE", sub, "dev-a", counter_base + 7,
                    path="age", value=30, wall_clock="2026-08-28T12:00:00Z"),
                _op(f"01B{tag}AGE", sub, "dev-b", counter_base + 7,
                    path="age", value=25, wall_clock="2026-08-28T09:00:00Z"),
            )

        a_name, b_name, a_age, b_age = edits("01SUBORDERAB", "AB", 300)
        await _push(client, "dev-a", [a_name, a_age])
        await _push(client, "dev-b", [b_name, b_age])

        a_name, b_name, a_age, b_age = edits("01SUBORDERBA", "BA", 310)
        await _push(client, "dev-b", [b_name, b_age])
        await _push(client, "dev-a", [a_name, a_age])

        state_ab = await _state("01SUBORDERAB")
        state_ba = await _state("01SUBORDERBA")
        assert state_ab == state_ba
        # name: higher counter wins even though the loser's clock is later
        assert state_ab["name"] == "from-a"
        # age: counters tie, deviceId is the tiebreak (dev-b > dev-a);
        # dev-b wins despite carrying the EARLIEST wall clock of all four ops
        assert state_ab["age"] == 25

    _run_with_client(sync_api, scenario)


@pytest.mark.db
def test_pull_with_cursor_returns_only_newer_ops(sync_api: Any) -> None:
    async def scenario(client: Any) -> None:
        batch_1 = [
            _op("01OPCUR1", "01SUBCURSOR", "dev-a", 400, value="v1"),
            _op("01OPCUR2", "01SUBCURSOR", "dev-a", 401, path="age", value=1),
        ]
        await _push(client, "dev-a", batch_1)
        first = await _pull(client, cursor=0)
        first_ids = {op["opId"] for op in first["ops"]}
        assert {"01OPCUR1", "01OPCUR2"} <= first_ids
        assert first["hasMore"] is False

        batch_2 = [
            _op("01OPCUR3", "01SUBCURSOR", "dev-a", 402, value="v2"),
            _op("01OPCUR4", "01SUBCURSOR", "dev-a", 403, path="age", value=2),
        ]
        await _push(client, "dev-a", batch_2)

        second = await _pull(client, cursor=first["nextCursor"])
        second_ids = [op["opId"] for op in second["ops"]]
        assert second_ids == ["01OPCUR3", "01OPCUR4"]
        assert second["nextCursor"] > first["nextCursor"]

        # Pulled ops are complete per spec §2: a fresh device can fold them.
        pulled = second["ops"][0]
        assert pulled["formId"] == FORM_KEY
        assert pulled["formVersion"] == FORM_VERSION
        assert pulled["counter"] == 402

    _run_with_client(sync_api, scenario)


@pytest.mark.db
def test_tombstone_reaches_a_device_that_was_offline_during_the_delete(sync_api: Any) -> None:
    async def scenario(client: Any) -> None:
        sub = "01SUBTOMBSTONE"
        await _push(
            client,
            "dev-a",
            [
                _op("01OPTOMB1", sub, "dev-a", 500, kind="repeat_add", path="members[i1]"),
                _op("01OPTOMB2", sub, "dev-a", 501, path="members[i1].age", value=12),
            ],
        )
        # dev-a's last successful pull, before going offline.
        offline_cursor = (await _pull(client, cursor=0))["nextCursor"]

        # While dev-a is offline, dev-b deletes the repeat instance.
        await _push(
            client,
            "dev-b",
            [_op("01OPTOMB3", sub, "dev-b", 502, kind="repeat_delete", path="members[i1]")],
        )
        assert await _state(sub) == {}

        # Back online, dev-a resumes from its cursor and learns of the delete.
        resumed = await _pull(client, cursor=offline_cursor)
        assert [op["opId"] for op in resumed["ops"]] == ["01OPTOMB3"]
        tombstones = resumed["tombstones"]
        assert len(tombstones) == 1
        assert tombstones[0]["subjectType"] == "repeat_instance"
        assert tombstones[0]["path"] == "members[i1]"
        assert tombstones[0]["submissionId"] == sub
        assert tombstones[0]["serverSeq"] > offline_cursor

    _run_with_client(sync_api, scenario)


@pytest.mark.db
def test_a_brand_new_device_registers_and_pushes_in_one_flow(sync_api: Any) -> None:
    async def scenario(client: Any) -> None:
        # An unregistered device gets every op rejected — the exact failure
        # registration exists to prevent.
        unregistered = await _push(
            client, "dev-unseen", [_op("01OPUNSEEN1", "01SUBUNSEEN", "dev-unseen", 1, value="x")]
        )
        assert unregistered["accepted"] == []
        assert unregistered["rejected"] == [
            {"opId": "01OPUNSEEN1", "reason": "not_authorized"}
        ]

        payload = {
            "deviceId": "dev-unseen",
            "platform": "android",
            "osVersion": "Android 14 (API 34)",
            "appVersion": "0.1.0",
        }
        first = await client.post("/api/v1/devices", json=payload)
        assert first.status_code == 200, first.text
        assert first.json()["status"] == "registered"
        assert first.json()["deviceId"] == "dev-unseen"
        assert first.json()["projectId"] == "01PROJECT"

        # Re-registering (reinstall, lost local flag) is success, not an error.
        again = await client.post("/api/v1/devices", json=payload)
        assert again.status_code == 200, again.text
        assert again.json()["status"] == "already_registered"

        # The same op that was rejected now goes through and is stored.
        pushed = await _push(
            client, "dev-unseen", [_op("01OPUNSEEN1", "01SUBUNSEEN", "dev-unseen", 1, value="x")]
        )
        assert pushed["accepted"] == ["01OPUNSEEN1"]
        assert pushed["rejected"] == []
        assert await _state("01SUBUNSEEN") == {"name": "x"}

    _run_with_client(sync_api, scenario)
