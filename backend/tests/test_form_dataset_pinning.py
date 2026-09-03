"""A form version and the exact choice lists it was published against.

The IR names a dataset by **key** — `"dataset": "villages"` (Form IR §3) — and
a key is not a version. If the key were resolved when a form is opened rather
than when it is published, a draft started against form v1 would see whatever
`villages` happens to be newest by the time somebody finishes it. That is the
same mistake as validating a v1 answer against v2's choice list (break 30,
break 40), and it has the same symptom: an answer nobody can explain, checked
against a list nobody can reconstruct.

So the resolution happens once, at publish, into `form_version_dataset`, and
this is the file that holds it there. The tests are all refusals, because the
guarantee is entirely made of refusals — a pin that resolves is unremarkable
and a pin that quietly does not is the whole failure.

Break 42: `_resolve_dataset_pins` removed, a form naming three datasets
published with none pinned, and every unit test stayed green. The IR was valid,
it compiled, both engines agreed, the conformance run was clean — and the
published version said nothing about which villages it offered. Watched to fail
before it was written; recorded in docs/known-breaks.md.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

DATASET_DB = "dcp_test_pinning"
PROJECT_ID = "01PROJPIN"
OTHER_PROJECT_ID = "01PROJPIN2"


def _ir(*dataset_keys: str) -> dict:
    """A minimal form choosing from each named dataset."""
    return {
        "irVersion": "0.1",
        "formId": "pinned",
        "version": 1,
        "title": {"en": "Pinned"},
        "defaultLanguage": "en",
        "languages": ["en"],
        "children": [
            {
                "type": "question",
                "id": f"q{index}",
                "dataType": "select_one",
                "label": {"en": f"Q{index}"},
                "choices": {
                    "kind": "dataset",
                    "dataset": key,
                    "valueColumn": "name",
                    "labelColumn": {"en": "label"},
                },
            }
            for index, key in enumerate(dataset_keys, start=1)
        ]
        or [
            {
                "type": "question",
                "id": "q1",
                "dataType": "text",
                "label": {"en": "Q1"},
            }
        ],
    }


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
    return urlunsplit(parts._replace(scheme="postgresql+asyncpg", path=f"/{DATASET_DB}"))


@asynccontextmanager
async def _session(url: str):  # noqa: ANN201 - an async context manager
    """A committing session — an `@asynccontextmanager`, never a bare generator.

    See the docs/project-conventions.md convention and `test_no_session_generator_loops.py`: an
    `async for ... break` leaves the generator parked at its yield, the
    `async with` never exits, and the write is discarded with no error.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as session:
            yield session
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def pinning_db():  # noqa: ANN201 - pytest fixture
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
    cfg.set_main_option("sqlalchemy.url", _db_url())
    command.upgrade(cfg, "head")

    async def seed() -> None:
        from app.modules.projects.models import Project

        async with _session(_db_url()) as session, session.begin():
            session.add(Project(id=PROJECT_ID, name="Pinning", slug="pinning"))
            session.add(Project(id=OTHER_PROJECT_ID, name="Other", slug="other"))

    asyncio.run(seed())
    return _db_url()


@pytest.fixture(scope="module")
def versions(pinning_db: str) -> dict[str, str]:
    """Two datasets in this project and one in another, published."""
    import asyncio

    from app.modules.entities.service import publish_dataset_version

    async def run() -> dict[str, str]:
        published: dict[str, str] = {}
        async with _session(pinning_db) as session, session.begin():
            for project, key in (
                (PROJECT_ID, "villages"),
                (PROJECT_ID, "districts"),
                (OTHER_PROJECT_ID, "villages"),
            ):
                result = await publish_dataset_version(
                    session,
                    project_id=project,
                    dataset_key=key,
                    rows=[{"name": f"{key}-1", "label": "One"}],
                    key_column="name",
                )
                published[f"{project}/{key}"] = result.dataset_version_id
        return published

    return asyncio.run(run())


def _publish(url: str, ir: dict, pins: list[tuple[str, str]], form_key: str):  # noqa: ANN202
    """Publish, returning the response or raising PublishRefused."""
    import asyncio

    from app.modules.forms import service
    from app.modules.forms.schemas import DatasetPin

    document = dict(ir)
    document["formId"] = form_key

    async def run():  # noqa: ANN202
        async with _session(url) as session, session.begin():
            return await service.publish_version(
                session,
                project_id=PROJECT_ID,
                ir=document,
                datasets=[DatasetPin(key=k, dataset_version_id=v) for k, v in pins],
            )

    return asyncio.run(run())


# ---------------------------------------------------------------------------


@pytest.mark.db
def test_a_pinned_form_records_which_version_each_list_resolves_to(
    pinning_db: str, versions: dict[str, str]
) -> None:
    """The ordinary case, and what the row must actually contain afterwards.

    Asserted by reading `form_version_dataset` rather than the response,
    because the response is what the code says it did and the table is what
    survives the process.
    """
    import asyncio

    from sqlalchemy import select

    from app.modules.entities.models import FormVersionDataset

    response = _publish(
        pinning_db,
        _ir("villages", "districts"),
        [
            ("villages", versions[f"{PROJECT_ID}/villages"]),
            ("districts", versions[f"{PROJECT_ID}/districts"]),
        ],
        "pinned_ok",
    )
    assert response.created
    assert {p.key for p in response.datasets} == {"villages", "districts"}

    async def stored() -> dict[str, str]:
        async with _session(pinning_db) as session:
            rows = await session.execute(
                select(
                    FormVersionDataset.dataset_key, FormVersionDataset.dataset_version_id
                ).where(FormVersionDataset.form_version_id == response.id)
            )
            return {key: version for key, version in rows}

    assert asyncio.run(stored()) == {
        "villages": versions[f"{PROJECT_ID}/villages"],
        "districts": versions[f"{PROJECT_ID}/districts"],
    }


@pytest.mark.db
def test_a_form_that_names_a_dataset_and_pins_nothing_is_refused(
    pinning_db: str, versions: dict[str, str]
) -> None:
    """Break 42.

    This is the failure with no other symptom. The IR is valid, it compiles,
    both engines agree, every conformance vector passes — and the version says
    nothing about which villages it offered, so the list would have to be
    resolved later against whatever is newest.
    """
    from app.modules.forms.service import PublishRefused

    with pytest.raises(PublishRefused) as refusal:
        _publish(pinning_db, _ir("villages"), [], "pinned_none")
    assert any("`villages`" in v for v in refusal.value.violations)
    assert any("published against" in v for v in refusal.value.violations)


@pytest.mark.db
def test_every_missing_pin_is_named_in_one_pass(
    pinning_db: str, versions: dict[str, str]
) -> None:
    # One refusal listing both, not two round trips.
    from app.modules.forms.service import PublishRefused

    with pytest.raises(PublishRefused) as refusal:
        _publish(pinning_db, _ir("villages", "districts"), [], "pinned_none2")
    joined = " ".join(refusal.value.violations)
    assert "`villages`" in joined and "`districts`" in joined


@pytest.mark.db
def test_a_pin_for_a_dataset_the_form_does_not_use_is_refused(
    pinning_db: str, versions: dict[str, str]
) -> None:
    """A pin nothing references is a claim about this version that is not true.

    Usually it means the caller published a different form's companion files,
    which is worth a refusal rather than a stored row nobody will ever read.
    """
    from app.modules.forms.service import PublishRefused

    with pytest.raises(PublishRefused) as refusal:
        _publish(
            pinning_db,
            _ir("villages"),
            [
                ("villages", versions[f"{PROJECT_ID}/villages"]),
                ("districts", versions[f"{PROJECT_ID}/districts"]),
            ],
            "pinned_extra",
        )
    assert any("no question in this form chooses from" in v for v in refusal.value.violations)


@pytest.mark.db
def test_a_pin_to_another_project_s_dataset_is_refused(
    pinning_db: str, versions: dict[str, str]
) -> None:
    """Not an ordering mistake — a disclosure.

    Reference data belongs to a project. A form here pinned to another
    project's `villages` would deliver that project's villages to these
    devices, and nothing downstream would ever question it: the key matches,
    the version exists, the choice list resolves.
    """
    from app.modules.forms.service import PublishRefused

    with pytest.raises(PublishRefused) as refusal:
        _publish(
            pinning_db,
            _ir("villages"),
            [("villages", versions[f"{OTHER_PROJECT_ID}/villages"])],
            "pinned_cross",
        )
    assert any("different project" in v for v in refusal.value.violations)


@pytest.mark.db
def test_a_pin_to_a_version_that_does_not_exist_is_refused(
    pinning_db: str, versions: dict[str, str]
) -> None:
    from app.modules.forms.service import PublishRefused

    with pytest.raises(PublishRefused) as refusal:
        _publish(pinning_db, _ir("villages"), [("villages", "01NOSUCHVERSION")], "pinned_ghost")
    assert any("does not exist" in v for v in refusal.value.violations)


@pytest.mark.db
def test_a_pin_naming_a_different_dataset_than_its_key_is_refused(
    pinning_db: str, versions: dict[str, str]
) -> None:
    """`villages` pinned to a version of `districts`. The key would resolve and
    the question would offer the wrong list, with everything else consistent."""
    from app.modules.forms.service import PublishRefused

    with pytest.raises(PublishRefused) as refusal:
        _publish(
            pinning_db,
            _ir("villages"),
            [("villages", versions[f"{PROJECT_ID}/districts"])],
            "pinned_swapped",
        )
    assert any("a version of `districts`" in v for v in refusal.value.violations)


@pytest.mark.db
def test_republishing_the_same_version_against_a_different_list_is_refused(
    pinning_db: str, versions: dict[str, str]
) -> None:
    """Identical IR is not the same form if its villages moved.

    A published version is immutable, and its view of its reference data is
    part of what is published. Letting the pin move would change what an
    already-collected answer was chosen from, with the IR checksum unchanged
    and nothing to notice.
    """
    import asyncio

    from app.modules.entities.service import publish_dataset_version
    from app.modules.forms.service import PublishRefused

    async def second_version() -> str:
        async with _session(pinning_db) as session, session.begin():
            result = await publish_dataset_version(
                session,
                project_id=PROJECT_ID,
                dataset_key="villages",
                rows=[{"name": "villages-1", "label": "One"}, {"name": "v2", "label": "Two"}],
                key_column="name",
            )
            return result.dataset_version_id

    first = _publish(
        pinning_db,
        _ir("villages"),
        [("villages", versions[f"{PROJECT_ID}/villages"])],
        "pinned_immutable",
    )
    assert first.created

    moved = asyncio.run(second_version())
    with pytest.raises(PublishRefused) as refusal:
        _publish(pinning_db, _ir("villages"), [("villages", moved)], "pinned_immutable")
    assert any("cannot move underneath" in v for v in refusal.value.violations)


@pytest.mark.db
def test_republishing_identical_content_and_pins_is_a_no_op(
    pinning_db: str, versions: dict[str, str]
) -> None:
    """The retry case. Re-running a seed must not refuse and must not duplicate."""
    pins = [("villages", versions[f"{PROJECT_ID}/villages"])]
    first = _publish(pinning_db, _ir("villages"), pins, "pinned_retry")
    again = _publish(pinning_db, _ir("villages"), pins, "pinned_retry")
    assert first.created and not again.created
    assert first.id == again.id
    assert {p.key for p in again.datasets} == {"villages"}


@pytest.mark.db
def test_a_form_with_no_datasets_publishes_with_no_pins(pinning_db: str) -> None:
    """The ordinary form must not have to say anything about datasets at all."""
    response = _publish(pinning_db, _ir(), [], "pinned_plain")
    assert response.created
    assert response.datasets == []


@pytest.mark.db
def test_the_same_dataset_pinned_twice_is_refused(
    pinning_db: str, versions: dict[str, str]
) -> None:
    """Two answers to one question, and no way to say which the answers were
    collected against. Taking the last one would be a coin toss recorded as a
    fact."""
    from app.modules.forms.service import PublishRefused

    with pytest.raises(PublishRefused) as refusal:
        _publish(
            pinning_db,
            _ir("villages"),
            [
                ("villages", versions[f"{PROJECT_ID}/villages"]),
                ("villages", versions[f"{PROJECT_ID}/districts"]),
            ],
            "pinned_twice",
        )
    assert any("pinned twice" in v for v in refusal.value.violations)


@pytest.mark.db
def test_a_pinned_dataset_version_cannot_be_deleted_out_from_under_a_form(
    pinning_db: str, versions: dict[str, str]
) -> None:
    """`form_version_dataset.dataset_version_id` is ON DELETE RESTRICT.

    Not a detail of the migration: a deleted dataset version is a published
    form whose choice lists stop resolving and whose collected answers stop
    being explicable. The database is where that is made impossible, because
    the delete would otherwise come from a script nobody reviewed.
    """
    import asyncio

    import sqlalchemy.exc
    from sqlalchemy import delete

    from app.modules.entities.models import DatasetVersion

    _publish(
        pinning_db,
        _ir("villages"),
        [("villages", versions[f"{PROJECT_ID}/villages"])],
        "pinned_restrict",
    )

    async def attempt() -> None:
        async with _session(pinning_db) as session, session.begin():
            await session.execute(
                delete(DatasetVersion).where(
                    DatasetVersion.id == versions[f"{PROJECT_ID}/villages"]
                )
            )

    with pytest.raises(sqlalchemy.exc.IntegrityError):
        asyncio.run(attempt())


# ---------------------------------------------------------------------------
# Delivery (sync §5, `scope=datasets`) and the resolver
# ---------------------------------------------------------------------------


@pytest.mark.db
def test_the_manifest_is_derived_from_the_pins_and_not_from_the_project(
    pinning_db: str, versions: dict[str, str]
) -> None:
    """A device is told about the lists its forms were published against.

    Not the datasets its project owns. A dataset nothing references is a
    38,000-row transfer for a question nobody will be asked, and the pinning
    that makes an answer explicable is the same thing that decides what travels.
    """
    import asyncio

    from app.modules.entities.service import deployed_dataset_versions_for_device

    published = _publish(
        pinning_db,
        _ir("villages"),
        [("villages", versions[f"{PROJECT_ID}/villages"])],
        "manifest_form",
    )

    async def run():  # noqa: ANN202
        from app.modules.forms import service as forms_service
        from app.modules.projects.models import Device, Environment

        async with _session(pinning_db) as session, session.begin():
            environment = Environment(id="01ENVPIN", project_id=PROJECT_ID, kind="production")
            session.add(environment)
            session.add(
                Device(
                    id="01DEVPIN",
                    project_id=PROJECT_ID,
                    user_id="01USERPIN",
                    platform="android",
                )
            )
        async with _session(pinning_db) as session, session.begin():
            await forms_service.deploy_version(
                session,
                project_id=PROJECT_ID,
                form_version_id=published.id,
                kinds=["production"],
            )
        async with _session(pinning_db) as session:
            return await deployed_dataset_versions_for_device(session, "01DEVPIN")

    manifest = asyncio.run(run())
    assert manifest is not None
    keys = {(m.dataset_key, m.dataset_version_id) for m in manifest}
    assert keys == {("villages", versions[f"{PROJECT_ID}/villages"])}, (
        "`districts` exists in this project and no deployed form pins it, so it "
        "must not be in the manifest"
    )
    assert all(m.form_version_id == published.id for m in manifest), (
        "the pin is per form version, because two versions of a form can be "
        "deployed at once and may name different lists"
    )


@pytest.mark.db
def test_an_unknown_device_is_told_nothing_rather_than_told_there_is_nothing(
    pinning_db: str,
) -> None:
    """None and [] are different answers, and this is the one that matters.

    `[]` is an instruction: it means "your forms reference no lists", and a
    device acts on it by dropping what it holds. A device the server does not
    recognise must not be given that instruction — its answers are not ours to
    destroy on the strength of a question it was not allowed to ask.
    """
    import asyncio

    from app.modules.entities.service import deployed_dataset_versions_for_device

    async def run():  # noqa: ANN202
        async with _session(pinning_db) as session:
            return await deployed_dataset_versions_for_device(session, "01NOSUCHDEVICE")

    assert asyncio.run(run()) is None


@pytest.mark.db
def test_rows_page_resumes_from_its_cursor_and_says_when_it_is_done(
    pinning_db: str,
) -> None:
    """`nextCursor` null is how a device knows it has the whole list.

    It matters more here than anywhere else in this API: a village list that
    stopped two thirds of the way through is one an enumerator can search,
    scroll and choose from, and nothing about it looks wrong.
    """
    import asyncio

    from app.modules.entities.service import dataset_rows_page, publish_dataset_version

    async def run():  # noqa: ANN202
        async with _session(pinning_db) as session, session.begin():
            published = await publish_dataset_version(
                session,
                project_id=PROJECT_ID,
                dataset_key="paged",
                rows=[{"name": f"V{i:03d}", "label": f"Village {i}"} for i in range(250)],
                key_column="name",
            )
        seen: list[str] = []
        cursor = None
        pages = 0
        async with _session(pinning_db) as session:
            while True:
                page = await dataset_rows_page(
                    session,
                    dataset_version_id=published.dataset_version_id,
                    cursor=cursor,
                    limit=100,
                )
                assert page is not None
                rows, cursor = page
                seen += [r["name"] for r in rows]
                pages += 1
                if cursor is None:
                    break
        return seen, pages

    seen, pages = asyncio.run(run())
    assert pages == 3, "250 rows at 100 a page"
    assert len(seen) == 250
    assert seen == [f"V{i:03d}" for i in range(250)], (
        "the file's own order, kept. A list is offered in the order its author "
        "wrote it, and paging by ULID delivered 38,000 villages in an order "
        "nobody chose — stable, and scrambled."
    )
    assert len(set(seen)) == 250, "a resumed page must not repeat what the last one sent"


@pytest.mark.db
def test_a_missing_dataset_version_is_none_rather_than_an_empty_page(
    pinning_db: str,
) -> None:
    # An empty page and a version that does not exist lead to different next
    # steps, and a client that could not tell them apart would mark a
    # nonexistent list complete.
    import asyncio

    from app.modules.entities.service import dataset_rows_page

    async def run():  # noqa: ANN202
        async with _session(pinning_db) as session:
            return await dataset_rows_page(
                session, dataset_version_id="01NOSUCHVERSION", cursor=None, limit=10
            )

    assert asyncio.run(run()) is None


@pytest.mark.db
def test_the_server_resolver_takes_no_version_either(
    pinning_db: str, versions: dict[str, str]
) -> None:
    """`dataset_rows_for(submission_id, dataset_key)` — break 42's shape, again.

    The client's `DatasetStore.rowsFor` has no way to ask for a dataset key
    alone and neither does this. A resolver that took a version would let a
    caller explain a submission against whatever list is newest, which is the
    mistake breaks 30, 40 and 42 are all the same instance of.
    """
    import inspect

    from app.modules.entities.service import dataset_rows_for

    parameters = list(inspect.signature(dataset_rows_for).parameters)
    assert parameters == ["session", "submission_id", "dataset_key"], (
        "a `version` parameter here would be the wrong list, on request"
    )
