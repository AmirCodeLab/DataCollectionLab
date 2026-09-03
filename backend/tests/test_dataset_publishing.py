"""Publishing a dataset version: immutable, keyed, and canonically hashed.

The rules here are the ones that are cheap now and expensive once a device in
the field is pinned to a version. A dataset version that could change underneath
a published form would make every guarantee above it a lie — a submission is
validated against its form version, the form version is pinned to a dataset
version, and if that last link moves then answers were checked against a list
nobody can reconstruct.

The hashing tests are not about hashing. They are about two servers agreeing:
a hash that depends on dictionary order or on a locally-invented serialisation
makes every row look changed, and the symptom is a 50k-row transfer on a field
connection every time anything syncs.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from app.modules.entities.service import row_hash, version_checksum


def test_the_same_row_hashes_the_same_whatever_order_its_keys_arrive_in() -> None:
    """JSONB does not preserve key order and neither does a CSV reader.

    If order mattered, the same row read by two servers — or by the same server
    twice — would hash differently, every row would look changed, and every
    sync would ship the whole dataset.
    """
    one = {"code": "TZ01", "name_en": "Arusha", "name_sw": "Arusha", "pop": 1694310}
    other = {"pop": 1694310, "name_sw": "Arusha", "name_en": "Arusha", "code": "TZ01"}

    assert row_hash(one) == row_hash(other)


def test_the_hash_uses_the_envelope_s_canonical_json_and_not_a_second_one() -> None:
    """Reused rather than reinvented, and this is what says so.

    `canonical_json` already has a conformance vector behind it proving two
    implementations agree. A serialisation invented here would be a second thing
    to keep in step, and nothing would notice when it drifted.
    """
    import hashlib

    from app.modules.crypto.envelope import canonical_json

    row = {"code": "TZ01", "name": "Arusha"}
    assert row_hash(row) == "sha256:" + hashlib.sha256(canonical_json(row)).hexdigest()


def test_a_changed_value_changes_the_hash() -> None:
    # The control. Without it the two tests above could pass on a constant.
    assert row_hash({"code": "TZ01", "name": "Arusha"}) != row_hash(
        {"code": "TZ01", "name": "Arusha Mjini"}
    )


def test_non_ascii_survives_the_hash() -> None:
    """Real reference data is not ASCII, and `ensure_ascii=False` is why.

    Two implementations that disagreed about escaping would hash the same
    Swahili name differently and nothing else in the system would notice.
    """
    assert row_hash({"n": "Kilimanjaro"}) != row_hash({"n": "Kilimanjáro"})
    assert row_hash({"n": "Kilimanjáro"}) == row_hash({"n": "Kilimanjáro"})


def test_a_version_checksum_does_not_depend_on_insert_order() -> None:
    """"Is this the same dataset" must not depend on how the rows arrived."""
    rows = [("tz01", "sha256:a"), ("tz02", "sha256:b"), ("tz03", "sha256:c")]
    assert version_checksum(rows) == version_checksum(list(reversed(rows)))


def test_a_version_checksum_separates_key_from_hash() -> None:
    """Otherwise ("ab", "c") and ("a", "bc") would be the same dataset.

    A field separator sounds like pedantry until two datasets collide, at which
    point a device believes it is up to date and is holding somebody else's
    villages.
    """
    assert version_checksum([("ab", "c")]) != version_checksum([("a", "bc")])


def test_a_row_hash_is_not_what_decides_whether_a_device_is_sent_anything() -> None:
    """The two-stage rule, asserted so the distinction stays deliberate.

    An edit to a column no form references *does* change the row hash — that is
    correct, the row did change. It must not follow that a 50k-row list ships a
    delta over a field connection, because nothing an enumerator can see is
    different. Stage two compares the projection onto the columns the device's
    forms actually use, and that is what decides.
    """
    before = {"code": "TZ01", "name_en": "Arusha", "internal_note": "checked 2024"}
    after = {"code": "TZ01", "name_en": "Arusha", "internal_note": "checked 2026"}

    assert row_hash(before) != row_hash(after), "the row did change"

    used_columns = ("code", "name_en")
    project = lambda r: {k: r[k] for k in used_columns}  # noqa: E731
    assert row_hash(project(before)) == row_hash(project(after)), (
        "but nothing the form uses changed, so no delta should ship"
    )


# ---------------------------------------------------------------------------
# Publishing, against a real database
# ---------------------------------------------------------------------------

pytest_plugins: list[str] = []


@pytest.mark.db
def test_publishing_is_immutable_and_idempotent(dataset_db: str) -> None:
    """Same number, same content: fine. Same number, different content: refused.

    The second is the one that matters. A form version pinned to this dataset
    version would have its choice list changed underneath it, and answers
    already collected against it could no longer be explained.
    """
    import asyncio

    from app.modules.entities.service import DatasetRefused, publish_dataset_version

    rows = [
        {"code": "tz01", "name": "Arusha"},
        {"code": "tz02", "name": "Dodoma"},
    ]

    async def run() -> None:
        async with _session(dataset_db) as session:
            first = await publish_dataset_version(
                session, project_id=PROJECT_ID, dataset_key="regions",
                rows=rows, key_column="code",
            )
            assert first.created and first.version == 1 and first.row_count == 2

            again = await publish_dataset_version(
                session, project_id=PROJECT_ID, dataset_key="regions",
                rows=rows, key_column="code", version=1,
            )
            assert not again.created, "same content under the same number is a no-op"
            assert again.dataset_version_id == first.dataset_version_id

            with pytest.raises(DatasetRefused, match="immutable"):
                await publish_dataset_version(
                    session, project_id=PROJECT_ID, dataset_key="regions",
                    rows=[{"code": "tz01", "name": "Arusha Region"}],
                    key_column="code", version=1,
                )

    asyncio.run(run())


@pytest.mark.db
def test_a_dataset_without_usable_keys_is_refused(dataset_db: str) -> None:
    """A row with no identity cannot be selected, referred to, or deleted later.

    Both failures are what a real CSV produces: a blank cell in the key column,
    and the same village code twice.
    """
    import asyncio

    from app.modules.entities.service import DatasetRefused, publish_dataset_version

    async def run() -> None:
        async with _session(dataset_db) as session:
            with pytest.raises(DatasetRefused, match="no value in the key column"):
                await publish_dataset_version(
                    session, project_id=PROJECT_ID, dataset_key="blank",
                    rows=[{"code": "a"}, {"code": "  "}], key_column="code",
                )
            with pytest.raises(DatasetRefused, match="more than once"):
                await publish_dataset_version(
                    session, project_id=PROJECT_ID, dataset_key="dup",
                    rows=[{"code": "a"}, {"code": "a"}], key_column="code",
                )
            with pytest.raises(DatasetRefused, match="no rows"):
                await publish_dataset_version(
                    session, project_id=PROJECT_ID, dataset_key="empty",
                    rows=[], key_column="code",
                )

    asyncio.run(run())


# -- fixture plumbing -------------------------------------------------------

DATASET_DB = "dcp_test_datasets"
PROJECT_ID = "01PROJDATA"


def _database_url() -> str:
    from app.core.config import get_settings

    return get_settings().database_url


def _admin_dsn() -> str:
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(_database_url())
    return urlunsplit(parts._replace(scheme="postgresql", path="/postgres"))


def _dataset_db_url() -> str:
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(_database_url())
    return urlunsplit(parts._replace(scheme="postgresql+asyncpg", path=f"/{DATASET_DB}"))


@asynccontextmanager
async def _session(url: str):  # noqa: ANN201 - an async context manager
    """A committing session.

    An `async for ... break` over a generator was the first shape here and it
    silently did not commit: breaking out of the loop leaves the generator
    suspended at the yield, so nothing after it runs and the transaction is
    abandoned. A context manager cannot be exited without its __aexit__.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as session, session.begin():
            yield session
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def dataset_db():  # noqa: ANN201 - pytest fixture
    import asyncio

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
            await conn.execute(f"DROP DATABASE IF EXISTS {DATASET_DB} WITH (FORCE)")
            await conn.execute(f"CREATE DATABASE {DATASET_DB}")
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
    cfg.set_main_option("sqlalchemy.url", _dataset_db_url())
    command.upgrade(cfg, "head")

    async def seed() -> None:
        from app.modules.projects.models import Project

        async with _session(_dataset_db_url()) as session:
            session.add(Project(id=PROJECT_ID, name="Data", slug="data"))

    asyncio.run(seed())
    return _dataset_db_url()


@pytest.mark.db
def test_a_key_is_stored_exactly_and_never_trimmed(dataset_db: str) -> None:
    """Form IR §3.1, and its agreement with §6.3 is the whole reason.

    A dataset-backed select stores a value taken from `valueColumn`, and §6.3
    validates that value against the resolved list by exact match. If the key
    were trimmed here while the stored answer kept its whitespace, a legitimate
    answer would fail membership against the very row it came from — and the
    report would say the value is not in a list that visibly contains it.

    "Moshi" and "moshi " are therefore two rows, and the publisher is told.
    """
    import asyncio

    from sqlalchemy import select

    from app.modules.entities.models import DatasetRecord
    from app.modules.entities.service import publish_dataset_version

    async def run() -> tuple[list[str], list[str]]:
        async with _session(dataset_db) as session:
            published = await publish_dataset_version(
                session,
                project_id=PROJECT_ID,
                dataset_key="villages",
                rows=[
                    {"code": "Moshi", "name": "Moshi town"},
                    {"code": "moshi ", "name": "Moshi rural"},
                ],
                key_column="code",
            )
            keys = (
                await session.execute(
                    select(DatasetRecord.record_key).where(
                        DatasetRecord.dataset_version_id == published.dataset_version_id
                    )
                )
            ).scalars().all()
            return sorted(keys), published.warnings

    keys, warnings = asyncio.run(run())

    assert keys == ["Moshi", "moshi "], (
        f"keys were altered on the way in: {keys}. A trimmed or folded key stops "
        "matching the answer that was collected from it."
    )
    assert warnings, "differing only by case or whitespace must be reported"
    assert "not merged" in warnings[0]


@pytest.mark.db
def test_a_key_that_is_only_whitespace_is_still_refused(dataset_db: str) -> None:
    """Exactness is not the same as accepting anything.

    "   " is no identity at all — it cannot be selected, referred to, or deleted
    in a later version — so emptiness is decided after stripping even though
    what gets *stored* never is.
    """
    import asyncio

    from app.modules.entities.service import DatasetRefused, publish_dataset_version

    async def run() -> None:
        async with _session(dataset_db) as session:
            with pytest.raises(DatasetRefused, match="no value in the key column"):
                await publish_dataset_version(
                    session, project_id=PROJECT_ID, dataset_key="ws",
                    rows=[{"code": "a"}, {"code": "   "}], key_column="code",
                )

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Over HTTP: POST /api/v1/projects/{projectId}/datasets
# ---------------------------------------------------------------------------
#
# Multipart, because the caller already has the file and a 38,000-row list
# re-encoded as JSON is several megabytes of body for nothing. The route is
# also where the two refusal shapes have to stay apart: a file that is not a
# readable CSV is a 400 (there is no dataset here to refuse), and a dataset
# whose keys are unusable is a 409 (there is, and these are the reasons).


def _api(method: str, url: str, database_url: str, **kwargs):  # noqa: ANN202
    import asyncio

    import httpx

    from app.api.deps import get_db
    from app.main import app

    async def override():  # noqa: ANN202
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        engine = create_async_engine(database_url)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with maker() as session:
                yield session
        finally:
            await engine.dispose()

    app.dependency_overrides[get_db] = override

    async def main():  # noqa: ANN202
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, url, **kwargs)

    try:
        return asyncio.run(main())
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.db
def test_publishing_a_csv_over_http_returns_its_content_address(dataset_db: str) -> None:
    response = _api(
        "POST",
        f"/api/v1/projects/{PROJECT_ID}/datasets",
        dataset_db,
        files={"file": ("wards.csv", b"name,label\nW01,Kata Moja\nW02,Kata Mbili\n", "text/csv")},
        data={"datasetKey": "wards"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["datasetKey"] == "wards"
    assert body["rowCount"] == 2
    assert body["created"] is True
    assert body["checksum"].startswith("sha256:")
    assert body["publishedAt"] is not None, "a version row that exists is published"


@pytest.mark.db
def test_re_uploading_an_unchanged_file_publishes_nothing_new(dataset_db: str) -> None:
    """The console re-sends the companion files every time somebody presses
    Publish, so this is the common path and not the odd one.

    A duplicate version is not merely untidy: a device holding the old id would
    be told it is behind and re-fetch rows that did not change, which on a
    field connection is the cost this whole design exists to avoid.
    """
    payload = {
        "files": {"file": ("streets.csv", b"name,label\nS01,Barabara\n", "text/csv")},
        "data": {"datasetKey": "streets"},
    }
    first = _api("POST", f"/api/v1/projects/{PROJECT_ID}/datasets", dataset_db, **payload)
    again = _api("POST", f"/api/v1/projects/{PROJECT_ID}/datasets", dataset_db, **payload)

    assert first.json()["created"] is True
    assert again.json()["created"] is False
    assert again.json()["datasetVersionId"] == first.json()["datasetVersionId"]
    assert again.json()["version"] == first.json()["version"] == 1


@pytest.mark.db
def test_changed_content_becomes_a_new_version(dataset_db: str) -> None:
    first = _api(
        "POST",
        f"/api/v1/projects/{PROJECT_ID}/datasets",
        dataset_db,
        files={"file": ("wards2.csv", b"name,label\nW01,One\n", "text/csv")},
        data={"datasetKey": "wards2"},
    )
    second = _api(
        "POST",
        f"/api/v1/projects/{PROJECT_ID}/datasets",
        dataset_db,
        files={"file": ("wards2.csv", b"name,label\nW01,One\nW02,Two\n", "text/csv")},
        data={"datasetKey": "wards2"},
    )
    assert first.json()["version"] == 1
    assert second.json()["version"] == 2
    assert second.json()["checksum"] != first.json()["checksum"]


@pytest.mark.db
def test_a_file_that_is_not_a_readable_csv_is_a_400_not_a_409(dataset_db: str) -> None:
    """The distinction `WorkbookError` draws, one level down: a 409 says "this
    dataset cannot be published and here is why", and there is no dataset
    here to say it about."""
    response = _api(
        "POST",
        f"/api/v1/projects/{PROJECT_ID}/datasets",
        dataset_db,
        files={"file": ("bad.csv", b"name;label\nW01;Kata\n", "text/csv")},
        data={"datasetKey": "bad"},
    )
    assert response.status_code == 400
    assert "semicolon" in response.json()["detail"]


@pytest.mark.db
def test_unusable_keys_are_a_409_listing_every_reason(dataset_db: str) -> None:
    """409 and not 422, deliberately: 422 already belongs to FastAPI's own
    request-validation failure and only one body shape can be declared under
    one status (docs/project-conventions.md, "The API contract")."""
    response = _api(
        "POST",
        f"/api/v1/projects/{PROJECT_ID}/datasets",
        dataset_db,
        files={"file": ("dupes.csv", b"name,label\nW01,One\nW01,Two\n,Three\n", "text/csv")},
        data={"datasetKey": "dupes"},
    )
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, list), "every reason in one pass, not the first one"
    assert any("more than once" in reason for reason in detail)
    assert any("no value in the key column" in reason for reason in detail)


@pytest.mark.db
def test_the_files_own_findings_travel_with_the_datasets(dataset_db: str) -> None:
    """A padded row and a confusable key are the same kind of fact to whoever
    uploaded the file, so they arrive in one list rather than two places."""
    response = _api(
        "POST",
        f"/api/v1/projects/{PROJECT_ID}/datasets",
        dataset_db,
        files={
            "file": (
                "mixed.csv",
                b"name,label,ward\nMoshi,Moshi town,Kata\nmoshi ,Moshi rural\n",
                "text/csv",
            )
        },
        data={"datasetKey": "mixed"},
    )
    assert response.status_code == 201, response.text
    warnings = response.json()["warnings"]
    assert any("fewer values" in w for w in warnings), "the file's own finding"
    assert any("not merged" in w for w in warnings), "the dataset's finding"
