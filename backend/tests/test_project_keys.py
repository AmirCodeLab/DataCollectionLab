"""Project recipient keys (encryption envelope §4.1, §4.3).

The load-bearing property is negative: there is no way to give the server a
private key. It generates no keypairs, and the create model forbids unknown
fields, so a client that sends a private half — under any name — is refused
rather than quietly obliged.

The db-marked tests run the real endpoints against a scratch database, like the
other API suites. They skip when Postgres is unreachable.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from pydantic import ValidationError

from app.modules.crypto.envelope import is_usable_recipient_key
from app.modules.projects.schemas import ProjectKeyCreate

KEYS_DB = "dcp_test_keys"
PROJECT_ID = "01PROJKEYS"
ARCHIVED_PROJECT_ID = "01PROJARCHIVED"


def _public_hex() -> str:
    return X25519PrivateKey.generate().public_key().public_bytes_raw().hex()


# ---------------------------------------------------------------------------
# The create model — no database needed
# ---------------------------------------------------------------------------


def test_a_private_key_field_is_refused_under_any_name() -> None:
    """The whole point of the mode, enforced at the request boundary.

    An X25519 private key is 32 bytes and so is a public key, so no server can
    tell them apart by looking. The guarantee has to be structural: nothing but
    these three fields is accepted, so a private key cannot arrive at all —
    not even to be ignored, which would still put it in a request log.
    """
    valid = {"publicKey": _public_hex(), "role": "primary", "label": "Programme lead"}
    ProjectKeyCreate.model_validate(valid)

    for smuggled in ("privateKey", "private_key", "secretKey", "d", "seed", "keyPair"):
        with pytest.raises(ValidationError) as refusal:
            ProjectKeyCreate.model_validate({**valid, smuggled: _public_hex()})
        assert "extra_forbidden" in str(refusal.value)


def test_a_key_container_is_refused_rather_than_parsed() -> None:
    """PEM, JWK and OpenSSH blobs can all carry a private key.

    A server that unwrapped one to "find the public part" would be parsing a
    secret it must never receive. Refuse the containers; take raw hex only.
    """
    containers = [
        "-----BEGIN PRIVATE KEY-----\nMC4CAQAwBQYDK2VuBCIEIA==\n-----END PRIVATE KEY-----",
        '{"kty":"OKP","crv":"X25519","d":"aaa","x":"bbb"}',
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI",
        "-----BEGIN PUBLIC KEY-----",
    ]
    for container in containers:
        with pytest.raises(ValidationError):
            ProjectKeyCreate.model_validate(
                {"publicKey": container, "role": "primary", "label": "x"}
            )


def test_the_public_key_must_be_thirty_two_bytes_of_hex() -> None:
    for bad in ("", "zz" * 32, _public_hex()[:-2], _public_hex() + "00"):
        with pytest.raises(ValidationError):
            ProjectKeyCreate.model_validate(
                {"publicKey": bad, "role": "primary", "label": "x"}
            )


def test_the_role_is_closed_and_the_label_is_required() -> None:
    """A recipient with no label is a private key nobody can attribute in a year."""
    with pytest.raises(ValidationError):
        ProjectKeyCreate.model_validate(
            {"publicKey": _public_hex(), "role": "escrow", "label": "x"}
        )
    with pytest.raises(ValidationError):
        ProjectKeyCreate.model_validate(
            {"publicKey": _public_hex(), "role": "primary", "label": ""}
        )


def test_small_order_points_are_not_usable_recipients() -> None:
    """They drive every exchange to an all-zero secret (envelope §2).

    A content key wrapped to one is wrapped under a key anybody can derive,
    while the console shows a recipient like any other.
    """
    degenerate = [
        "00" * 32,
        "01" + "00" * 31,
        "e0eb7a7c3b41b8ae1656e3faf19fc46ada098deb9c32b1fd866205165f49b800",
        "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f",
    ]
    for hexed in degenerate:
        assert not is_usable_recipient_key(bytes.fromhex(hexed)), hexed
    assert is_usable_recipient_key(bytes.fromhex(_public_hex()))


# ---------------------------------------------------------------------------
# Live tests against the real endpoints
# ---------------------------------------------------------------------------


def _admin_dsn() -> str:
    from app.core.config import get_settings

    return get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")


def _keys_db_url() -> str:
    parts = urlsplit(_admin_dsn())
    return urlunsplit(parts._replace(scheme="postgresql+asyncpg", path=f"/{KEYS_DB}"))


async def _seed() -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.modules.projects.models import Project

    engine = create_async_engine(_keys_db_url())
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            session.add(
                Project(
                    id=PROJECT_ID,
                    name="Key Study",
                    slug="key-study",
                    security_mode="project_e2e",
                )
            )
            session.add(
                Project(
                    id=ARCHIVED_PROJECT_ID,
                    name="Finished Study",
                    slug="finished-study",
                    security_mode="project_e2e",
                    archived_at=datetime(2026, 1, 1, tzinfo=UTC),
                )
            )
    finally:
        await engine.dispose()


async def _make_project(project_id: str, security_mode: str) -> None:
    """A project of its own for a test that counts a project's active keys.

    The shared PROJECT_ID accumulates keys from every test in the module, so
    "this is the last recipient" can only be arranged in a project nothing else
    touches.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.modules.projects.models import Project

    engine = create_async_engine(_keys_db_url())
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            session.add(
                Project(
                    id=project_id,
                    name=project_id,
                    slug=project_id.lower(),
                    security_mode=security_mode,
                )
            )
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def keys_api() -> Any:
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
            await conn.execute(f"DROP DATABASE IF EXISTS {KEYS_DB} WITH (FORCE)")
            await conn.execute(f"CREATE DATABASE {KEYS_DB}")
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
    cfg.set_main_option("sqlalchemy.url", _keys_db_url())
    command.upgrade(cfg, "head")
    asyncio.run(_seed())

    from app.api.deps import get_db
    from app.main import app

    async def scratch_db() -> AsyncIterator[Any]:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        engine = create_async_engine(_keys_db_url())
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
            await conn.execute(f"DROP DATABASE IF EXISTS {KEYS_DB} WITH (FORCE)")
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


@pytest.mark.db
def test_a_project_holds_primary_backup_and_recovery_keys(keys_api: Any) -> None:
    """Multi-recipient wrapping is in v0.1 because a lost key is unrecoverable data.

    §4.3: the answer to a lost private key is not a server-side escrow — that
    reintroduces the trust the mode removes — but more than one recipient.
    """
    recipients = [
        (_public_hex(), "primary", "Programme lead — Fatima"),
        (_public_hex(), "backup", "Deputy — Samuel"),
        (_public_hex(), "recovery", "Ethics board escrow"),
    ]

    async def scenario(client: Any) -> None:
        for public_key, role, label in recipients:
            response = await client.post(
                f"/api/v1/projects/{PROJECT_ID}/keys",
                json={"publicKey": public_key, "role": role, "label": label},
            )
            assert response.status_code == 201, response.text
            body = response.json()
            assert body["publicKey"] == public_key
            assert body["role"] == role
            assert body["revokedAt"] is None

        listed = await client.get(f"/api/v1/projects/{PROJECT_ID}/keys")
        assert listed.status_code == 200, listed.text
        assert listed.json()["securityMode"] == "project_e2e"
        assert [k["role"] for k in listed.json()["keys"]] == ["primary", "backup", "recovery"]

        # The device-facing endpoint offers the same set to wrap to.
        await client.post(
            "/api/v1/devices", json={"deviceId": "dev-keys", "platform": "android"}
        )
        crypto = await client.get("/api/v1/devices/dev-keys/crypto")
        assert crypto.status_code == 200, crypto.text
        assert {k["publicKey"] for k in crypto.json()["projectKeys"]} == {
            public_key for public_key, _, _ in recipients
        }

        # And the project list shows the count that decides whether devices can
        # push at all.
        projects = (await client.get("/api/v1/projects")).json()["projects"]
        assert next(p for p in projects if p["id"] == PROJECT_ID)["activeKeyCount"] == 3

    _run_with_client(keys_api, scenario)


@pytest.mark.db
def test_the_same_public_key_twice_is_not_two_recipients(keys_api: Any) -> None:
    """Otherwise a project shows three holders and one lost laptop loses everything."""
    duplicated = _public_hex()

    async def scenario(client: Any) -> None:
        first = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/keys",
            json={"publicKey": duplicated, "role": "primary", "label": "Lead"},
        )
        assert first.status_code == 201, first.text

        again = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/keys",
            json={"publicKey": duplicated, "role": "backup", "label": "Deputy"},
        )
        assert again.status_code == 409, again.text
        assert again.json()["detail"]["reason"] == "duplicate_public_key"

    _run_with_client(keys_api, scenario)


@pytest.mark.db
def test_the_api_refuses_what_the_model_refuses(keys_api: Any) -> None:
    """The rejections reach the wire as 422s, not as silently dropped fields."""

    async def scenario(client: Any) -> None:
        private = X25519PrivateKey.generate()
        smuggled = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/keys",
            json={
                "publicKey": private.public_key().public_bytes_raw().hex(),
                "role": "primary",
                "label": "Lead",
                "privateKey": private.private_bytes_raw().hex(),
            },
        )
        assert smuggled.status_code == 422, smuggled.text
        assert "privateKey" in smuggled.text

        degenerate = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/keys",
            json={"publicKey": "00" * 32, "role": "primary", "label": "Lead"},
        )
        assert degenerate.status_code == 422, degenerate.text
        assert degenerate.json()["detail"]["reason"] == "degenerate_public_key"

        missing = await client.post(
            "/api/v1/projects/01NOSUCHPROJECT/keys",
            json={"publicKey": _public_hex(), "role": "primary", "label": "Lead"},
        )
        assert missing.status_code == 404, missing.text

        archived = await client.post(
            f"/api/v1/projects/{ARCHIVED_PROJECT_ID}/keys",
            json={"publicKey": _public_hex(), "role": "primary", "label": "Lead"},
        )
        assert archived.status_code == 409, archived.text
        assert archived.json()["detail"]["reason"] == "project_archived"

    _run_with_client(keys_api, scenario)


@pytest.mark.db
def test_a_published_test_key_is_refused_outside_development(
    keys_api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The private half of this key is in the repository (§4.1, and docs/project-conventions.md rule 5).

    Registering it as a recipient would wrap every future submission to a key
    anyone with a clone can open, while the console lists it as a recipient like
    any other. The environment is the only thing that separates a useful
    development fixture from that, so it is the thing the server checks.
    """
    from app.modules.crypto.published_test_keys import PUBLISHED_TEST_PUBLIC_KEYS
    from app.modules.projects import service

    published = sorted(PUBLISHED_TEST_PUBLIC_KEYS)[0]

    def production_settings() -> Any:
        return SimpleNamespace(environment="production")

    async def scenario(client: Any) -> None:
        monkeypatch.setattr(service, "get_settings", production_settings)

        refused = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/keys",
            json={"publicKey": published, "role": "primary", "label": "Programme lead"},
        )
        assert refused.status_code == 422, refused.text
        assert refused.json()["detail"]["reason"] == "test_only_key"
        assert "dev_project_key.py" in refused.json()["detail"]["message"]

        # A fresh key announced as a test key is refused on its label alone.
        labelled = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/keys",
            json={"publicKey": _public_hex(), "role": "backup", "label": "TEST ONLY — rehearsal"},
        )
        assert labelled.status_code == 422, labelled.text
        assert labelled.json()["detail"]["reason"] == "test_only_key"

        # Neither reached the database: a refusal is not a write.
        listed = (await client.get(f"/api/v1/projects/{PROJECT_ID}/keys")).json()
        assert published not in [key["publicKey"] for key in listed["keys"]]
        assert "TEST ONLY — rehearsal" not in [key["label"] for key in listed["keys"]]

        # And in development it is exactly what it is for.
        monkeypatch.setattr(
            service, "get_settings", lambda: SimpleNamespace(environment="development")
        )
        allowed = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/keys",
            json={
                "publicKey": published,
                "role": "recovery",
                "label": "TEST ONLY — scripts/dev_project_key.py (primary)",
            },
        )
        assert allowed.status_code == 201, allowed.text

        # With that key now installed, a device asking what to wrap to gets a
        # refusal rather than a recipient set it must not use. This is the case
        # a registration check alone cannot catch: the key arrived in
        # development and the deployment was promoted afterwards.
        await client.post(
            "/api/v1/devices", json={"deviceId": "dev-promoted", "platform": "android"}
        )
        monkeypatch.setattr(service, "get_settings", production_settings)
        crypto = await client.get("/api/v1/devices/dev-promoted/crypto")
        assert crypto.status_code == 409, crypto.text
        assert crypto.json()["detail"]["reason"] == "test_only_key"
        # Naming the key is the point: someone has to go and revoke it.
        assert published[:16] in crypto.text or "TEST ONLY" in crypto.text

    _run_with_client(keys_api, scenario)


@pytest.mark.db
def test_no_endpoint_hands_back_key_material_that_could_decrypt(keys_api: Any) -> None:
    """A grep of the whole API surface for a private key that never entered it.

    The server generates no keypairs and stores no private halves; this asserts
    the shape of that, so an endpoint added later that starts returning one
    fails here rather than in an incident.
    """

    async def scenario(client: Any) -> None:
        private = X25519PrivateKey.generate()
        public_hex = private.public_key().public_bytes_raw().hex()
        await client.post(
            f"/api/v1/projects/{PROJECT_ID}/keys",
            json={"publicKey": public_hex, "role": "recovery", "label": "Escrow"},
        )

        bodies = [
            (await client.get("/api/v1/projects")).text,
            (await client.get(f"/api/v1/projects/{PROJECT_ID}/keys")).text,
            (await client.get(f"/api/v1/projects/{PROJECT_ID}/keys?includeRevoked=true")).text,
        ]
        for body in bodies:
            assert private.private_bytes_raw().hex() not in body
            assert "privateKey" not in body
            assert "private_key" not in body
        # The public half is returned, and is meant to be: it is what a device
        # wraps to, and it is useless on its own.
        assert public_hex in bodies[1]

    _run_with_client(keys_api, scenario)


# ---------------------------------------------------------------------------
# Revocation (encryption envelope §8)
# ---------------------------------------------------------------------------


@pytest.mark.db
def test_a_revoked_key_stops_receiving_wraps_but_keeps_opening_what_it_has(
    keys_api: Any,
) -> None:
    """Revocation is about the future, and only about the future.

    A retired key must disappear from what devices wrap to. It must NOT
    disappear from the record: the submissions collected while it was active
    are encrypted to it permanently — the server cannot re-wrap them because it
    cannot open them — so the console still has to be able to name it when it
    tells someone which private key opens an old submission.
    """
    retiring = _public_hex()
    staying = _public_hex()

    async def scenario(client: Any) -> None:
        created = []
        for public_key, role, label in (
            (retiring, "primary", "Leaving — Priya"),
            (staying, "backup", "Staying — Omar"),
        ):
            response = await client.post(
                f"/api/v1/projects/{PROJECT_ID}/keys",
                json={"publicKey": public_key, "role": role, "label": label},
            )
            assert response.status_code == 201, response.text
            created.append(response.json()["keyId"])
        leaving, remaining = created

        revoked = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/keys/{leaving}/revoke"
        )
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["revokedAt"] is not None
        stamp = revoked.json()["revokedAt"]

        # Gone from the default listing and from what devices wrap to...
        active = (await client.get(f"/api/v1/projects/{PROJECT_ID}/keys")).json()["keys"]
        assert leaving not in [k["keyId"] for k in active]
        assert remaining in [k["keyId"] for k in active]

        await client.post(
            "/api/v1/devices", json={"deviceId": "dev-revoke", "platform": "android"}
        )
        crypto = await client.get("/api/v1/devices/dev-revoke/crypto")
        assert crypto.status_code == 200, crypto.text
        assert retiring not in {k["publicKey"] for k in crypto.json()["projectKeys"]}
        assert staying in {k["publicKey"] for k in crypto.json()["projectKeys"]}

        # ...and still there, named, for anyone holding an old submission.
        including = (
            await client.get(
                f"/api/v1/projects/{PROJECT_ID}/keys", params={"includeRevoked": True}
            )
        ).json()["keys"]
        retired = next(k for k in including if k["keyId"] == leaving)
        assert retired["revokedAt"] == stamp
        assert retired["publicKey"] == retiring
        assert retired["label"] == "Leaving — Priya"

        # Idempotent: a retry does not move when the revocation happened.
        again = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/keys/{leaving}/revoke"
        )
        assert again.status_code == 200, again.text
        assert again.json()["revokedAt"] == stamp

    _run_with_client(keys_api, scenario)


@pytest.mark.db
def test_the_last_recipient_of_an_encrypting_project_cannot_be_revoked(
    keys_api: Any,
) -> None:
    """Otherwise collection stops in the field and nobody is told.

    A project in an encrypting mode with no recipients cannot receive data at
    all — its devices hold everything locally rather than send answers in the
    clear. The refusal names the fix, and the fix leaves the same end state.
    """
    sole = _public_hex()
    replacement = _public_hex()

    async def scenario(client: Any) -> None:
        # A project of its own, so the count is unambiguous.
        project_id = "01PROJLASTKEY"
        await _make_project(project_id, "project_e2e")

        first = await client.post(
            f"/api/v1/projects/{project_id}/keys",
            json={"publicKey": sole, "role": "primary", "label": "Only holder"},
        )
        assert first.status_code == 201, first.text
        only_key = first.json()["keyId"]

        refused = await client.post(
            f"/api/v1/projects/{project_id}/keys/{only_key}/revoke"
        )
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"]["reason"] == "last_active_key"

        # Register the replacement first, exactly as the message says, and the
        # same revocation goes through.
        second = await client.post(
            f"/api/v1/projects/{project_id}/keys",
            json={"publicKey": replacement, "role": "primary", "label": "New holder"},
        )
        assert second.status_code == 201, second.text

        now_allowed = await client.post(
            f"/api/v1/projects/{project_id}/keys/{only_key}/revoke"
        )
        assert now_allowed.status_code == 200, now_allowed.text
        assert now_allowed.json()["revokedAt"] is not None

    _run_with_client(keys_api, scenario)


@pytest.mark.db
def test_revoking_something_that_is_not_there_says_which_thing(keys_api: Any) -> None:
    """A 404 with no reason leaves you guessing which id was wrong."""

    async def scenario(client: Any) -> None:
        missing_key = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/keys/01NOSUCHKEY/revoke"
        )
        assert missing_key.status_code == 404, missing_key.text
        assert missing_key.json()["detail"]["reason"] == "key_not_found"

        missing_project = await client.post(
            "/api/v1/projects/01NOSUCHPROJECT/keys/01NOSUCHKEY/revoke"
        )
        assert missing_project.status_code == 404, missing_project.text
        assert missing_project.json()["detail"]["reason"] == "project_not_found"

    _run_with_client(keys_api, scenario)
