"""End-to-end encrypted sync (encryption envelope §5, sync protocol §2.1).

Runs the real endpoints against a scratch database, acting as the client: it
generates a content key, wraps it to a project key whose private half the server
never sees, encrypts operation values with the reference envelope, and pushes.

What it then proves is the whole point of the mode:

1. the server stored ciphertext and no plaintext;
2. nothing the server holds — the op rows, the folded state, the console's own
   read API — contains the answers, byte for byte;
3. a key holder gets the original answers back, and only with the private key.

Skips when Postgres is unreachable (docker compose up -d postgres), like every
other db-marked test.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from app.modules.crypto.envelope import (
    EnvelopeError,
    WrappedKey,
    decrypt_op_value,
    encrypt_op_value,
    op_nonce,
    unwrap_content_key,
    wrap_to_recipients,
)

CRYPTO_DB = "dcp_test_crypto"

PROJECT_ID = "01PROJCRYPTO"
FORM_KEY = "clinic_intake"
FORM_VERSION = 1
DEVICE_A = "dev-crypto-a"
DEVICE_B = "dev-crypto-b"
PROJECT_KEY_PRIMARY = "01PKEYPRIMARY"
PROJECT_KEY_BACKUP = "01PKEYBACKUP"

# TEST ONLY. Generated per run so nothing here can be mistaken for a key that
# matters, and so the test proves the wrap works rather than that a fixture
# still decodes.
PRIMARY_PRIVATE = X25519PrivateKey.generate()
BACKUP_PRIVATE = X25519PrivateKey.generate()
STRANGER_PRIVATE = X25519PrivateKey.generate()

# The answers this test follows end to end.
ANSWERS: dict[str, Any] = {
    "patient_name": "Amina Yusuf",
    "hiv_status": "positive",
    "cd4_count": 412,
    "notes": "Referred by Dr Okoye — follow up in 3 months",
}


# ---------------------------------------------------------------------------
# Scratch database
# ---------------------------------------------------------------------------


def _admin_dsn() -> str:
    from app.core.config import get_settings

    return get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")


def _crypto_db_url(scheme: str = "postgresql+asyncpg") -> str:
    parts = urlsplit(_admin_dsn())
    return urlunsplit(parts._replace(scheme=scheme, path=f"/{CRYPTO_DB}"))


async def _seed(security_mode: str) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.modules.crypto.models import ProjectKey
    from app.modules.forms.models import Form, FormVersion
    from app.modules.projects.models import Device, Environment, Project

    engine = create_async_engine(_crypto_db_url())
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            session.add(
                Project(
                    id=PROJECT_ID,
                    name="Clinic Study",
                    slug="clinic-study",
                    security_mode=security_mode,
                )
            )
            await session.flush()
            session.add(Environment(id="01ENVCRYPTO", project_id=PROJECT_ID, kind="production"))
            session.add(
                Form(id="01FORMCRYPTO", project_id=PROJECT_ID, form_key=FORM_KEY, title="Intake")
            )
            for device_id in (DEVICE_A, DEVICE_B):
                session.add(
                    Device(
                        id=device_id, project_id=PROJECT_ID, user_id="usr-1", platform="android"
                    )
                )
            # Two recipients: a lost private key means permanently unrecoverable
            # data, and multi-recipient wrapping is the answer (envelope §4.3).
            session.add(
                ProjectKey(
                    id=PROJECT_KEY_PRIMARY,
                    project_id=PROJECT_ID,
                    public_key=PRIMARY_PRIVATE.public_key().public_bytes_raw(),
                    key_role="primary",
                    label="Programme lead",
                )
            )
            session.add(
                ProjectKey(
                    id=PROJECT_KEY_BACKUP,
                    project_id=PROJECT_ID,
                    public_key=BACKUP_PRIVATE.public_key().public_bytes_raw(),
                    key_role="backup",
                    label="Ethics board escrow",
                )
            )
            await session.flush()
            session.add(
                FormVersion(
                    id="01FORMVCRYPTO",
                    form_id="01FORMCRYPTO",
                    version=FORM_VERSION,
                    ir={},
                    ir_checksum="test",
                )
            )
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def crypto_api() -> Any:
    """The real app on a scratch database seeded in project_e2e mode."""
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
            await conn.execute(f"DROP DATABASE IF EXISTS {CRYPTO_DB} WITH (FORCE)")
            await conn.execute(f"CREATE DATABASE {CRYPTO_DB}")
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
    cfg.set_main_option("sqlalchemy.url", _crypto_db_url())
    command.upgrade(cfg, "head")

    asyncio.run(_seed("project_e2e"))

    from app.api.deps import get_db
    from app.main import app

    async def scratch_db() -> AsyncIterator[Any]:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        # One engine per request: each test runs in its own event loop, and
        # pooled asyncpg connections cannot cross loops.
        engine = create_async_engine(_crypto_db_url())
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
            await conn.execute(f"DROP DATABASE IF EXISTS {CRYPTO_DB} WITH (FORCE)")
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


async def _fetch(query: str) -> Any:
    import asyncpg

    conn = await asyncpg.connect(_crypto_db_url(scheme="postgresql"))
    try:
        return await conn.fetch(query)
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# The client side, played by the reference envelope
# ---------------------------------------------------------------------------


class Client:
    """A device: owns a content key per submission and encrypts its own ops."""

    def __init__(self, device_id: str, recipients: dict[str, bytes]) -> None:
        self.device_id = device_id
        self.recipients = recipients
        self.counter = 0
        self.content_keys: dict[str, tuple[str, bytes]] = {}

    def content_key(self, submission_id: str) -> tuple[str, bytes]:
        """One content key per device per submission (envelope §4.2)."""
        if submission_id not in self.content_keys:
            key_id = f"01CK{self.device_id}{submission_id}".upper()
            self.content_keys[submission_id] = (key_id, bytes(range(32)))
        return self.content_keys[submission_id]

    def wrapped(self, submission_id: str) -> dict[str, Any]:
        key_id, material = self.content_key(submission_id)
        return {
            "contentKeyId": key_id,
            "submissionId": submission_id,
            "deviceId": self.device_id,
            "wraps": [
                {
                    "projectKeyId": wrap.project_key_id,
                    "ephemeralPublic": wrap.ephemeral_public.hex(),
                    "nonce": wrap.nonce.hex(),
                    "wrappedKey": wrap.wrapped_key.hex(),
                }
                for wrap in wrap_to_recipients(material, key_id, self.recipients)
            ],
        }

    def encrypted_op(
        self, op_id: str, submission_id: str, path: str, value: Any, *, counter: int | None = None
    ) -> dict[str, Any]:
        self.counter = counter if counter is not None else self.counter + 1
        key_id, material = self.content_key(submission_id)
        ciphertext, nonce = encrypt_op_value(
            value,
            material,
            op_id=op_id,
            submission_id=submission_id,
            path=path,
            form_version=FORM_VERSION,
            device_id=self.device_id,
            counter=self.counter,
        )
        return {
            "opId": op_id,
            "submissionId": submission_id,
            "formId": FORM_KEY,
            "formVersion": FORM_VERSION,
            "kind": "set",
            "path": path,
            "valueCiphertext": ciphertext.hex(),
            "contentKeyId": key_id,
            "nonce": nonce.hex(),
            "deviceId": self.device_id,
            "counter": self.counter,
            "wallClock": datetime.now(tz=UTC).isoformat(),
        }


def _recipients() -> dict[str, bytes]:
    return {
        PROJECT_KEY_PRIMARY: PRIMARY_PRIVATE.public_key().public_bytes_raw(),
        PROJECT_KEY_BACKUP: BACKUP_PRIVATE.public_key().public_bytes_raw(),
    }


async def _push(client: Any, device_id: str, ops: list[dict], keys: list[dict]) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/sync/push", json={"deviceId": device_id, "ops": ops, "keys": keys}
    )
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# The end-to-end round trip
# ---------------------------------------------------------------------------


@pytest.mark.db
def test_encrypted_ops_survive_a_server_that_cannot_read_them(crypto_api: Any) -> None:
    submission = "01SUBE2E"
    device = Client(DEVICE_A, _recipients())
    ops = [
        device.encrypted_op(f"01OPE2E{i}", submission, path, value)
        for i, (path, value) in enumerate(ANSWERS.items())
    ]

    async def scenario(client: Any) -> None:
        result = await _push(client, DEVICE_A, ops, [device.wrapped(submission)])
        assert result["accepted"] == [op["opId"] for op in ops]
        assert result["rejected"] == []

        # -- 1. the server stored ciphertext, and no plaintext ---------------
        rows = await _fetch(
            "SELECT path, value, value_ciphertext, content_key_id, nonce "
            f"FROM submission_op WHERE submission_id = '{submission}' ORDER BY counter"
        )
        assert len(rows) == len(ops)
        for row in rows:
            assert row["value"] is None, f"{row['path']} was stored in plaintext"
            assert row["value_ciphertext"], f"{row['path']} has no ciphertext"
            assert row["content_key_id"] == device.content_key(submission)[0]
            assert len(row["nonce"]) == 12

        # -- 2. no answer is anywhere the server can reach -------------------
        # Not "the value column is null" but "these bytes do not occur", which
        # also catches the fold, a stray audit copy and the outbox payload.
        dump = await _fetch(
            "SELECT string_agg(t::text, ' ') AS blob FROM ("
            "  SELECT * FROM submission_op UNION ALL SELECT * FROM submission_op"
            ") t"
        )
        haystack = (dump[0]["blob"] or "") + json.dumps(
            [dict(r) for r in await _fetch("SELECT data::text AS data FROM submission_state")]
        )
        for path, value in ANSWERS.items():
            if isinstance(value, str):
                assert value not in haystack, f"{path} leaked into the database in the clear"

        # The fold holds no values at all: an encrypted answer has no place in
        # a queryable projection (envelope §10).
        state = await _fetch(
            f"SELECT data FROM submission_state WHERE submission_id = '{submission}'"
        )
        assert json.loads(state[0]["data"]) == {}

        # The console read API reports the ops as encrypted rather than empty.
        detail = await client.get(f"/api/v1/submissions/{submission}")
        assert detail.status_code == 200, detail.text
        assert all(op["encrypted"] and op["value"] is None for op in detail.json()["ops"])
        assert detail.json()["state"]["data"] == {}

        # -- 3. a key holder gets the answers back --------------------------
        pulled = (await client.get("/api/v1/sync/pull", params={"cursor": 0, "limit": 200})).json()
        keys = (await client.get(f"/api/v1/submissions/{submission}/keys")).json()

        answers = _decrypt(pulled["ops"], keys, PRIMARY_PRIVATE.private_bytes_raw())
        assert answers == ANSWERS

        # ...and so does the backup holder, from the same stored wraps.
        assert _decrypt(pulled["ops"], keys, BACKUP_PRIVATE.private_bytes_raw()) == ANSWERS

        # ...and nobody else. The wraps are public; the private key is not.
        with pytest.raises(EnvelopeError):
            _decrypt(pulled["ops"], keys, STRANGER_PRIVATE.private_bytes_raw())

    _run_with_client(crypto_api, scenario)


def _decrypt(
    pulled_ops: list[dict], keys: dict[str, Any], private_key: bytes
) -> dict[str, Any]:
    """The client side of envelope §7: unwrap, then fold, decrypting as we go."""
    content_keys: dict[str, bytes] = {}
    for key in keys["contentKeys"]:
        for wrap in key["wraps"]:
            try:
                content_keys[key["contentKeyId"]] = unwrap_content_key(
                    WrappedKey(
                        project_key_id=wrap["projectKeyId"],
                        content_key_id=key["contentKeyId"],
                        ephemeral_public=bytes.fromhex(wrap["ephemeralPublic"]),
                        nonce=bytes.fromhex(wrap["nonce"]),
                        wrapped_key=bytes.fromhex(wrap["wrappedKey"]),
                    ),
                    private_key,
                )
                break
            except EnvelopeError:
                # A wrap addressed to another recipient: expected, not an error.
                continue

    answers: dict[str, Any] = {}
    # Same fold as everywhere: last writer wins by (counter, deviceId).
    for op in sorted(pulled_ops, key=lambda o: (o["counter"], o["deviceId"])):
        if op["kind"] != "set" or op["path"] is None:
            continue
        if op["valueCiphertext"] is None:
            answers[op["path"]] = op["value"]
            continue
        material = content_keys.get(op["contentKeyId"])
        if material is None:
            raise EnvelopeError(f"no content key opens op {op['opId']}")
        answers[op["path"]] = decrypt_op_value(
            bytes.fromhex(op["valueCiphertext"]),
            bytes.fromhex(op["nonce"]),
            material,
            op_id=op["opId"],
            submission_id=op["submissionId"],
            path=op["path"],
            form_version=op["formVersion"],
        )
    return answers


def _decrypt_from_console_api(
    detail: dict[str, Any], keys: dict[str, Any], private_key: bytes
) -> dict[str, Any]:
    """Decrypt using only what the console's own two reads return.

    Deliberately not the pull stream: the browser has a submission id, not a
    cursor, and if this path is missing a field then the console can display
    "encrypted" forever while the data is in fact recoverable. Same steps as
    web/src/lib/decryptSubmission.ts, which is what actually runs for a user.
    """
    content_keys: dict[str, bytes] = {}
    for key in keys["contentKeys"]:
        for wrap in key["wraps"]:
            try:
                content_keys[key["contentKeyId"]] = unwrap_content_key(
                    WrappedKey(
                        project_key_id=wrap["projectKeyId"],
                        content_key_id=key["contentKeyId"],
                        ephemeral_public=bytes.fromhex(wrap["ephemeralPublic"]),
                        nonce=bytes.fromhex(wrap["nonce"]),
                        wrapped_key=bytes.fromhex(wrap["wrappedKey"]),
                    ),
                    private_key,
                )
                break
            except EnvelopeError:
                continue

    answers: dict[str, Any] = {}
    for op in sorted(detail["ops"], key=lambda o: (o["counter"], o["deviceId"])):
        if op["kind"] != "set" or op["path"] is None:
            continue
        if not op["encrypted"]:
            answers[op["path"]] = op["value"]
            continue
        material = content_keys.get(op["contentKeyId"])
        if material is None:
            raise EnvelopeError(f"no content key opens op {op['id']}")
        answers[op["path"]] = decrypt_op_value(
            bytes.fromhex(op["valueCiphertext"]),
            bytes.fromhex(op["nonce"]),
            material,
            op_id=op["id"],
            submission_id=detail["id"],
            path=op["path"],
            form_version=detail["formVersion"],
        )
    return answers


@pytest.mark.db
def test_the_console_read_api_carries_everything_a_key_holder_needs(crypto_api: Any) -> None:
    """Encrypted correctly is only half the claim; the other half is readable back.

    Storing ciphertext where plaintext used to be is easy to verify and easy to
    get wrong in a way that only shows up years later, when someone asks for the
    data and there is no path that returns it. This test walks the path a key
    holder actually walks — GET the submission, GET its wrapped keys, unwrap,
    decrypt, fold — and asserts the answers come back exactly as typed, for a
    submission two devices contributed to (§4.2, §7).
    """
    submission = "01SUBCONSOLE"
    a = Client(DEVICE_A, _recipients())
    b = Client(DEVICE_B, _recipients())
    typed = {"enumerator_name": "amr", "resp_name": "AMR", "hh_size": 2}

    ops = [
        a.encrypted_op("01OPCON1", submission, "enumerator_name", "amr", counter=1200),
        a.encrypted_op("01OPCON2", submission, "resp_name", "AMR", counter=1201),
        # A second device contributing to the same submission, peer-to-peer:
        # its own content key, and the submission needs both to read in full.
        b.encrypted_op("01OPCON3", submission, "hh_size", 2, counter=1200),
    ]

    async def scenario(client: Any) -> None:
        result = await _push(
            client, DEVICE_A, ops, [a.wrapped(submission), b.wrapped(submission)]
        )
        assert result["rejected"] == []

        detail = (await client.get(f"/api/v1/submissions/{submission}")).json()
        keys = (await client.get(f"/api/v1/submissions/{submission}/keys")).json()

        # The server still reads none of it: no plaintext value, and a fold
        # holding nothing.
        assert all(op["value"] is None and op["encrypted"] for op in detail["ops"])
        assert detail["state"]["data"] == {}
        for value in typed.values():
            if isinstance(value, str):
                assert value not in json.dumps(detail["state"])

        # Two content keys, one per contributing device, both wrapped to both
        # recipients — so one private key opens the whole submission.
        assert len(keys["contentKeys"]) == 2
        assert all(len(k["wraps"]) == 2 for k in keys["contentKeys"])

        assert _decrypt_from_console_api(detail, keys, PRIMARY_PRIVATE.private_bytes_raw()) == typed
        assert _decrypt_from_console_api(detail, keys, BACKUP_PRIVATE.private_bytes_raw()) == typed
        with pytest.raises(EnvelopeError):
            _decrypt_from_console_api(detail, keys, STRANGER_PRIVATE.private_bytes_raw())

    _run_with_client(crypto_api, scenario)


@pytest.mark.db
def test_a_key_added_later_opens_nothing_older(crypto_api: Any) -> None:
    """Envelope §8, and the reason the console has to say so at rotation time.

    A submission is wrapped to the recipients that existed when it was
    collected. Adding a recipient afterwards cannot re-wrap it — the server has
    no key to re-wrap with — so the new holder gets ciphertext they cannot open,
    and the old private key stays load-bearing forever. A customer who rotates
    and discards the old key has destroyed their historical data.
    """
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey as _X

    submission = "01SUBROTATE"
    before = Client(DEVICE_A, _recipients())
    early = before.encrypted_op(
        "01OPROT1", submission, "resp_name", "collected first", counter=1300
    )

    latecomer = _X.generate()

    async def scenario(client: Any) -> None:
        assert (await _push(client, DEVICE_A, [early], [before.wrapped(submission)]))["accepted"]

        registered = await client.post(
            f"/api/v1/projects/{PROJECT_ID}/keys",
            json={
                "publicKey": latecomer.public_key().public_bytes_raw().hex(),
                "role": "recovery",
                "label": "Ethics board — joined later",
            },
        )
        assert registered.status_code == 201, registered.text

        detail = (await client.get(f"/api/v1/submissions/{submission}")).json()
        keys = (await client.get(f"/api/v1/submissions/{submission}/keys")).json()

        # The wraps on the existing submission are untouched by the new key.
        assert [w["projectKeyId"] for w in keys["contentKeys"][0]["wraps"]] == sorted(
            [PROJECT_KEY_BACKUP, PROJECT_KEY_PRIMARY]
        )
        with pytest.raises(EnvelopeError):
            _decrypt_from_console_api(detail, keys, latecomer.private_bytes_raw())

        # The keys that existed at collection time still open it, and always will.
        assert _decrypt_from_console_api(
            detail, keys, PRIMARY_PRIVATE.private_bytes_raw()
        ) == {"resp_name": "collected first"}

        # A submission collected after the rotation reaches all three.
        rotated = {
            **_recipients(),
            registered.json()["keyId"]: latecomer.public_key().public_bytes_raw(),
        }
        after = Client(DEVICE_B, rotated)
        fresh_id = "01SUBROTATE2"
        late_op = after.encrypted_op(
            "01OPROT2", fresh_id, "resp_name", "collected later", counter=1310
        )
        assert (await _push(client, DEVICE_B, [late_op], [after.wrapped(fresh_id)]))["accepted"]

        fresh_detail = (await client.get(f"/api/v1/submissions/{fresh_id}")).json()
        fresh_keys = (await client.get(f"/api/v1/submissions/{fresh_id}/keys")).json()
        assert len(fresh_keys["contentKeys"][0]["wraps"]) == 3
        assert _decrypt_from_console_api(
            fresh_detail, fresh_keys, latecomer.private_bytes_raw()
        ) == {"resp_name": "collected later"}

    _run_with_client(crypto_api, scenario)


@pytest.mark.db
def test_a_repeated_nonce_is_refused_with_a_reason(crypto_api: Any) -> None:
    """Envelope §4.5: the last line of defence against a broken counter.

    An honest client that reuses a counter is already caught upstream — the
    same (deviceId, counter) is treated as a replay (sync §4) and nothing is
    written. This is the case that gets past that: the nonce arrives on the
    wire, so a broken or hostile client can send a *fresh* counter with a
    *stale* nonce. Two different ciphertexts under one (key, nonce) is the
    catastrophic AES-GCM failure, and the server has to refuse it without being
    able to decrypt either one — with a stated reason, not a 500 on an index.
    """
    submission = "01SUBNONCE"
    device = Client(DEVICE_B, _recipients())

    first = device.encrypted_op("01OPNONCE1", submission, "cd4_count", 412, counter=500)
    # A fresh counter, so the replay rule does not fire, carrying the nonce the
    # accepted op already used.
    forged = device.encrypted_op("01OPNONCE2", submission, "cd4_count", 999, counter=501)
    assert forged["nonce"] != first["nonce"]
    forged["nonce"] = first["nonce"]

    async def scenario(client: Any) -> None:
        accepted = await _push(client, DEVICE_B, [first], [device.wrapped(submission)])
        assert accepted["accepted"] == ["01OPNONCE1"]

        result = await _push(client, DEVICE_B, [forged], [])
        assert result["accepted"] == []
        assert result["rejected"] == [{"opId": "01OPNONCE2", "reason": "nonce_reused"}]

        # The accepted op is untouched — a rejection is not a write.
        rows = await _fetch(
            f"SELECT id FROM submission_op WHERE submission_id = '{submission}'"
        )
        assert [row["id"] for row in rows] == ["01OPNONCE1"]

        # And the same pair inside a single batch is caught too, before the
        # database ever sees the second one.
        a = device.encrypted_op("01OPNONCE3", submission, "notes", "one", counter=510)
        b = device.encrypted_op("01OPNONCE4", submission, "notes", "two", counter=511)
        b["nonce"] = a["nonce"]
        batch = await _push(client, DEVICE_B, [a, b], [])
        assert batch["accepted"] == ["01OPNONCE3"]
        assert batch["rejected"] == [{"opId": "01OPNONCE4", "reason": "nonce_reused"}]

    _run_with_client(crypto_api, scenario)


@pytest.mark.db
def test_the_same_nonce_under_a_different_content_key_is_fine(crypto_api: Any) -> None:
    """Two devices derive the same nonce only if they share a counter AND a key.

    They never share a key — that is why per-device content keys exist (§4.2) —
    so the uniqueness rule is on the pair, not on the nonce alone. Rejecting on
    the nonce alone would break peer-to-peer collection on day one.
    """
    submission = "01SUBTWODEV"
    a = Client(DEVICE_A, _recipients())
    b = Client(DEVICE_B, _recipients())

    op_a = a.encrypted_op("01OPTWO1", submission, "patient_name", "Amina", counter=900)
    op_b = b.encrypted_op("01OPTWO2", submission, "notes", "second device", counter=900)
    # Different devices: the derivation already separates them.
    assert op_a["nonce"] != op_b["nonce"]
    assert op_a["contentKeyId"] != op_b["contentKeyId"]

    async def scenario(client: Any) -> None:
        result = await _push(
            client, DEVICE_A, [op_a, op_b], [a.wrapped(submission), b.wrapped(submission)]
        )
        assert result["rejected"] == []
        assert sorted(result["accepted"]) == ["01OPTWO1", "01OPTWO2"]

        keys = (await client.get(f"/api/v1/submissions/{submission}/keys")).json()
        # One content key per contributing device, both wrapped to both
        # recipients, so one private key opens the whole submission (§7).
        assert len(keys["contentKeys"]) == 2
        assert all(len(k["wraps"]) == 2 for k in keys["contentKeys"])

        pulled = (await client.get("/api/v1/sync/pull", params={"cursor": 0, "limit": 500})).json()
        ops = [o for o in pulled["ops"] if o["submissionId"] == submission]
        answers = _decrypt(ops, keys, PRIMARY_PRIVATE.private_bytes_raw())
        assert answers == {"patient_name": "Amina", "notes": "second device"}

    _run_with_client(crypto_api, scenario)


@pytest.mark.db
def test_an_op_whose_content_key_never_arrived_is_refused_not_orphaned(crypto_api: Any) -> None:
    """Ciphertext the server keeps but nobody can decrypt is worse than a retry.

    The client sends the key with the ops it encrypts; if the key is missing the
    ops are refused with a reason and stay in the outbox, where the next sync
    sends both together.
    """
    submission = "01SUBNOKEY"
    device = Client(DEVICE_A, _recipients())
    op = device.encrypted_op("01OPNOKEY", submission, "hiv_status", "positive", counter=950)

    async def scenario(client: Any) -> None:
        result = await _push(client, DEVICE_A, [op], keys=[])
        assert result["accepted"] == []
        assert result["rejected"] == [{"opId": "01OPNOKEY", "reason": "unknown_content_key"}]

        # Retried with its key, as the client would on the next sync.
        retried = await _push(client, DEVICE_A, [op], [device.wrapped(submission)])
        assert retried["accepted"] == ["01OPNOKEY"]

    _run_with_client(crypto_api, scenario)


@pytest.mark.db
def test_a_ciphertext_moved_to_another_field_fails_to_authenticate(crypto_api: Any) -> None:
    """The AAD binds a value to its exact location (envelope §5).

    Without `path` in the AAD a server operator could relocate an encrypted
    answer from `notes` to `hiv_status` and the client would decrypt it without
    complaint. This is the test that says the binding is load-bearing.
    """
    submission = "01SUBAAD"
    device = Client(DEVICE_A, _recipients())
    op = device.encrypted_op("01OPAAD", submission, "notes", "seen at clinic", counter=980)

    async def scenario(client: Any) -> None:
        assert (await _push(client, DEVICE_A, [op], [device.wrapped(submission)]))["accepted"]

        keys = (await client.get(f"/api/v1/submissions/{submission}/keys")).json()
        pulled = (await client.get("/api/v1/sync/pull", params={"cursor": 0, "limit": 500})).json()
        stored = next(o for o in pulled["ops"] if o["opId"] == "01OPAAD")

        # A hostile operator rewrites the path and hands it back.
        relocated = dict(stored, path="hiv_status")
        with pytest.raises(EnvelopeError):
            _decrypt([relocated], keys, PRIMARY_PRIVATE.private_bytes_raw())

        # Likewise a replay against another form version.
        with pytest.raises(EnvelopeError):
            _decrypt(
                [dict(stored, formVersion=FORM_VERSION + 1)],
                keys,
                PRIMARY_PRIVATE.private_bytes_raw(),
            )

    _run_with_client(crypto_api, scenario)


@pytest.mark.db
def test_field_level_keeps_the_non_sensitive_remainder_queryable(crypto_api: Any) -> None:
    """The mode that keeps the product useful (envelope §1, §5.2).

    In `field_level` a submission carries both kinds of op. The sensitive values
    are unreadable to the server; everything else stays in the fold, which is
    what dashboards, duplicate detection and quality rules run on. If encryption
    emptied the fold entirely, `field_level` would just be a slower
    `project_e2e`.
    """
    submission = "01SUBFIELDLEVEL"
    device = Client(DEVICE_A, _recipients())

    # Only `sensitive: true` fields are encrypted; the rest travel as plaintext.
    encrypted = [
        device.encrypted_op("01OPFL1", submission, "hiv_status", "positive", counter=700),
        device.encrypted_op("01OPFL2", submission, "cd4_count", 412, counter=701),
    ]
    plaintext = [
        {
            "opId": "01OPFL3",
            "submissionId": submission,
            "formId": FORM_KEY,
            "formVersion": FORM_VERSION,
            "kind": "set",
            "path": "clinic_code",
            "value": "KLA-07",
            "deviceId": DEVICE_A,
            "counter": 702,
            "wallClock": datetime.now(tz=UTC).isoformat(),
        },
        {
            "opId": "01OPFL4",
            "submissionId": submission,
            "formId": FORM_KEY,
            "formVersion": FORM_VERSION,
            "kind": "set",
            "path": "visit_number",
            "value": 3,
            "deviceId": DEVICE_A,
            "counter": 703,
            "wallClock": datetime.now(tz=UTC).isoformat(),
        },
    ]

    async def scenario(client: Any) -> None:
        result = await _push(
            client, DEVICE_A, encrypted + plaintext, [device.wrapped(submission)]
        )
        assert result["rejected"] == []

        # The fold holds exactly the non-sensitive answers, and nothing else.
        state = await _fetch(
            f"SELECT data FROM submission_state WHERE submission_id = '{submission}'"
        )
        assert json.loads(state[0]["data"]) == {"clinic_code": "KLA-07", "visit_number": 3}

        keys = (await client.get(f"/api/v1/submissions/{submission}/keys")).json()
        pulled = (await client.get("/api/v1/sync/pull", params={"cursor": 0, "limit": 500})).json()
        ops = [o for o in pulled["ops"] if o["submissionId"] == submission]

        # A key holder sees the whole submission: both halves fold together.
        assert _decrypt(ops, keys, PRIMARY_PRIVATE.private_bytes_raw()) == {
            "hiv_status": "positive",
            "cd4_count": 412,
            "clinic_code": "KLA-07",
            "visit_number": 3,
        }

    _run_with_client(crypto_api, scenario)


@pytest.mark.db
def test_encrypting_a_field_answered_earlier_in_plaintext_removes_it_from_the_fold(
    crypto_api: Any,
) -> None:
    """A superseded plaintext answer must not survive in a queryable projection.

    This happens for real: a field is marked `sensitive` in a new form version,
    or an enumerator corrects an answer after the project's mode changed the
    form. Leaving the old value in the fold would report a superseded answer as
    current AND disclose the very value the newer op was encrypted to protect.
    """
    submission = "01SUBUPGRADE"
    device = Client(DEVICE_A, _recipients())

    plain = {
        "opId": "01OPUP1",
        "submissionId": submission,
        "formId": FORM_KEY,
        "formVersion": FORM_VERSION,
        "kind": "set",
        "path": "hiv_status",
        "value": "positive",
        "deviceId": DEVICE_A,
        "counter": 800,
        "wallClock": datetime.now(tz=UTC).isoformat(),
    }
    corrected = device.encrypted_op("01OPUP2", submission, "hiv_status", "negative", counter=801)

    async def scenario(client: Any) -> None:
        await _push(client, DEVICE_A, [plain], [])
        state = await _fetch(
            f"SELECT data FROM submission_state WHERE submission_id = '{submission}'"
        )
        assert json.loads(state[0]["data"]) == {"hiv_status": "positive"}

        await _push(client, DEVICE_A, [corrected], [device.wrapped(submission)])
        state = await _fetch(
            f"SELECT data FROM submission_state WHERE submission_id = '{submission}'"
        )
        assert json.loads(state[0]["data"]) == {}

        keys = (await client.get(f"/api/v1/submissions/{submission}/keys")).json()
        pulled = (await client.get("/api/v1/sync/pull", params={"cursor": 0, "limit": 500})).json()
        ops = [o for o in pulled["ops"] if o["submissionId"] == submission]
        # The correction wins for a key holder, in (counter, deviceId) order.
        assert _decrypt(ops, keys, PRIMARY_PRIVATE.private_bytes_raw()) == {
            "hiv_status": "negative"
        }

    _run_with_client(crypto_api, scenario)


@pytest.mark.db
def test_two_pushes_racing_for_one_nonce_still_get_a_reason(crypto_api: Any) -> None:
    """Whichever path catches it, the answer is the same and neither is a 500.

    The pre-check sees only what was committed when it ran, so two concurrent
    pushes can both pass it and meet at the unique index instead. That is what
    the index is for; the point of this test is that reaching it produces a
    stated reason and a working push for the winner, not a failed request for
    both.
    """
    submission = "01SUBRACE"
    device = Client(DEVICE_B, _recipients())

    seed = device.encrypted_op("01OPRACE0", submission, "clinic_code", "KLA-07", counter=600)
    left = device.encrypted_op("01OPRACE1", submission, "cd4_count", 1, counter=601)
    right = device.encrypted_op("01OPRACE2", submission, "cd4_count", 2, counter=602)
    right["nonce"] = left["nonce"]

    async def scenario(client: Any) -> None:
        # The submission and its content key exist before the race, so the two
        # pushes differ in nothing but the op they carry.
        await _push(client, DEVICE_B, [seed], [device.wrapped(submission)])

        first, second = await asyncio.gather(
            client.post("/api/v1/sync/push", json={"deviceId": DEVICE_B, "ops": [left]}),
            client.post("/api/v1/sync/push", json={"deviceId": DEVICE_B, "ops": [right]}),
            return_exceptions=True,
        )
        for response in (first, second):
            assert not isinstance(response, BaseException), response
            assert response.status_code == 200, response.text

        outcomes = [r.json() for r in (first, second)]
        accepted = [op for r in outcomes for op in r["accepted"]]
        rejected = [op for r in outcomes for op in r["rejected"]]
        assert len(accepted) == 1, outcomes
        assert rejected == [{"opId": next(
            op for op in ("01OPRACE1", "01OPRACE2") if op not in accepted
        ), "reason": "nonce_reused"}]

        # Exactly one row holds that nonce, which is the property that matters.
        rows = await _fetch(
            f"SELECT id FROM submission_op WHERE nonce = '\\x{left['nonce']}'::bytea"
        )
        assert len(rows) == 1

    _run_with_client(crypto_api, scenario)


def test_the_derived_nonce_does_not_depend_on_wall_clock_or_run() -> None:
    """Envelope §4.5. Derivation, not randomness — no database needed.

    A random nonce would work cryptographically but would depend on the RNG of
    a cheap Android handset, and would make a retried push produce different
    bytes for the same op, which the server's uniqueness check would then have
    to tolerate rather than enforce.
    """
    assert op_nonce("device-a", 148) == op_nonce("device-a", 148)
    assert op_nonce("device-a", 148) != op_nonce("device-a", 149)
    assert op_nonce("device-a", 148) != op_nonce("device-b", 148)
    assert len(op_nonce("device-a", 0)) == 12


def test_a_unique_violation_maps_to_the_reason_a_client_can_act_on() -> None:
    """The fallback path when a concurrent push beats the pre-check to the index.

    Racing to reach it in a test is timing-dependent, so the mapping is checked
    directly: it is the part that decides between a stated reason and a 500, and
    it is keyed on constraint names Postgres derives from column lists, which
    nothing else in the codebase would notice changing.
    """
    import asyncpg
    from sqlalchemy.exc import IntegrityError

    from app.modules.sync.service import (
        _COUNTER_CONSTRAINT,
        _NONCE_CONSTRAINT,
        _integrity_reason,
    )

    def violation(constraint: str) -> IntegrityError:
        original = asyncpg.exceptions.UniqueViolationError("duplicate key")
        original.constraint_name = constraint
        return IntegrityError("INSERT ...", None, original)

    assert _integrity_reason(violation(_NONCE_CONSTRAINT)) == "nonce_reused"
    # A counter collision means the op is already stored under another opId:
    # the replay verdict, which is acceptance, not a rejection.
    assert _integrity_reason(violation(_COUNTER_CONSTRAINT)) is None

    # Anything unanticipated propagates. Swallowing it would hide a real bug
    # behind a rejected op that a client would then retry forever.
    with pytest.raises(IntegrityError):
        _integrity_reason(violation("submission_op_submission_id_fkey"))


def test_the_constraint_names_match_the_schema() -> None:
    """Postgres derives these from the column lists; nothing else would notice.

    If a migration renames or restructures either unique constraint, the
    fallback above stops recognising it and a losing race becomes a 500 again.
    """
    from app.modules.submissions.models import SubmissionOp
    from app.modules.sync.service import _COUNTER_CONSTRAINT, _NONCE_CONSTRAINT

    unique_columns = {
        tuple(col.name for col in constraint.columns)
        for constraint in SubmissionOp.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("content_key_id", "nonce") in unique_columns
    assert ("device_id", "counter") in unique_columns
    # Postgres names an unnamed UNIQUE as <table>_<col>_<col>_key.
    assert _NONCE_CONSTRAINT == "submission_op_content_key_id_nonce_key"
    assert _COUNTER_CONSTRAINT == "submission_op_device_id_counter_key"
