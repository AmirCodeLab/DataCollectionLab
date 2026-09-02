"""The server compiles a submission's own form version, never the newest.

Form IR §9 binds a submission to the version it was collected under, and §6.3
made that binding load-bearing: now that a choice value is validated against its
list, a value that was in v1's list and was removed in v2 is still correct for a
submission collected under v1.

Getting that backwards is worse than not checking at all. Not checking admits a
bad answer; checking against the wrong version **rejects a good one** — data
that was right when it was collected, destroyed by a later edit to the form. It
would surface months afterwards as "the server is losing our data", by which
time the submissions are gone and nobody would connect it to a choice list
somebody tidied up.

The client made this unexpressible with `FormCatalog.compiledFormForSubmission`
(break 30): the ViewModel stopped being able to get it wrong by having nothing
to pass. `forms.service.compiled_form_for_submission` is the same move on the
server — one function, a submission id, no version parameter — written before
the §6.4 enforcement that will use it, so there is no moment where the wrong
form is the easy one to reach for.

These are `db`-marked: they need a real database, because the binding *is* the
join from submission to form version.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pytest

pytestmark = pytest.mark.db

BINDING_DB = "dcp_test_version_binding"

PROJECT_ID = "01PROJBIND"
ENVIRONMENT_ID = "01ENVBIND"
DEVICE_ID = "dev_binding"
USER_ID = "usr_binding"


def _roster_ir(version: int, members: list[str]) -> dict[str, Any]:
    """A one-question form whose choice list shrinks between versions."""
    return {
        "irVersion": "0.1",
        "formId": "roster",
        "version": version,
        "title": {"en": "Roster"},
        "defaultLanguage": "en",
        "languages": ["en"],
        "children": [
            {
                "type": "question",
                "id": "member",
                "dataType": "select_one",
                "label": {"en": "Member"},
                "choices": {
                    "kind": "inline",
                    "items": [{"value": m, "label": {"en": m.title()}} for m in members],
                },
            }
        ],
    }


def _database_url() -> str:
    from app.core.config import get_settings

    return get_settings().database_url


def _admin_dsn() -> str:
    parts = urlsplit(_database_url())
    return urlunsplit(parts._replace(scheme="postgresql", path="/postgres"))


def _binding_db_url() -> str:
    parts = urlsplit(_database_url())
    return urlunsplit(parts._replace(scheme="postgresql+asyncpg", path=f"/{BINDING_DB}"))


@pytest.fixture(scope="module")
def binding_db() -> Any:
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
            await conn.execute(f"DROP DATABASE IF EXISTS {BINDING_DB} WITH (FORCE)")
            await conn.execute(f"CREATE DATABASE {BINDING_DB}")
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
    cfg.set_main_option("sqlalchemy.url", _binding_db_url())
    command.upgrade(cfg, "head")
    return _binding_db_url()


async def _session(url: str) -> AsyncIterator[Any]:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(url, future=True)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _seed(url: str) -> tuple[str, str]:
    """Publish roster v1 (with carol) and v2 (without), and pin a submission to each.

    Uses the ORM models rather than hand-written INSERTs, for the same reason
    `test_form_delivery` does: the tables have required columns this test does
    not care about, and spelling them out here would be a second copy of the
    schema that goes stale.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.modules.forms import service as forms_service
    from app.modules.projects.models import Device, Environment, Project
    from app.modules.submissions.models import Submission

    engine = create_async_engine(url)
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            session.add(Project(id=PROJECT_ID, name="Binding", slug="binding"))
            await session.flush()
            session.add(Environment(id=ENVIRONMENT_ID, project_id=PROJECT_ID, kind="production"))
            session.add(
                Device(id=DEVICE_ID, project_id=PROJECT_ID, user_id=USER_ID, platform="android")
            )
            await session.flush()

            v1 = await forms_service.publish_version(
                session, project_id=PROJECT_ID, ir=_roster_ir(1, ["alice", "bob", "carol"])
            )
            v2 = await forms_service.publish_version(
                session, project_id=PROJECT_ID, ir=_roster_ir(2, ["alice", "bob"])
            )
            await session.flush()

            for submission_id, version_id in (("sub_on_v1", v1.id), ("sub_on_v2", v2.id)):
                session.add(
                    Submission(
                        id=submission_id,
                        project_id=PROJECT_ID,
                        environment_id=ENVIRONMENT_ID,
                        form_version_id=version_id,
                        origin_device_id=DEVICE_ID,
                        created_by=USER_ID,
                        status="draft",
                    )
                )
    finally:
        await engine.dispose()
    return "sub_on_v1", "sub_on_v2"


def test_a_v1_answer_is_accepted_where_v2_would_reject_it(binding_db: str) -> None:
    """The whole point, in one assertion pair.

    `carol` was a choice in v1 and is not in v2. A submission collected under v1
    must still validate her as a member; one collected under v2 must not. If the
    server compiled the newest version it would reject the first — data that was
    correct when collected.
    """
    from app.modules.form_engine.runtime import FormInstance
    from app.modules.forms.service import compiled_form_for_submission

    async def run() -> tuple[bool, bool]:
        on_v1, on_v2 = await _seed(binding_db)
        results = []
        async for session in _session(binding_db):
            for submission_id in (on_v1, on_v2):
                compiled = await compiled_form_for_submission(session, submission_id)
                assert compiled is not None, f"{submission_id} resolved to no form"
                instance = FormInstance(compiled, today="2026-09-03")
                instance.set("member", "carol")
                instance.recalculate()
                results.append(instance.states["member"].valid)
            break
        return results[0], results[1]

    v1_valid, v2_valid = asyncio.run(run())

    assert v1_valid, (
        "a submission collected under v1 must still accept `carol`. Rejecting it "
        "would destroy an answer that was correct when it was given."
    )
    assert not v2_valid, (
        "a submission collected under v2 must reject `carol` — if both versions "
        "agreed, binding to the wrong one would be undetectable"
    )


def test_the_resolver_offers_no_way_to_ask_for_a_different_version() -> None:
    """Made unexpressible, not tested for.

    The client's equivalent (`FormCatalog.compiledFormForSubmission`, break 30)
    removed the choice rather than testing it, because a test only catches the
    instance somebody wrote. This asserts the shape that makes the mistake
    impossible: one function, a submission id, and nothing that names a version.
    """
    import inspect

    from app.modules.forms.service import compiled_form_for_submission

    parameters = list(inspect.signature(compiled_form_for_submission).parameters)
    assert parameters == ["session", "submission_id"], (
        f"the signature is {parameters}. A version parameter here is the whole "
        "mistake: it lets a caller ask for the wrong form, which is what break 30 "
        "removed on the client."
    )


def test_an_unknown_submission_resolves_to_nothing_rather_than_something(
    binding_db: str,
) -> None:
    """No fallback to the latest version.

    A fallback here would be the shape of break 27's tempting mistake — "answer
    with something rather than nothing" — and it would validate one submission's
    answers against another's form.
    """
    from app.modules.forms.service import compiled_form_for_submission

    async def run() -> Any:
        async for session in _session(binding_db):
            return await compiled_form_for_submission(session, "sub_that_does_not_exist")
        raise AssertionError("unreachable")

    assert asyncio.run(run()) is None
