"""A form can be edited before it is published, and editing cannot publish it.

`form_draft` is the table item 0 needed and the platform did not have: every
form on the platform arrived already final, from an importer or a seed script,
which is the situation the visual builder exists to end
(`docs/phase3-item0-builder-scope.md` §6).

The risk it introduces is the one Form IR §2.3 is about. A table holding
unpublished IR sits next to the table holding published IR, and the shortcut is
obvious — copy the row, set a version number, skip `check_publishable`. The
schema removes half of that: a draft has no `version`, no `ir_checksum` and no
published state, so promotion is not a column write.
`test_form_version_has_one_writer.py` removes the other half.

What is left for this file is the behaviour: a draft holds work that does not
compile, and two authors do not silently overwrite each other.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from tests.identity_fixtures import ORG_ID, ensure_organization

DRAFT_DB = "dcp_test_draft"
PROJECT_ID = "01PROJDRAFT"
FORM_ID = "01FORMDRAFT"


def _database_url() -> str:
    from app.core.config import get_settings

    return get_settings().database_url


def _admin_dsn() -> str:
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(_database_url())
    return urlunsplit(parts._replace(scheme="postgresql", path="/postgres"))


def _db_url() -> str:
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(_database_url())
    return urlunsplit(parts._replace(scheme="postgresql+asyncpg", path=f"/{DRAFT_DB}"))


@asynccontextmanager
async def _session(url: str):  # noqa: ANN201 - an async context manager
    """A committing session — an `@asynccontextmanager`, never a bare generator."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as session:
            yield session
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def draft_db():  # noqa: ANN201 - pytest fixture
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
            await conn.execute(f"DROP DATABASE IF EXISTS {DRAFT_DB} WITH (FORCE)")
            await conn.execute(f"CREATE DATABASE {DRAFT_DB}")
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

    async def seed() -> None:
        from app.modules.forms.models import Form
        from app.modules.projects.models import Project

        # Two transactions, not one. The form's FK needs the project to be
        # committed, and relying on the unit of work to order two `add`s across
        # two modules is the kind of assumption that fails on a runner and not
        # on a laptop — which is exactly how this first ran.
        async with _session(_db_url()) as session, session.begin():
            await ensure_organization(session)
            session.add(Project(organization_id=ORG_ID, id=PROJECT_ID, name="Draft", slug="draft"))
        async with _session(_db_url()) as session, session.begin():
            session.add(Form(id=FORM_ID, project_id=PROJECT_ID, form_key="drafty", title="Drafty"))

    asyncio.run(seed())
    return _db_url()


pytestmark = pytest.mark.db


def test_a_draft_holds_a_form_that_does_not_compile(draft_db: str) -> None:
    """Most of editing is a form that is not valid yet.

    A draft that refused to hold work until it compiled would be a draft nobody
    could use: the first question an author adds references nothing, and the
    relevance they are halfway through writing names a field they have not
    created. `POST /forms/compile` is how they find out, on demand.
    """
    import asyncio

    from app.modules.forms import service

    broken = {"irVersion": "0.1", "formId": "drafty", "children": [{"nonsense": True}]}

    async def run() -> dict:
        async with _session(draft_db) as session, session.begin():
            draft = await service.save_draft(
                session, form_id=FORM_ID, ir=broken, expected_revision=None
            )
            return {"revision": draft.revision, "ir": draft.ir}

    saved = asyncio.run(run())
    assert saved["revision"] == 1
    assert saved["ir"] == broken


def test_a_stale_save_is_refused_rather_than_merged(draft_db: str) -> None:
    """Two authors, one draft. The second save with a stale revision loses.

    Last-write-wins is the default and it is the wrong default here: a
    discarded afternoon is not reported as a bug, it is assumed to be a
    forgotten save, so it never gets found.
    """
    import asyncio

    from app.modules.forms import service

    async def run() -> tuple[int, int | None]:
        async with _session(draft_db) as session, session.begin():
            first = await service.save_draft(
                session, form_id=FORM_ID, ir={"a": 1}, expected_revision=None
            )
            revision = first.revision

        # Author A saves against the revision they loaded.
        async with _session(draft_db) as session, session.begin():
            await service.save_draft(
                session, form_id=FORM_ID, ir={"a": 2}, expected_revision=revision
            )

        # Author B still holds the old one.
        conflict_at: int | None = None
        async with _session(draft_db) as session, session.begin():
            try:
                await service.save_draft(
                    session, form_id=FORM_ID, ir={"a": 3}, expected_revision=revision
                )
            except service.DraftConflict as exc:
                conflict_at = exc.current
        return revision, conflict_at

    revision, conflict_at = asyncio.run(run())
    assert conflict_at == revision + 1, (
        "a stale save should be refused, naming the current revision"
    )


def test_the_draft_survives_and_is_the_later_write(draft_db: str) -> None:
    """After the refused save, the winning author's work is what is stored."""
    import asyncio

    from app.modules.forms import service

    async def run() -> dict:
        async with _session(draft_db) as session, session.begin():
            draft = await service.get_draft(session, FORM_ID)
            assert draft is not None
            return draft.ir

    assert asyncio.run(run()) == {"a": 2}


def test_a_form_can_exist_with_nothing_published(draft_db: str) -> None:
    """The builder starts before anything is publishable.

    Until `POST /forms` a form row came only from publishing, and a draft
    cannot be held for a form that is not there — `form_draft.form_id` is a
    foreign key. So: create the row, save a draft against it, and the listing
    says which is which — `versions: []` and `hasDraft: true` — because a form
    that was started and never published must not look like an empty one.
    """
    import asyncio

    from app.modules.forms import service

    async def run() -> tuple[dict, dict, str | None]:
        async with _session(draft_db) as session, session.begin():
            created = await service.create_form(
                session, project_id=PROJECT_ID, form_key="started", title="Started"
            )
        async with _session(draft_db) as session, session.begin():
            await service.save_draft(
                session, form_id=created.id, ir={"formId": "started"}, expected_revision=None
            )
        async with _session(draft_db) as session, session.begin():
            listed = await service.list_forms(session, include_archived=False)
            mine = next(f for f in listed.forms if f.id == created.id)
        # The same key in the same project is the UNIQUE constraint on `form`,
        # reported before the database has to.
        duplicate: str | None = None
        async with _session(draft_db) as session, session.begin():
            try:
                await service.create_form(
                    session, project_id=PROJECT_ID, form_key="started", title="Again"
                )
            except service.FormExists as exc:
                duplicate = str(exc)
        return created.model_dump(), mine.model_dump(), duplicate

    created, mine, duplicate = asyncio.run(run())
    assert created["versions"] == [] and created["has_draft"] is False
    assert mine["versions"] == [] and mine["has_draft"] is True
    assert mine["project_id"] == PROJECT_ID
    assert mine["latest_version_id"] is None, "nothing is published"
    assert duplicate is not None and "started" in duplicate


def test_test_cases_live_with_the_draft(draft_db: str) -> None:
    """Builder scope §4 and §6: a draft is "IR + test cases", and a case is
    owned by the author — saved with the draft, returned with it, and left
    alone by a save that says nothing about it. The server runs nothing."""
    import asyncio

    from app.modules.forms import service

    cases = [
        {
            "id": "tc1",
            "name": "consent hides the page",
            "steps": [{"kind": "set", "path": "consent", "value": "no"}],
            "expectations": [{"path": "page_q", "relevant": False}],
        },
        {
            "id": "tc2",
            "name": "a member's age counts",
            "steps": [{"kind": "addRow", "repeatId": "members"}],
            "expectations": [{"path": "members[i1].age", "valid": False}],
        },
    ]

    async def run() -> tuple[list, list, list]:
        async with _session(draft_db) as session, session.begin():
            created = await service.create_form(
                session, project_id=PROJECT_ID, form_key="tested", title="Tested"
            )
        async with _session(draft_db) as session, session.begin():
            first = await service.save_draft(
                session,
                form_id=created.id,
                ir={"formId": "tested"},
                expected_revision=None,
                test_cases=cases,
            )
            revision = first.revision
        async with _session(draft_db) as session, session.begin():
            draft = await service.get_draft(session, created.id)
            stored = list(draft.test_cases) if draft else []
        # A save that says nothing about the cases leaves them.
        async with _session(draft_db) as session, session.begin():
            await service.save_draft(
                session,
                form_id=created.id,
                ir={"formId": "tested", "v": 2},
                expected_revision=revision,
                test_cases=None,
            )
        async with _session(draft_db) as session, session.begin():
            draft = await service.get_draft(session, created.id)
            kept = list(draft.test_cases) if draft else []
        # An empty list is a request to have none.
        async with _session(draft_db) as session, session.begin():
            await service.save_draft(
                session,
                form_id=created.id,
                ir={"formId": "tested", "v": 3},
                expected_revision=revision + 1,
                test_cases=[],
            )
        async with _session(draft_db) as session, session.begin():
            draft = await service.get_draft(session, created.id)
            cleared = list(draft.test_cases) if draft else ["never"]
        return stored, kept, cleared

    stored, kept, cleared = asyncio.run(run())
    assert stored == cases
    assert kept == cases
    assert cleared == []
