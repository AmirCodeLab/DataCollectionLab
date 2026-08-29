"""Submission read API tests — the endpoints the console reads.

Same shape as test_sync.py: a scratch database migrated to head, real
endpoints, data created the only way it ever is in production — by pushing
ops through /sync/push. Skips when Postgres is unreachable
(docker compose up -d postgres) and is deselectable with -m "not db".
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pytest

SUBMISSIONS_DB = "dcp_test_submissions"

FORM_KEY = "household_survey"
FORM_VERSION = 3
OTHER_FORM_KEY = "clinic_visit"
OTHER_FORM_VERSION = 1


def _op(
    op_id: str,
    submission_id: str,
    device_id: str,
    counter: int,
    kind: str = "set",
    path: str | None = "name",
    value: Any = None,
    form_id: str = FORM_KEY,
    form_version: int = FORM_VERSION,
    wall_clock: str = "2026-08-28T09:14:22Z",
) -> dict[str, Any]:
    return {
        "opId": op_id,
        "submissionId": submission_id,
        "formId": form_id,
        "formVersion": form_version,
        "kind": kind,
        "path": path,
        "value": value,
        "deviceId": device_id,
        "counter": counter,
        "wallClock": wall_clock,
    }


def _admin_dsn() -> str:
    from app.core.config import get_settings

    return get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")


def _db_url() -> str:
    parts = urlsplit(_admin_dsn())
    return urlunsplit(parts._replace(scheme="postgresql+asyncpg", path=f"/{SUBMISSIONS_DB}"))


async def _seed() -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.modules.forms.models import Form, FormVersion
    from app.modules.projects.models import Device, Environment, Project

    engine = create_async_engine(_db_url())
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            # No relationship()s on the models, so flush between levels.
            session.add(Project(id="01PROJECT", name="Household Study", slug="household-study"))
            await session.flush()
            session.add(Environment(id="01ENVPROD", project_id="01PROJECT", kind="production"))
            session.add(
                Form(id="01FORM", project_id="01PROJECT", form_key=FORM_KEY, title="Household")
            )
            session.add(
                Form(
                    id="01FORMCLINIC",
                    project_id="01PROJECT",
                    form_key=OTHER_FORM_KEY,
                    title="Clinic Visit",
                )
            )
            for device_id in ("dev-a", "dev-b"):
                session.add(
                    Device(
                        id=device_id, project_id="01PROJECT", user_id="usr-1", platform="android"
                    )
                )
            await session.flush()
            session.add(
                FormVersion(
                    id="01FORMV3", form_id="01FORM", version=FORM_VERSION, ir={}, ir_checksum="t"
                )
            )
            session.add(
                FormVersion(
                    id="01FORMCLINICV1",
                    form_id="01FORMCLINIC",
                    version=OTHER_FORM_VERSION,
                    ir={},
                    ir_checksum="t",
                )
            )
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def console_api() -> Any:
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
            await conn.execute(f"DROP DATABASE IF EXISTS {SUBMISSIONS_DB} WITH (FORCE)")
            await conn.execute(f"CREATE DATABASE {SUBMISSIONS_DB}")
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
    cfg.set_main_option("sqlalchemy.url", _db_url())
    command.upgrade(cfg, "head")

    asyncio.run(_seed())

    from app.api.deps import get_db
    from app.main import app

    async def scratch_db() -> AsyncIterator[Any]:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        # One engine per request: each test runs in its own event loop, and
        # pooled asyncpg connections cannot cross loops.
        engine = create_async_engine(_db_url())
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
            await conn.execute(f"DROP DATABASE IF EXISTS {SUBMISSIONS_DB} WITH (FORCE)")
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
    body: dict[str, Any] = response.json()
    assert body["rejected"] == [], body["rejected"]
    return body


async def _get(client: Any, url: str, **params: Any) -> dict[str, Any]:
    response = await client.get(url, params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


@pytest.mark.db
def test_list_reports_the_columns_the_console_shows(console_api: Any) -> None:
    async def scenario(client: Any) -> None:
        sub = "01SUBLISTCOLS"
        await _push(
            client,
            "dev-a",
            [
                _op("01OPCOLS1", sub, "dev-a", 1000, value="Amina"),
                _op("01OPCOLS2", sub, "dev-a", 1001, path="age", value=34),
                _op("01OPCOLS3", sub, "dev-a", 1002, kind="finalize", path=None),
            ],
        )

        body = await _get(client, "/api/v1/submissions")
        row = next(s for s in body["submissions"] if s["id"] == sub)
        assert row["formId"] == FORM_KEY
        assert row["formTitle"] == "Household"
        assert row["formVersion"] == FORM_VERSION
        assert row["originDeviceId"] == "dev-a"
        assert row["status"] == "finalized"
        assert row["opCount"] == 3
        assert row["receivedAt"]

    _run_with_client(console_api, scenario)


@pytest.mark.db
def test_filters_narrow_by_form_and_status(console_api: Any) -> None:
    async def scenario(client: Any) -> None:
        draft = "01SUBFILTERDRAFT"
        final = "01SUBFILTERFINAL"
        clinic = "01SUBFILTERCLINIC"
        await _push(client, "dev-a", [_op("01OPFILT1", draft, "dev-a", 1100, value="d")])
        await _push(
            client,
            "dev-a",
            [
                _op("01OPFILT2", final, "dev-a", 1101, value="f"),
                _op("01OPFILT3", final, "dev-a", 1102, kind="finalize", path=None),
            ],
        )
        await _push(
            client,
            "dev-b",
            [
                _op(
                    "01OPFILT4",
                    clinic,
                    "dev-b",
                    1103,
                    value="c",
                    form_id=OTHER_FORM_KEY,
                    form_version=OTHER_FORM_VERSION,
                )
            ],
        )

        by_form = await _get(client, "/api/v1/submissions", formId=OTHER_FORM_KEY)
        assert [s["id"] for s in by_form["submissions"]] == [clinic]
        assert by_form["total"] == 1

        by_status = await _get(client, "/api/v1/submissions", status="draft")
        ids = {s["id"] for s in by_status["submissions"]}
        assert draft in ids and clinic in ids
        assert final not in ids

        both = await _get(client, "/api/v1/submissions", formId=FORM_KEY, status="finalized")
        assert final in {s["id"] for s in both["submissions"]}
        # Filters compose: every row satisfies both, none satisfies only one.
        assert all(
            s["formId"] == FORM_KEY and s["status"] == "finalized" for s in both["submissions"]
        )

        # A typo'd status is an error, not a silently empty page.
        bad = await client.get("/api/v1/submissions", params={"status": "finalised"})
        assert bad.status_code == 422

    _run_with_client(console_api, scenario)


@pytest.mark.db
def test_paging_is_stable_and_bounded(console_api: Any) -> None:
    async def scenario(client: Any) -> None:
        for i in range(3):
            sub = f"01SUBPAGE{i}"
            await _push(client, "dev-a", [_op(f"01OPPAGE{i}", sub, "dev-a", 1200 + i, value=i)])

        first = await _get(client, "/api/v1/submissions", limit=2, offset=0)
        second = await _get(client, "/api/v1/submissions", limit=2, offset=2)
        assert len(first["submissions"]) == 2
        assert first["total"] == second["total"] >= 3
        # Pages partition: received_at ties are broken by id, so no overlap.
        assert not {s["id"] for s in first["submissions"]} & {
            s["id"] for s in second["submissions"]
        }

        over_limit = await client.get("/api/v1/submissions", params={"limit": 5000})
        assert over_limit.status_code == 422

    _run_with_client(console_api, scenario)


@pytest.mark.db
def test_detail_returns_the_log_in_counter_order_not_arrival_order(console_api: Any) -> None:
    """The op log is shown in (counter, deviceId) order — the order the fold
    replays in — so what the console displays explains the state beside it.

    dev-b's ops arrive after dev-a's but carry lower counters, so arrival
    order and replay order genuinely differ here.
    """

    async def scenario(client: Any) -> None:
        sub = "01SUBDETAIL"
        await _push(
            client,
            "dev-a",
            [
                _op("01OPDETA1", sub, "dev-a", 1310, path="age", value=40),
                _op("01OPDETA2", sub, "dev-a", 1311, value="from-a"),
            ],
        )
        await _push(
            client,
            "dev-b",
            [_op("01OPDETB1", sub, "dev-b", 1300, path="village", value="Kisumu")],
        )

        detail = await _get(client, f"/api/v1/submissions/{sub}")
        assert [op["id"] for op in detail["ops"]] == ["01OPDETB1", "01OPDETA1", "01OPDETA2"]
        assert [op["counter"] for op in detail["ops"]] == [1300, 1310, 1311]
        assert detail["opCount"] == 3
        assert detail["opsTruncated"] is False
        assert detail["ops"][0]["encrypted"] is False

        # The folded state is the one push committed, not a recomputation.
        assert detail["state"]["data"] == {"age": 40, "name": "from-a", "village": "Kisumu"}
        assert detail["state"]["opHighWater"] > 0
        assert detail["status"] == "draft"
        assert detail["formId"] == FORM_KEY
        assert detail["projectId"] == "01PROJECT"

    _run_with_client(console_api, scenario)


@pytest.mark.db
def test_unknown_submission_is_404(console_api: Any) -> None:
    async def scenario(client: Any) -> None:
        response = await client.get("/api/v1/submissions/01NOSUCHSUBMISSION")
        assert response.status_code == 404

    _run_with_client(console_api, scenario)


@pytest.mark.db
def test_forms_list_feeds_the_filter(console_api: Any) -> None:
    async def scenario(client: Any) -> None:
        body = await _get(client, "/api/v1/forms")
        forms = {f["formId"]: f for f in body["forms"]}
        assert forms[FORM_KEY]["title"] == "Household"
        assert forms[FORM_KEY]["versions"] == [FORM_VERSION]
        assert forms[OTHER_FORM_KEY]["versions"] == [OTHER_FORM_VERSION]

    _run_with_client(console_api, scenario)
