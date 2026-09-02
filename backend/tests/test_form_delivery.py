"""Form delivery to devices (specs/sync-protocol-v0.1.md §5, `scope=forms`).

Before this, a form reached a phone by being compiled into the APK. That made
"a form authored by someone other than us, collected on a real phone" a thing
the system could not do at all — the customer's form had no route onto the
device.

The two rules these tests exist to hold are the ones that are cheap now and
expensive once devices are in the field:

1. **A device is offered every deployed version, not just the newest.** A
   submission is validated against the version it was collected under (Form IR
   §9), and an enumerator can be holding a v2 draft on the morning v3 deploys.
   Sending only the latest would leave that draft unopenable on the device that
   wrote it.

2. **Deployment is per environment.** A version deployed to staging must not
   reach a production device. Publishing is not deploying, and a published
   version nothing has deployed must reach nobody at all — otherwise "publish"
   silently means "ship to every phone in the field", which is the mistake this
   separation exists to make impossible.

The db-marked tests run the real endpoints against a scratch database migrated
to head. They skip when Postgres is unreachable (docker compose up -d postgres)
and are deselectable with -m "not db".
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pytest

FORMS_DB = "dcp_test_form_delivery"

PROJECT_ID = "01PROJECT"
# Two environments, so "deployed to staging" and "deployed to production" are
# distinguishable. A single-environment project could not tell the two rules
# above apart from a test that always passes.
ENV_PROD = "01ENVPROD"
ENV_STAGING = "01ENVSTG"

# dev-prod resolves to production (the preference order in forms.service);
# dev-revoked is registered and then revoked.
DEVICE = "dev-prod"
REVOKED_DEVICE = "dev-revoked"


def _ir(form_id: str, version: int) -> dict[str, Any]:
    """A minimal publishable Form IR document."""
    return {
        "irVersion": "0.1",
        "formId": form_id,
        "version": version,
        "title": {"en": f"{form_id} v{version}"},
        "defaultLanguage": "en",
        "languages": ["en"],
        "children": [
            {
                "type": "question",
                "id": "name",
                "dataType": "text",
                "label": {"en": "Name"},
            }
        ],
    }


# ---------------------------------------------------------------------------
# Scope parsing — no database needed
# ---------------------------------------------------------------------------


def test_pull_response_always_carries_a_forms_list() -> None:
    """`forms` is never absent, only empty.

    A response field the server sometimes omits makes a client handle three
    cases for two — the same reasoning as the encryption fields on PulledOp.
    """
    from app.modules.sync.schemas import PullResponse

    body = PullResponse(
        ops=[], tombstones=[], forms=[], next_cursor=0, has_more=False
    ).model_dump(by_alias=True)
    assert body["forms"] == []


# ---------------------------------------------------------------------------
# Live tests against the real endpoints
# ---------------------------------------------------------------------------


def _admin_dsn() -> str:
    from app.core.config import get_settings

    return get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")


def _forms_db_url() -> str:
    parts = urlsplit(_admin_dsn())
    return urlunsplit(parts._replace(scheme="postgresql+asyncpg", path=f"/{FORMS_DB}"))


async def _seed() -> None:
    from datetime import UTC, datetime

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.modules.forms import service as forms_service
    from app.modules.projects.models import Device, Environment, Project

    engine = create_async_engine(_forms_db_url())
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            # The models carry no relationship()s, so flush between dependency
            # levels to control insert order.
            session.add(Project(id=PROJECT_ID, name="Household Study", slug="household-study"))
            await session.flush()
            session.add(Environment(id=ENV_PROD, project_id=PROJECT_ID, kind="production"))
            session.add(Environment(id=ENV_STAGING, project_id=PROJECT_ID, kind="staging"))
            for device_id in (DEVICE, REVOKED_DEVICE):
                session.add(
                    Device(
                        id=device_id,
                        project_id=PROJECT_ID,
                        user_id="usr-1",
                        platform="android",
                        revoked_at=(
                            datetime.now(tz=UTC) if device_id == REVOKED_DEVICE else None
                        ),
                    )
                )
            await session.flush()

            # household v1 and v2 both deployed to production: the case rule 1
            # is about. household v3 published and NOT deployed. staging_only
            # v1 deployed to staging alone.
            for version in (1, 2):
                await forms_service.publish_version(
                    session,
                    project_id=PROJECT_ID,
                    ir=_ir("household", version),
                    deploy_to=["production"],
                )
            await forms_service.publish_version(
                session, project_id=PROJECT_ID, ir=_ir("household", 3), deploy_to=[]
            )
            await forms_service.publish_version(
                session,
                project_id=PROJECT_ID,
                ir=_ir("staging_only", 1),
                deploy_to=["staging"],
            )
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def forms_api() -> Any:
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
            await conn.execute(f"DROP DATABASE IF EXISTS {FORMS_DB} WITH (FORCE)")
            await conn.execute(f"CREATE DATABASE {FORMS_DB}")
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
    cfg.set_main_option("sqlalchemy.url", _forms_db_url())
    command.upgrade(cfg, "head")

    asyncio.run(_seed())

    from app.api.deps import get_db
    from app.main import app

    async def scratch_db() -> AsyncIterator[Any]:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        # One engine per request: each test runs in its own event loop, and
        # pooled asyncpg connections cannot cross loops.
        engine = create_async_engine(_forms_db_url())
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
            await conn.execute(f"DROP DATABASE IF EXISTS {FORMS_DB} WITH (FORCE)")
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


async def _manifest(client: Any, device_id: str = DEVICE) -> list[dict[str, Any]]:
    response = await client.get(
        "/api/v1/sync/pull", params={"scope": "forms", "deviceId": device_id}
    )
    assert response.status_code == 200, response.text
    return response.json()["forms"]


@pytest.mark.db
def test_a_device_is_offered_every_deployed_version_not_only_the_latest(forms_api: Any) -> None:
    """Rule 1 — Form IR §9.

    An enumerator holding a v2 draft when v3 deploys must still be able to open
    it, and the device can only do that if it was given v2's document. This is
    the assertion that fails if the manifest is ever narrowed to "the newest
    version of each form", which is the obvious-looking simplification.
    """

    async def scenario(client: Any) -> None:
        forms = await _manifest(client)
        household = [f for f in forms if f["formId"] == "household"]
        assert [f["version"] for f in household] == [1, 2]

    _run_with_client(forms_api, scenario)


@pytest.mark.db
def test_a_published_version_nobody_deployed_reaches_no_device(forms_api: Any) -> None:
    """Publishing is not deploying.

    household v3 is published — it is in the database, immutable, addressable —
    and no environment runs it. If publishing alone reached devices, every
    draft-in-progress form an author saved would ship to the field.
    """

    async def scenario(client: Any) -> None:
        forms = await _manifest(client)
        assert 3 not in [f["version"] for f in forms if f["formId"] == "household"]

    _run_with_client(forms_api, scenario)


@pytest.mark.db
def test_a_staging_deployment_does_not_reach_a_production_device(forms_api: Any) -> None:
    """Rule 2 — deployment is per environment.

    `staging_only` v1 is deployed, and to the wrong environment for this device.
    A manifest that ignored `form_deployment.environment_id` would hand a
    production phone a form still being tested.
    """

    async def scenario(client: Any) -> None:
        forms = await _manifest(client)
        assert "staging_only" not in {f["formId"] for f in forms}

    _run_with_client(forms_api, scenario)


@pytest.mark.db
def test_the_manifest_is_names_and_checksums_never_the_ir(forms_api: Any) -> None:
    """The manifest is small on purpose.

    A 52-question form is tens of kilobytes; a device re-syncs on whatever
    connection it has. If the IR ever leaks into this response, every pull pays
    for every form on the phone — on the links this protocol exists for, that is
    the difference between a sync that finishes and one that does not.
    """

    async def scenario(client: Any) -> None:
        forms = await _manifest(client)
        assert forms, "expected a manifest to check the shape of"
        for entry in forms:
            assert set(entry) == {
                "formVersionId",
                "formId",
                "version",
                "title",
                "irChecksum",
                "deployedAt",
            }
            assert entry["irChecksum"].startswith("sha256:")

    _run_with_client(forms_api, scenario)


@pytest.mark.db
def test_the_ir_is_fetched_by_the_id_the_manifest_gave(forms_api: Any) -> None:
    """The second half of delivery: the manifest names it, this hands it over.

    Also pins that the checksum in the manifest addresses the document actually
    returned — that equality is what lets a device skip a version it holds.
    """

    async def scenario(client: Any) -> None:
        from app.modules.forms.service import ir_checksum

        entry = next(f for f in await _manifest(client) if f["version"] == 2)
        response = await client.get(f"/api/v1/forms/versions/{entry['formVersionId']}")
        assert response.status_code == 200, response.text

        body = response.json()
        assert body["form"]["formId"] == "household"
        assert body["form"]["version"] == 2
        assert body["irChecksum"] == entry["irChecksum"]
        assert ir_checksum(body["form"]) == entry["irChecksum"]

    _run_with_client(forms_api, scenario)


@pytest.mark.db
def test_an_unknown_form_version_is_404_not_an_empty_document(forms_api: Any) -> None:
    async def scenario(client: Any) -> None:
        response = await client.get("/api/v1/forms/versions/01NOSUCHVERSION")
        assert response.status_code == 404, response.text

    _run_with_client(forms_api, scenario)


@pytest.mark.db
def test_pull_without_the_forms_scope_returns_an_empty_manifest(forms_api: Any) -> None:
    """A client that does not ask does not pay.

    `forms` is still present — see `test_pull_response_always_carries_a_forms_list`
    — but it costs nothing, which is what keeps `scope` meaningful rather than
    decorative.
    """

    async def scenario(client: Any) -> None:
        response = await client.get("/api/v1/sync/pull", params={"deviceId": DEVICE})
        assert response.status_code == 200, response.text
        assert response.json()["forms"] == []

    _run_with_client(forms_api, scenario)


@pytest.mark.db
def test_an_unknown_scope_word_is_accepted_rather_than_refused(forms_api: Any) -> None:
    """Spec §5 lists assignments, forms and datasets; two are unimplemented.

    A newer client asking for all three has to keep working against this server.
    Refusing an unknown scope would make every future scope a breaking change
    for every deployed device, which is backwards for self-hosted installs
    running whatever version they run.
    """

    async def scenario(client: Any) -> None:
        response = await client.get(
            "/api/v1/sync/pull",
            params={"scope": "assignments,forms,datasets", "deviceId": DEVICE},
        )
        assert response.status_code == 200, response.text
        assert response.json()["forms"], "forms should still be served alongside unknown scopes"

    _run_with_client(forms_api, scenario)


@pytest.mark.db
def test_forms_scope_without_a_device_cannot_guess_an_environment(forms_api: Any) -> None:
    """No device, no environment, no manifest.

    Answering with every published version would be the tempting fallback and it
    is exactly wrong: it would leak staging forms and undeployed drafts to any
    caller, and it would make the environment rule optional in practice.
    """

    async def scenario(client: Any) -> None:
        response = await client.get("/api/v1/sync/pull", params={"scope": "forms"})
        assert response.status_code == 200, response.text
        assert response.json()["forms"] == []

    _run_with_client(forms_api, scenario)


@pytest.mark.db
def test_a_revoked_device_is_told_about_no_forms(forms_api: Any) -> None:
    """A device the server will not take data from does not learn the forms.

    Same rule as `/devices/{id}/media-policy`. Pull does not refuse it — push is
    where a revoked device is told `not_authorized`, and a 200 with nothing in
    it keeps the two answers from disagreeing.
    """

    async def scenario(client: Any) -> None:
        assert await _manifest(client, REVOKED_DEVICE) == []
        assert await _manifest(client, "dev-never-registered") == []

    _run_with_client(forms_api, scenario)


@pytest.mark.db
def test_deploying_is_idempotent_and_additive(forms_api: Any) -> None:
    """Re-publishing identical content deploys without duplicating a row.

    The realistic caller is someone correcting a form that was published and
    never deployed: they re-run the publish with `deployTo` set. That must
    deploy it, must not create a second deployment row for the same pair, and
    must not retire the environments it already had — production and staging are
    separate statements, not a single "current" slot.
    """

    async def scenario(client: Any) -> None:
        body = {
            "projectId": PROJECT_ID,
            "form": _ir("household", 3),
            "deployTo": ["staging"],
        }
        first = await client.post("/api/v1/forms/versions", json=body)
        assert first.status_code == 201, first.text
        assert first.json()["created"] is False  # v3 was already published
        assert first.json()["deployments"] == ["staging"]

        second = await client.post(
            "/api/v1/forms/versions", json={**body, "deployTo": ["production"]}
        )
        assert second.status_code == 201, second.text
        # Additive: staging survives, production joins it. Sorted, so the
        # response does not depend on insertion order.
        assert second.json()["deployments"] == ["production", "staging"]

        third = await client.post("/api/v1/forms/versions", json=body)
        assert third.json()["deployments"] == ["production", "staging"]

        rows = await _db_snapshot(
            "SELECT environment_id FROM form_deployment fd "
            "JOIN form_version fv ON fv.id = fd.form_version_id "
            "WHERE fv.version = 3 AND fd.retired_at IS NULL"
        )
        assert sorted(r["environment_id"] for r in rows) == sorted([ENV_PROD, ENV_STAGING])

    _run_with_client(forms_api, scenario)


@pytest.mark.db
def test_deploying_to_an_environment_the_project_lacks_is_skipped_not_invented(
    forms_api: Any,
) -> None:
    """This project has production and staging, and no development environment.

    Creating one here would deploy a form to a place nothing is enrolled in —
    which reads as success in the response and reaches nobody, the exact failure
    mode `deployments` is reported to prevent.
    """

    async def scenario(client: Any) -> None:
        response = await client.post(
            "/api/v1/forms/versions",
            json={
                "projectId": PROJECT_ID,
                "form": _ir("household", 1),
                "deployTo": ["development"],
            },
        )
        assert response.status_code == 201, response.text
        assert "development" not in response.json()["deployments"]

        rows = await _db_snapshot(
            f"SELECT id FROM environment WHERE project_id = '{PROJECT_ID}'"
        )
        assert sorted(r["id"] for r in rows) == sorted([ENV_PROD, ENV_STAGING])

    _run_with_client(forms_api, scenario)


async def _db_snapshot(query: str) -> Any:
    import asyncpg

    parts = urlsplit(_admin_dsn())
    conn = await asyncpg.connect(urlunsplit(parts._replace(path=f"/{FORMS_DB}")))
    try:
        return await conn.fetch(query)
    finally:
        await conn.close()
