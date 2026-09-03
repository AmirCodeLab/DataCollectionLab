"""Export resolves everything against the version a submission was collected on.

Two bindings, one file, because they are the same mistake one level apart and
this repository has already paid for both:

  - **Which form version's columns a submission is read through** (break 40).
    A field renamed in v2 must not rename v1's answers, and a field added in v2
    must not make v1's submissions look like they left it blank on purpose.
  - **Which dataset version a code is named through** (break 42). The IR names
    a dataset by key and a key is not a version, so `V000023` is `Nyamburi Kati`
    for a submission collected under form v1 and `Nyamburi Mpya` for one
    collected under v2 — and an export that resolved either through "whatever
    is newest" would be wrong about the one it renamed, silently, in a column
    that reads perfectly.

The third thing here needs a database too: what an **unreadable** value exports
as, and which project keys open it. The token is a value; the key ids are what
turn "you have a problem" into "ask whoever holds `pk_alpha`".

The HTTP route is here too rather than in a file of its own, because it needs
this exact seed and a second scratch database is a second minute of migrations
in every CI run. What it adds is the thing no contract check can assert: that
the body a refusal actually sends is the body the document declares.

`db`-marked: the bindings *are* joins, so there is nothing to test without one.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pytest

pytestmark = pytest.mark.db

EXPORT_DB = "dcp_test_export"

PROJECT_ID = "01PROJEXPORT"
ENVIRONMENT_ID = "01ENVEXPORT"
DEVICE_ID = "dev_export"
USER_ID = "usr_export"
KEY_ALPHA = "01KEYALPHA"
KEY_BETA = "01KEYBETA"


def _roster_ir(version: int) -> dict[str, Any]:
    """v1 asks for a village. v2 asks for a village and the head's name."""
    children: list[dict[str, Any]] = [
        {
            "type": "question",
            "id": "village",
            "dataType": "select_one",
            "label": {"en": "Village"},
            "choices": {
                "kind": "dataset",
                "dataset": "villages",
                "valueColumn": "code",
                "labelColumn": {"en": "name"},
            },
        },
        {
            "type": "question",
            "id": "income",
            "dataType": "decimal",
            "label": {"en": "Monthly income"},
            "sensitive": True,
        },
    ]
    if version >= 2:
        children.append(
            {
                "type": "question",
                "id": "head_name",
                "dataType": "text",
                "label": {"en": "Head of household"},
            }
        )
    return {
        "irVersion": "0.1",
        "formId": "roster",
        "version": version,
        "title": {"en": "Roster"},
        "defaultLanguage": "en",
        "languages": ["en"],
        "children": children,
    }


def _villages(name: str) -> list[dict[str, Any]]:
    return [
        {"code": "V000023", "name": name},
        {"code": "V000024", "name": "Kilimani"},
    ]


def _database_url() -> str:
    from app.core.config import get_settings

    return get_settings().database_url


def _admin_dsn() -> str:
    parts = urlsplit(_database_url())
    return urlunsplit(parts._replace(scheme="postgresql", path="/postgres"))


def _export_db_url() -> str:
    parts = urlsplit(_database_url())
    return urlunsplit(parts._replace(scheme="postgresql+asyncpg", path=f"/{EXPORT_DB}"))


@pytest.fixture(scope="module")
def export_db() -> Any:
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
            await conn.execute(f"DROP DATABASE IF EXISTS {EXPORT_DB} WITH (FORCE)")
            await conn.execute(f"CREATE DATABASE {EXPORT_DB}")
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
    cfg.set_main_option("sqlalchemy.url", _export_db_url())
    command.upgrade(cfg, "head")

    asyncio.run(_seed(_export_db_url()))
    return _export_db_url()


@asynccontextmanager
async def _session(url: str) -> AsyncIterator[Any]:
    """A session as a context manager, never a generator to iterate.

    `async for session in _session(...)` with a `break` leaves the generator
    parked at its yield: nothing commits and nothing says so.
    `test_no_session_generator_loops.py` is the lint.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(url, future=True)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as session:
            yield session
    finally:
        await engine.dispose()


async def _seed(url: str) -> None:
    """Two form versions, two village lists, one submission on each version.

    The village list is republished with `V000023` **renamed** between the two.
    That rename is what makes the pin observable at all: with identical lists
    both bindings give the same answer and neither can be wrong.
    """
    from app.core.ulid import new_ulid
    from app.modules.crypto.models import ProjectKey
    from app.modules.entities import service as entities_service
    from app.modules.forms import service as forms_service
    from app.modules.forms.schemas import DatasetPin
    from app.modules.projects.models import Device, Environment, Project
    from app.modules.submissions.models import (
        Submission,
        SubmissionContentKey,
        SubmissionOp,
        SubmissionWrappedKey,
    )

    async with _session(url) as session, session.begin():
        session.add(Project(id=PROJECT_ID, name="Export", slug="export"))
        await session.flush()
        session.add(Environment(id=ENVIRONMENT_ID, project_id=PROJECT_ID, kind="production"))
        session.add(
            Device(id=DEVICE_ID, project_id=PROJECT_ID, user_id=USER_ID, platform="android")
        )
        for key_id, label in ((KEY_ALPHA, "alpha"), (KEY_BETA, "beta")):
            session.add(
                ProjectKey(
                    id=key_id,
                    project_id=PROJECT_ID,
                    public_key=bytes(range(32)),
                    key_role="primary" if key_id == KEY_ALPHA else "backup",
                    label=label,
                )
            )
        await session.flush()

        first = await entities_service.publish_dataset_version(
            session,
            project_id=PROJECT_ID,
            dataset_key="villages",
            rows=_villages("Nyamburi Kati"),
            key_column="code",
        )
        second = await entities_service.publish_dataset_version(
            session,
            project_id=PROJECT_ID,
            dataset_key="villages",
            rows=_villages("Nyamburi Mpya"),
            key_column="code",
        )
        await session.flush()

        versions = {}
        for number, pin in ((1, first), (2, second)):
            published = await forms_service.publish_version(
                session,
                project_id=PROJECT_ID,
                ir=_roster_ir(number),
                datasets=[
                    DatasetPin(key="villages", dataset_version_id=pin.dataset_version_id)
                ],
            )
            versions[number] = published.id
        await session.flush()

        counter = 0
        for number, submission_id in ((1, "sub_on_v1"), (2, "sub_on_v2")):
            session.add(
                Submission(
                    id=submission_id,
                    project_id=PROJECT_ID,
                    environment_id=ENVIRONMENT_ID,
                    form_version_id=versions[number],
                    origin_device_id=DEVICE_ID,
                    created_by=USER_ID,
                    status="finalized",
                    received_at=datetime(2026, 9, 3, 9, number, tzinfo=UTC),
                )
            )
            await session.flush()

            content_key_id = f"ck_{submission_id}"
            session.add(
                SubmissionContentKey(
                    id=content_key_id, submission_id=submission_id, device_id=DEVICE_ID
                )
            )
            await session.flush()
            for key_id in (KEY_ALPHA, KEY_BETA):
                session.add(
                    SubmissionWrappedKey(
                        content_key_id=content_key_id,
                        project_key_id=key_id,
                        submission_id=submission_id,
                        ephemeral_public=bytes(32),
                        nonce=bytes(12),
                        wrapped_key=bytes(48),
                    )
                )

            ops: list[dict[str, Any]] = [
                {"op_kind": "set", "path": "village", "value": "V000023"},
                {
                    "op_kind": "set",
                    "path": "income",
                    "value_ciphertext": b"\x01" * 24,
                    "content_key_id": content_key_id,
                    "nonce": counter.to_bytes(12, "big"),
                },
                {"op_kind": "finalize"},
            ]
            if number == 2:
                ops.insert(
                    0, {"op_kind": "set", "path": "head_name", "value": "Asha Mollel"}
                )
            for op in ops:
                counter += 1
                session.add(
                    SubmissionOp(
                        id=new_ulid(),
                        submission_id=submission_id,
                        device_id=DEVICE_ID,
                        counter=counter,
                        wall_clock=datetime(2026, 9, 3, 9, 0, tzinfo=UTC),
                        **op,
                    )
                )


async def _export(url: str, **overrides: Any) -> Any:
    from app.modules.export.service import export_form

    arguments: dict[str, Any] = {"form_key": "roster", **overrides}
    async with _session(url) as session, session.begin():
        return await export_form(session, **arguments)


def _rows(bundle: Any, table_name: str) -> list[dict[str, Any]]:
    table = next(t for t in bundle.tables if t.name == table_name)
    names = [column.name for column in table.columns]
    return [dict(zip(names, row, strict=True)) for row in table.rows]


def test_a_code_is_named_by_the_list_its_own_version_was_published_against(
    export_db: str,
) -> None:
    """The same code, two submissions, two names — and both are correct.

    `V000023` was renamed between the two village lists. The submission
    collected under form v1 must read `Nyamburi Kati`, because that is what the
    enumerator was shown and chose; the one under v2 must read `Nyamburi Mpya`.
    An export resolving through the newest list would give both the second name
    and be wrong about a village nobody could tell had moved.
    """
    bundle = asyncio.run(_export(export_db))
    rows = {row["submission_id"]: row for row in _rows(bundle, "roster")}

    assert rows["sub_on_v1"]["village"] == "V000023"
    assert rows["sub_on_v1"]["village_label"] == "Nyamburi Kati"
    assert rows["sub_on_v2"]["village"] == "V000023"
    assert rows["sub_on_v2"]["village_label"] == "Nyamburi Mpya"


def test_columns_are_the_union_and_a_v1_submission_is_not_read_through_v2(
    export_db: str,
) -> None:
    """`head_name` arrived in v2. v1's submissions have no such question.

    The column exists — dropping it would lose v2's answers — and the manifest
    records that it belongs to version 2, so a blank in a v1 row is explicable
    rather than looking like a question somebody declined.
    """
    bundle = asyncio.run(_export(export_db))
    rows = {row["submission_id"]: row for row in _rows(bundle, "roster")}

    assert rows["sub_on_v2"]["head_name"] == "Asha Mollel"
    assert rows["sub_on_v1"]["head_name"] is None
    assert rows["sub_on_v1"]["form_version"] == 1

    described = {
        column.column: column
        for table in bundle.manifest.tables
        for column in table.columns
    }
    assert described["head_name"].versions == (2,)
    assert described["village"].versions == (1, 2)
    assert bundle.manifest.form_versions == (1, 2)


def test_an_encrypted_answer_exports_as_the_token_and_names_the_keys_that_open_it(
    export_db: str,
) -> None:
    """The server stored ciphertext it cannot read, and the file says so.

    A blank here would be indistinguishable from an unanswered question, and
    every statistical tool would drop the row from a mean without a word. The
    key ids are the practical half: they say who to ask.
    """
    from app.modules.export.cells import ENCRYPTED

    bundle = asyncio.run(_export(export_db))
    rows = {row["submission_id"]: row for row in _rows(bundle, "roster")}
    assert rows["sub_on_v1"]["income"] == ENCRYPTED

    described = {
        column.column: column
        for table in bundle.manifest.tables
        for column in table.columns
    }
    assert described["income"].unreadable == "encrypted"
    assert described["income"].openable_by == (KEY_ALPHA, KEY_BETA)
    assert bundle.manifest.as_dict()["encryptedToken"] == ENCRYPTED


def test_an_unknown_form_is_none_and_a_filter_that_matches_nothing_is_an_empty_file(
    export_db: str,
) -> None:
    """"No such form" and "no submissions" are different answers.

    A customer whose filter matched nothing needs a file with its columns in it,
    not an error; a customer who mistyped the form key needs to be told.
    """
    assert asyncio.run(_export(export_db, form_key="nope")) is None

    empty = asyncio.run(_export(export_db, status="approved"))
    assert empty is not None
    assert empty.manifest.submission_count == 0
    assert _rows(empty, "roster") == []
    assert [c.name for c in empty.tables[0].columns] != []


def test_the_bundle_is_writable_in_every_format(export_db: str) -> None:
    """The zip is what a customer downloads; every format has to produce one."""
    for fmt in ("csv", "xlsx", "dta", "sav"):
        bundle = asyncio.run(_export(export_db, fmt=fmt))
        assert bundle is not None
        archive = bundle.to_zip()
        assert archive[:2] == b"PK"
        assert len(archive) > 0


def test_a_stata_export_reaches_the_same_answers_through_the_same_pins(
    export_db: str,
) -> None:
    """Everything the CSV binding test proves, through the writer with types.

    The bindings are the same code either way; what a `.dta` adds is a chance to
    lose the answer on the way out. `income` arrived as ciphertext, so its column
    is stored as **text** rather than numeric — a numeric column cannot hold the
    token, and writing it as missing is what would make three interviews vanish
    from a mean without a word.
    """
    from app.modules.export.cells import ENCRYPTED
    from app.modules.export.readback import read_bundle

    bundle = asyncio.run(_export(export_db, fmt="dta"))
    read = read_bundle(bundle)

    assert read["sub_on_v1"].top["village"] == "V000023"
    assert read["sub_on_v2"].top["head_name"] == "Asha Mollel"
    assert read["sub_on_v1"].top["income"] == ENCRYPTED

    described = {
        column.column: column
        for table in bundle.manifest.tables
        for column in table.columns
    }
    assert described["income"].storage_type == "string"
    assert described["income"].declared_storage_type == "numeric"
    assert described["income"].openable_by == (KEY_ALPHA, KEY_BETA)
    assert described["form_version"].storage_type == "numeric"


# ---------------------------------------------------------------------------
# Over HTTP. `GET /api/v1/exports/{formId}` — the route the console will use.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def export_api(export_db: str) -> Any:
    """The real app, with its session pointed at this module's database."""
    from app.api.deps import get_db
    from app.main import app

    async def scratch_db() -> AsyncIterator[Any]:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        # One engine per request: each test runs in its own event loop, and
        # pooled asyncpg connections cannot cross loops.
        engine = create_async_engine(export_db)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                yield session
        finally:
            await engine.dispose()

    app.dependency_overrides[get_db] = scratch_db
    yield app
    app.dependency_overrides.pop(get_db, None)


def _get(app: Any, url: str) -> Any:
    import httpx

    async def main() -> Any:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(url)

    return asyncio.run(main())


def test_the_route_returns_a_zip_a_browser_will_save(export_api: Any) -> None:
    """A bundle is several files, so it is always a zip — even holding one table.

    One shape, no branch on how many repeats a form happens to have. The
    filename is what a browser saves it as, so it names the form, the shape and
    the format rather than being `download.zip` in everybody's downloads folder.
    """
    import io
    import zipfile

    response = _get(export_api, "/api/v1/exports/roster")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    assert "roster-long-csv.zip" in response.headers["content-disposition"]

    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert "roster.csv" in archive.namelist()
    assert "manifest.json" in archive.namelist()


def test_the_format_and_shape_asked_for_are_the_ones_returned(export_api: Any) -> None:
    import io
    import zipfile

    response = _get(export_api, "/api/v1/exports/roster?format=dta&shape=wide")

    assert response.status_code == 200, response.text
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert archive.namelist() == ["roster.dta", "manifest.json"]
    assert "roster-wide-dta.zip" in response.headers["content-disposition"]


def test_an_unknown_form_is_a_404_in_the_envelope_the_document_declares(
    export_api: Any,
) -> None:
    response = _get(export_api, "/api/v1/exports/nope")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": "form not found"}


def test_too_many_submissions_is_a_413_carrying_the_numbers(export_api: Any) -> None:
    """The refusal body is the one the contract declares, fields and all.

    This is what a contract check cannot do. `test_openapi_contract.py` asserts
    the document says `{"detail": {found, limit, message}}`; only a request can
    say whether the server sends it. Declaring the payload instead of the
    envelope publishes a body the server has never returned, and a generated
    client then fails on the first refusal it meets — break 13, which happened.

    413 rather than 422: 422 belongs to the framework and means the request did
    not match the schema. This one matched it and asked for too much.
    """
    response = _get(export_api, "/api/v1/exports/roster?limit=1")

    assert response.status_code == 413
    body = response.json()
    assert set(body) == {"detail"}, body
    assert body["detail"]["found"] == 2
    assert body["detail"]["limit"] == 1
    assert "narrow it" in body["detail"]["message"].lower()


def test_a_bad_format_is_the_frameworks_422_and_not_ours(export_api: Any) -> None:
    """The one status this API does not choose. `422` means "did not match"."""
    response = _get(export_api, "/api/v1/exports/roster?format=parquet")
    assert response.status_code == 422
