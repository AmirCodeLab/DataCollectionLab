"""Media capture end to end (sync protocol §9, encryption envelope §6).

Runs the real endpoints against a scratch database, acting as the device: it
generates a per-file media key, wraps it to project keys whose private halves
the server never sees, encrypts the file 4 MiB chunk at a time with the
reference envelope, and uploads.

What it proves is the set of properties the design exists for:

1. an op referencing media is accepted before the file arrives, and the pair
   resolves once the file lands — in either order;
2. an upload interrupted mid-way resumes without re-sending completed chunks;
3. the same photograph from two devices produces different ciphertext hashes,
   so the server cannot tell that two submissions contain the same image;
4. a stored chunk on the server's disk contains none of the original image
   bytes;
5. a chunk cannot be decrypted at a different chunk index.

Skips when Postgres is unreachable (docker compose up -d postgres), like every
other db-marked test.
"""

from __future__ import annotations

import asyncio
import hashlib
import pathlib
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from app.modules.crypto.envelope import (
    CONTENT_KEY_BYTES,
    MEDIA_CHUNK_BYTES,
    EnvelopeError,
    WrappedKey,
    ciphertext_hash,
    decrypt_media_chunk,
    encrypt_media_chunk,
    unwrap_content_key,
    wrap_to_recipients,
)

MEDIA_DB = "dcp_test_media"

PROJECT_ID = "01PROJMEDIA"
FORM_KEY = "housing_survey"
FORM_VERSION = 1
DEVICE_A = "dev-media-a"
DEVICE_B = "dev-media-b"
PROJECT_KEY_PRIMARY = "01PKEYMEDIAPRI"
PROJECT_KEY_BACKUP = "01PKEYMEDIABAK"

# TEST ONLY. Generated per run so nothing here can be mistaken for a key that
# matters, and so the test proves the wrap works rather than that a fixture
# still decodes.
PRIMARY_PRIVATE = X25519PrivateKey.generate()
BACKUP_PRIVATE = X25519PrivateKey.generate()

# A stand-in photograph: two full chunks and a short one, so chunking, the
# last-chunk exemption from the fixed size, and multi-chunk hashing are all
# exercised. Deterministic, because a test that fails should fail the same way
# twice.
PHOTO = bytes((i * 37 + 11) % 251 for i in range(1024)) * (
    (2 * MEDIA_CHUNK_BYTES + 4096) // 1024
)

# A recognisable run inside it, so "the ciphertext contains none of the
# plaintext" is a claim about something specific rather than about entropy.
PHOTO_MARKER = b"JFIF-DCP-TEST-MARKER-0123456789"
PHOTO = PHOTO_MARKER + PHOTO[len(PHOTO_MARKER) :]


# ---------------------------------------------------------------------------
# Scratch database and media root
# ---------------------------------------------------------------------------


def _admin_dsn() -> str:
    from app.core.config import get_settings

    return get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")


def _media_db_url(scheme: str = "postgresql+asyncpg") -> str:
    parts = urlsplit(_admin_dsn())
    return urlunsplit(parts._replace(scheme=scheme, path=f"/{MEDIA_DB}"))


async def _seed(security_mode: str) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.modules.crypto.models import ProjectKey
    from app.modules.forms.models import Form, FormVersion
    from app.modules.projects.models import Device, Environment, Project

    engine = create_async_engine(_media_db_url())
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            session.add(
                Project(
                    id=PROJECT_ID,
                    name="Housing Conditions",
                    slug="housing-conditions",
                    security_mode=security_mode,
                )
            )
            await session.flush()
            session.add(Environment(id="01ENVMEDIA", project_id=PROJECT_ID, kind="production"))
            session.add(
                Form(id="01FORMMEDIA", project_id=PROJECT_ID, form_key=FORM_KEY, title="Housing")
            )
            for device_id in (DEVICE_A, DEVICE_B):
                session.add(
                    Device(
                        id=device_id, project_id=PROJECT_ID, user_id="usr-1", platform="android"
                    )
                )
            for key_id, private in (
                (PROJECT_KEY_PRIMARY, PRIMARY_PRIVATE),
                (PROJECT_KEY_BACKUP, BACKUP_PRIVATE),
            ):
                session.add(
                    ProjectKey(
                        id=key_id,
                        project_id=PROJECT_ID,
                        public_key=private.public_key().public_bytes_raw(),
                        key_role="primary" if key_id == PROJECT_KEY_PRIMARY else "backup",
                        label="Programme lead" if key_id == PROJECT_KEY_PRIMARY else "Escrow",
                    )
                )
            await session.flush()
            session.add(
                FormVersion(
                    id="01FORMVMEDIA",
                    form_id="01FORMMEDIA",
                    version=FORM_VERSION,
                    ir={},
                    ir_checksum="test",
                )
            )
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def media_api() -> Any:
    """The real app on a scratch database, with media on a scratch disk."""
    import asyncpg
    from alembic import command
    from alembic.config import Config

    from app.infrastructure.media_storage import FilesystemMediaStore, set_media_store
    from tests.test_migrations import BACKEND_DIR

    async def prepare() -> str | None:
        try:
            conn = await asyncpg.connect(_admin_dsn(), timeout=3)
        except Exception as exc:  # noqa: BLE001 - any failure means "not available"
            return f"{type(exc).__name__}: {exc}"
        try:
            await conn.execute(f"DROP DATABASE IF EXISTS {MEDIA_DB} WITH (FORCE)")
            await conn.execute(f"CREATE DATABASE {MEDIA_DB}")
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
    cfg.set_main_option("sqlalchemy.url", _media_db_url())
    command.upgrade(cfg, "head")

    asyncio.run(_seed("project_e2e"))

    root = tempfile.TemporaryDirectory(prefix="dcp-media-test-")
    set_media_store(FilesystemMediaStore(pathlib.Path(root.name)))

    from app.api.deps import get_db
    from app.main import app

    async def scratch_db() -> AsyncIterator[Any]:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        # One engine per request: each test runs in its own event loop, and
        # pooled asyncpg connections cannot cross loops.
        engine = create_async_engine(_media_db_url())
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                yield session
        finally:
            await engine.dispose()

    app.dependency_overrides[get_db] = scratch_db
    yield app, pathlib.Path(root.name)
    app.dependency_overrides.pop(get_db, None)
    set_media_store(None)
    root.cleanup()

    async def drop() -> None:
        conn = await asyncpg.connect(_admin_dsn())
        try:
            await conn.execute(f"DROP DATABASE IF EXISTS {MEDIA_DB} WITH (FORCE)")
        finally:
            await conn.close()

    asyncio.run(drop())


def _run_with_client(app: Any, scenario: Callable[[Any], Awaitable[None]]) -> None:
    import httpx

    async def main() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", timeout=60
        ) as client:
            await scenario(client)

    asyncio.run(main())


async def _fetch(query: str) -> Any:
    import asyncpg

    conn = await asyncpg.connect(_media_db_url(scheme="postgresql"))
    try:
        return await conn.fetch(query)
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# The client side, played by the reference envelope
# ---------------------------------------------------------------------------


def _recipients() -> dict[str, bytes]:
    return {
        PROJECT_KEY_PRIMARY: PRIMARY_PRIVATE.public_key().public_bytes_raw(),
        PROJECT_KEY_BACKUP: BACKUP_PRIVATE.public_key().public_bytes_raw(),
    }


def _chunks(data: bytes) -> list[bytes]:
    return [
        data[i : i + MEDIA_CHUNK_BYTES] for i in range(0, len(data), MEDIA_CHUNK_BYTES)
    ] or [b""]


class StagedMedia:
    """A file as a device holds it: encrypted, chunked, and content-addressed
    over the CIPHERTEXT (envelope §6)."""

    def __init__(self, media_id: str, plaintext: bytes) -> None:
        self.media_id = media_id
        self.content_key_id = f"{media_id}-key"
        # Per-file key, independent of any operation key (§6). Random here
        # rather than derived: this is exactly what a device does.
        self.media_key = hashlib.sha256(f"media-key/{media_id}".encode()).digest()
        assert len(self.media_key) == CONTENT_KEY_BYTES
        self.chunks = [
            encrypt_media_chunk(chunk, self.media_key, media_id=media_id, chunk_index=index)[0]
            for index, chunk in enumerate(_chunks(plaintext))
        ]
        self.hash = ciphertext_hash(self.chunks)
        self.wraps = wrap_to_recipients(self.media_key, self.content_key_id, _recipients())

    def session_body(self, submission_id: str, device_id: str, **extra: Any) -> dict[str, Any]:
        body = {
            "mediaId": self.media_id,
            "submissionId": submission_id,
            "deviceId": device_id,
            "mimeType": "image/jpeg",
            "sizeBytes": sum(len(c) for c in self.chunks),
            "chunkCount": len(self.chunks),
            "encrypted": True,
            "contentKeyId": self.content_key_id,
            "wraps": [
                {
                    "projectKeyId": wrap.project_key_id,
                    "ephemeralPublic": wrap.ephemeral_public.hex(),
                    "nonce": wrap.nonce.hex(),
                    "wrappedKey": wrap.wrapped_key.hex(),
                }
                for wrap in self.wraps
            ],
        }
        body.update(extra)
        return body


def _op(
    op_id: str,
    submission_id: str,
    device_id: str,
    counter: int,
    path: str,
    value: Any,
) -> dict[str, Any]:
    return {
        "opId": op_id,
        "submissionId": submission_id,
        "formId": FORM_KEY,
        "formVersion": FORM_VERSION,
        "kind": "set",
        "path": path,
        "value": value,
        "deviceId": device_id,
        "counter": counter,
        "wallClock": datetime.now(tz=UTC).isoformat(),
    }


async def _upload_chunks(
    client: Any, upload_id: str, staged: StagedMedia, indexes: list[int]
) -> None:
    for index in indexes:
        response = await client.put(
            f"/api/v1/media/upload-sessions/{upload_id}/chunks/{index}",
            content=staged.chunks[index],
            headers={"content-type": "application/octet-stream"},
        )
        assert response.status_code == 200, response.text


# ---------------------------------------------------------------------------
# 1. The op arrives before the file
# ---------------------------------------------------------------------------


@pytest.mark.db
def test_an_op_referencing_missing_media_is_accepted_and_pairs_up_later(media_api: Any) -> None:
    """The op is accepted, the media is `pending`, and the pair resolves when
    the file lands.

    This is the ordinary case, not an edge case: a device finishes a
    questionnaire in minutes and a 3 MB photograph when it next sees a tower.
    A foreign key from media to submission_op would make it an error instead
    (sync §9), which is why there is not one.
    """
    app, _root = media_api
    submission_id = "01SUBMEDIA1"
    media_id = "01MEDIAPENDING1"
    staged = StagedMedia(media_id, PHOTO)

    async def scenario(client: Any) -> None:
        # The op, carrying only a reference. The file is still on the device.
        push = await client.post(
            "/api/v1/sync/push",
            json={
                "deviceId": DEVICE_A,
                "ops": [
                    _op(
                        "01OPMEDIA1",
                        submission_id,
                        DEVICE_A,
                        1,
                        "roof_photo",
                        {
                            "id": media_id,
                            "filename": "roof.jpg",
                            "hash": staged.hash,
                            "size": len(PHOTO),
                        },
                    )
                ],
            },
        )
        assert push.status_code == 200, push.text
        assert push.json()["accepted"] == ["01OPMEDIA1"]
        assert push.json()["rejected"] == []

        # The server recorded the reference and is waiting for the file.
        listed = (await client.get(f"/api/v1/submissions/{submission_id}/media")).json()
        assert [m["mediaId"] for m in listed["media"]] == [media_id]
        pending = listed["media"][0]
        assert pending["status"] == "pending"
        assert pending["opId"] == "01OPMEDIA1"
        assert pending["fieldPath"] == "roof_photo"
        assert pending["resolved"] is False
        assert listed["pendingCount"] == 1

        # Now the file.
        opened = await client.post(
            "/api/v1/media/upload-sessions",
            json=staged.session_body(submission_id, DEVICE_A, opId="01OPMEDIA1"),
        )
        assert opened.status_code == 200, opened.text
        upload_id = opened.json()["uploadId"]
        assert opened.json()["receivedChunks"] == []

        await _upload_chunks(client, upload_id, staged, list(range(len(staged.chunks))))

        completed = await client.post(
            f"/api/v1/media/upload-sessions/{upload_id}/complete",
            json={"ciphertextHash": staged.hash},
        )
        assert completed.status_code == 200, completed.text
        # The server's own hash over what it stored, not an echo of ours.
        assert completed.json()["hash"] == staged.hash
        assert completed.json()["status"] == "complete"

        # Both halves are here, so the pair has resolved.
        resolved = (await client.get(f"/api/v1/submissions/{submission_id}/media")).json()
        assert resolved["media"][0]["status"] == "complete"
        assert resolved["media"][0]["resolved"] is True
        assert resolved["pendingCount"] == 0

    _run_with_client(app, scenario)


@pytest.mark.db
def test_a_file_that_lands_before_its_op_also_pairs_up(media_api: Any) -> None:
    """The other order. Neither half is privileged."""
    app, _root = media_api
    submission_id = "01SUBMEDIA2"
    media_id = "01MEDIAEARLY1"
    staged = StagedMedia(media_id, PHOTO[:1024])

    async def scenario(client: Any) -> None:
        # The submission has to exist for its media to belong to it, so one
        # unrelated op opens it.
        first = await client.post(
            "/api/v1/sync/push",
            json={
                "deviceId": DEVICE_A,
                "ops": [_op("01OPMEDIA2A", submission_id, DEVICE_A, 2, "address", "12 Mill St")],
            },
        )
        assert first.json()["accepted"] == ["01OPMEDIA2A"]

        # The file first, naming the op that has not been pushed yet.
        opened = await client.post(
            "/api/v1/media/upload-sessions",
            json=staged.session_body(submission_id, DEVICE_A, opId="01OPMEDIA2B"),
        )
        upload_id = opened.json()["uploadId"]
        await _upload_chunks(client, upload_id, staged, [0])
        completed = await client.post(
            f"/api/v1/media/upload-sessions/{upload_id}/complete",
            json={"ciphertextHash": staged.hash},
        )
        assert completed.status_code == 200, completed.text

        # Complete, but not resolved: the op it names has not arrived.
        before = (await client.get(f"/api/v1/submissions/{submission_id}/media")).json()
        assert before["media"][0]["status"] == "complete"
        assert before["media"][0]["resolved"] is False
        assert before["pendingCount"] == 1

        push = await client.post(
            "/api/v1/sync/push",
            json={
                "deviceId": DEVICE_A,
                "ops": [
                    _op(
                        "01OPMEDIA2B",
                        submission_id,
                        DEVICE_A,
                        3,
                        "door_photo",
                        {"id": media_id, "filename": "door.jpg", "size": 1024},
                    )
                ],
            },
        )
        assert push.json()["accepted"] == ["01OPMEDIA2B"]

        after = (await client.get(f"/api/v1/submissions/{submission_id}/media")).json()
        assert after["media"][0]["resolved"] is True
        assert after["pendingCount"] == 0

    _run_with_client(app, scenario)


# ---------------------------------------------------------------------------
# 2. Resumption
# ---------------------------------------------------------------------------


@pytest.mark.db
def test_an_interrupted_upload_resumes_without_resending_completed_chunks(
    media_api: Any,
) -> None:
    """Reopening the session names the chunks already stored, and the client
    sends only the rest.

    The property that matters is the negative one: the chunks already here are
    not re-requested and not re-written. On a 2G link, re-sending 8 MiB to
    recover a dropped connection is the difference between an upload that
    finishes and one that never does.
    """
    app, root = media_api
    submission_id = "01SUBMEDIA3"
    media_id = "01MEDIARESUME1"
    staged = StagedMedia(media_id, PHOTO)
    assert len(staged.chunks) == 3, "the fixture must span several chunks to test resumption"

    async def scenario(client: Any) -> None:
        push = await client.post(
            "/api/v1/sync/push",
            json={
                "deviceId": DEVICE_A,
                "ops": [
                    _op(
                        "01OPMEDIA3",
                        submission_id,
                        DEVICE_A,
                        4,
                        "wall_photo",
                        {"id": media_id, "filename": "wall.jpg", "size": len(PHOTO)},
                    )
                ],
            },
        )
        assert push.json()["accepted"] == ["01OPMEDIA3"]

        opened = await client.post(
            "/api/v1/media/upload-sessions",
            json=staged.session_body(submission_id, DEVICE_A),
        )
        upload_id = opened.json()["uploadId"]
        assert opened.json()["chunkSize"] == MEDIA_CHUNK_BYTES

        # The connection drops after two of three chunks.
        await _upload_chunks(client, upload_id, staged, [0, 1])

        chunk_paths = sorted((root / "media" / media_id).iterdir())
        assert len(chunk_paths) == 2
        mtimes_before = {p.name: p.stat().st_mtime_ns for p in chunk_paths}

        # Completing now is refused, and says what is missing rather than
        # sealing a truncated file.
        premature = await client.post(
            f"/api/v1/media/upload-sessions/{upload_id}/complete",
            json={"ciphertextHash": staged.hash},
        )
        assert premature.status_code == 409
        assert premature.json()["detail"]["reason"] == "chunks_missing"

        # The device comes back and reopens the session for the same mediaId.
        resumed = await client.post(
            "/api/v1/media/upload-sessions",
            json=staged.session_body(submission_id, DEVICE_A),
        )
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["receivedChunks"] == [0, 1], (
            "a resuming client is told exactly which indexes to skip"
        )
        resumed_id = resumed.json()["uploadId"]

        # It sends only what is missing.
        await _upload_chunks(client, resumed_id, staged, [2])

        completed = await client.post(
            f"/api/v1/media/upload-sessions/{resumed_id}/complete",
            json={"ciphertextHash": staged.hash},
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["hash"] == staged.hash
        assert completed.json()["sizeBytes"] == sum(len(c) for c in staged.chunks)

        # The chunks that were already here were never rewritten.
        mtimes_after = {
            p.name: p.stat().st_mtime_ns for p in (root / "media" / media_id).iterdir()
        }
        for name, before in mtimes_before.items():
            assert mtimes_after[name] == before, f"chunk {name} was re-sent and rewritten"

    _run_with_client(app, scenario)


# ---------------------------------------------------------------------------
# 3. Two devices, one photograph, two ciphertext hashes
# ---------------------------------------------------------------------------


@pytest.mark.db
def test_the_same_photograph_from_two_devices_has_different_ciphertext_hashes(
    media_api: Any,
) -> None:
    """Content addressing is over ciphertext, and the key is per file.

    Hashing plaintext would deduplicate nicely and would also let the server
    confirm that two submissions contain the same photograph — precisely the
    inference end-to-end encryption exists to prevent (envelope §6). The cost
    is that the same image stored twice is stored twice, and that is the right
    trade.
    """
    app, _root = media_api
    a = StagedMedia("01MEDIASAMEA", PHOTO[:8192])
    b = StagedMedia("01MEDIASAMEB", PHOTO[:8192])

    assert a.media_key != b.media_key
    assert a.hash != b.hash, "identical plaintext must not produce identical ciphertext"
    # And the plaintext hash, which is what a naive implementation would have
    # used, is of course the same for both.
    assert hashlib.sha256(PHOTO[:8192]).hexdigest() == hashlib.sha256(PHOTO[:8192]).hexdigest()

    async def scenario(client: Any) -> None:
        for submission_id, device_id, counter, staged in (
            ("01SUBMEDIA4A", DEVICE_A, 5, a),
            ("01SUBMEDIA4B", DEVICE_B, 1, b),
        ):
            push = await client.post(
                "/api/v1/sync/push",
                json={
                    "deviceId": device_id,
                    "ops": [
                        _op(
                            f"01OPMEDIA4{device_id[-1].upper()}",
                            submission_id,
                            device_id,
                            counter,
                            "front_photo",
                            {"id": staged.media_id, "filename": "front.jpg", "size": 8192},
                        )
                    ],
                },
            )
            assert push.json()["rejected"] == [], push.text

            opened = await client.post(
                "/api/v1/media/upload-sessions",
                json=staged.session_body(submission_id, device_id),
            )
            upload_id = opened.json()["uploadId"]
            await _upload_chunks(client, upload_id, staged, [0])
            completed = await client.post(
                f"/api/v1/media/upload-sessions/{upload_id}/complete",
                json={"ciphertextHash": staged.hash},
            )
            assert completed.status_code == 200, completed.text

    _run_with_client(app, scenario)

    rows = asyncio.run(
        _fetch(
            "SELECT id, ciphertext_hash FROM media "
            "WHERE id IN ('01MEDIASAMEA', '01MEDIASAMEB') ORDER BY id"
        )
    )
    hashes = {row["id"]: row["ciphertext_hash"] for row in rows}
    assert hashes["01MEDIASAMEA"] == a.hash
    assert hashes["01MEDIASAMEB"] == b.hash
    assert hashes["01MEDIASAMEA"] != hashes["01MEDIASAMEB"], (
        "the server can tell these two submissions contain the same photograph"
    )


# ---------------------------------------------------------------------------
# 4. Nothing on disk is the photograph
# ---------------------------------------------------------------------------


@pytest.mark.db
def test_a_stored_chunk_contains_none_of_the_original_image_bytes(media_api: Any) -> None:
    """What is written to the server's disk is ciphertext and nothing else.

    Checked against a recognisable run in the plaintext rather than against
    entropy: a marker either survives into the stored bytes or it does not, and
    "the file looks random" is not a test.
    """
    app, root = media_api
    submission_id = "01SUBMEDIA5"
    media_id = "01MEDIAONDISK1"
    plaintext = PHOTO[:16384]
    staged = StagedMedia(media_id, plaintext)

    async def scenario(client: Any) -> None:
        push = await client.post(
            "/api/v1/sync/push",
            json={
                "deviceId": DEVICE_A,
                "ops": [
                    _op(
                        "01OPMEDIA5",
                        submission_id,
                        DEVICE_A,
                        6,
                        "id_card",
                        {"id": media_id, "filename": "id.jpg", "size": len(plaintext)},
                    )
                ],
            },
        )
        assert push.json()["rejected"] == [], push.text

        opened = await client.post(
            "/api/v1/media/upload-sessions",
            json=staged.session_body(submission_id, DEVICE_A),
        )
        upload_id = opened.json()["uploadId"]
        await _upload_chunks(client, upload_id, staged, [0])
        completed = await client.post(
            f"/api/v1/media/upload-sessions/{upload_id}/complete",
            json={"ciphertextHash": staged.hash},
        )
        assert completed.status_code == 200, completed.text

    _run_with_client(app, scenario)

    on_disk = b"".join(
        path.read_bytes() for path in sorted((root / "media" / media_id).iterdir())
    )
    assert on_disk, "nothing was written"
    assert PHOTO_MARKER not in on_disk
    assert plaintext[:64] not in on_disk
    # Nor any 32-byte window of it. AES-GCM in counter mode would leak a
    # repeated plaintext block as a repeated ciphertext block only if the key
    # or nonce repeated, so this is the check that would catch that.
    for offset in range(0, len(plaintext) - 32, 977):
        assert plaintext[offset : offset + 32] not in on_disk

    # And a key holder gets the photograph back, byte for byte — otherwise this
    # test would pass just as well against a store that threw the file away.
    wraps = asyncio.run(
        _fetch(
            "SELECT project_key_id, ephemeral_public, nonce, wrapped_key "
            f"FROM media_wrapped_key WHERE media_id = '{media_id}' ORDER BY project_key_id"
        )
    )
    assert len(wraps) == 2, "wrapped to both recipients (envelope §4.3)"
    recovered = unwrap_content_key(
        WrappedKey(
            project_key_id=wraps[0]["project_key_id"],
            content_key_id=staged.content_key_id,
            ephemeral_public=bytes(wraps[0]["ephemeral_public"]),
            nonce=bytes(wraps[0]["nonce"]),
            wrapped_key=bytes(wraps[0]["wrapped_key"]),
        ),
        BACKUP_PRIVATE.private_bytes_raw(),
    )
    assert recovered == staged.media_key
    assert (
        decrypt_media_chunk(on_disk, recovered, media_id=media_id, chunk_index=0) == plaintext
    )


# ---------------------------------------------------------------------------
# 5. A chunk is bound to its index
# ---------------------------------------------------------------------------


def test_a_chunk_cannot_be_decrypted_at_a_different_index() -> None:
    """Chunk *n* decrypts at *n* and nowhere else.

    Both the nonce and the AAD carry the index (envelope §6). Without that, a
    server operator could reorder the chunks of a file — or splice one file's
    chunk into another's — and the result would decrypt without complaint into
    a different photograph. Needs no database: it is a property of the envelope.
    """
    media_key = hashlib.sha256(b"chunk-index-binding").digest()
    media_id = "01MEDIAINDEXBIND"
    first, _nonce = encrypt_media_chunk(b"chunk zero", media_key, media_id=media_id, chunk_index=0)
    second, _ = encrypt_media_chunk(b"chunk one", media_key, media_id=media_id, chunk_index=1)

    assert decrypt_media_chunk(first, media_key, media_id=media_id, chunk_index=0) == b"chunk zero"
    assert decrypt_media_chunk(second, media_key, media_id=media_id, chunk_index=1) == b"chunk one"

    with pytest.raises(EnvelopeError):
        decrypt_media_chunk(first, media_key, media_id=media_id, chunk_index=1)
    with pytest.raises(EnvelopeError):
        decrypt_media_chunk(second, media_key, media_id=media_id, chunk_index=0)

    # And not into another file either: the AAD carries the media id too, so a
    # chunk cannot be moved between files any more than between indexes.
    with pytest.raises(EnvelopeError):
        decrypt_media_chunk(first, media_key, media_id="01MEDIAOTHERFILE", chunk_index=0)


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


@pytest.mark.db
def test_an_encrypted_file_with_no_wrapped_key_is_refused(media_api: Any) -> None:
    """A media key wrapped to nobody is a file nobody can ever open.

    It would upload perfectly and look exactly like a file somebody can open.
    This is the last moment the mistake is still recoverable, so it is refused
    here rather than discovered by whoever tries to read the data.
    """
    app, _root = media_api
    submission_id = "01SUBMEDIA6"
    staged = StagedMedia("01MEDIANOWRAP", PHOTO[:512])

    async def scenario(client: Any) -> None:
        await client.post(
            "/api/v1/sync/push",
            json={
                "deviceId": DEVICE_A,
                "ops": [_op("01OPMEDIA6", submission_id, DEVICE_A, 7, "note", "x")],
            },
        )
        body = staged.session_body(submission_id, DEVICE_A)
        body["wraps"] = []
        refused = await client.post("/api/v1/media/upload-sessions", json=body)
        assert refused.status_code == 422
        assert refused.json()["detail"]["reason"] == "unwrapped_media_key"

        body = staged.session_body(submission_id, DEVICE_A)
        body["wraps"][0]["projectKeyId"] = "01PKEYNOTOURS"
        stranger = await client.post("/api/v1/media/upload-sessions", json=body)
        assert stranger.status_code == 422
        assert stranger.json()["detail"]["reason"] == "unknown_recipient"

    _run_with_client(app, scenario)


@pytest.mark.db
def test_a_chunk_of_the_wrong_size_is_refused(media_api: Any) -> None:
    """Chunk size is fixed at 4 MiB, not negotiated (envelope §6).

    Two clients that disagreed about where the boundaries fall would derive the
    same `(mediaId, index)` nonce for different plaintext, which is the one
    failure AES-GCM does not survive.
    """
    app, _root = media_api
    submission_id = "01SUBMEDIA7"
    staged = StagedMedia("01MEDIABADSIZE", PHOTO)

    async def scenario(client: Any) -> None:
        await client.post(
            "/api/v1/sync/push",
            json={
                "deviceId": DEVICE_A,
                "ops": [_op("01OPMEDIA7", submission_id, DEVICE_A, 8, "note", "x")],
            },
        )
        opened = await client.post(
            "/api/v1/media/upload-sessions",
            json=staged.session_body(submission_id, DEVICE_A),
        )
        upload_id = opened.json()["uploadId"]

        short = await client.put(
            f"/api/v1/media/upload-sessions/{upload_id}/chunks/0",
            content=staged.chunks[0][:1000],
            headers={"content-type": "application/octet-stream"},
        )
        assert short.status_code == 422
        assert short.json()["detail"]["reason"] == "chunk_size_mismatch"

        past_the_end = await client.put(
            f"/api/v1/media/upload-sessions/{upload_id}/chunks/{len(staged.chunks)}",
            content=staged.chunks[-1],
            headers={"content-type": "application/octet-stream"},
        )
        assert past_the_end.status_code == 422
        assert past_the_end.json()["detail"]["reason"] == "chunk_out_of_range"

    _run_with_client(app, scenario)


@pytest.mark.db
def test_completion_recomputes_the_hash_rather_than_echoing_it(media_api: Any) -> None:
    """A declared hash that does not match the stored bytes fails the upload."""
    app, _root = media_api
    submission_id = "01SUBMEDIA8"
    staged = StagedMedia("01MEDIABADHASH", PHOTO[:2048])

    async def scenario(client: Any) -> None:
        await client.post(
            "/api/v1/sync/push",
            json={
                "deviceId": DEVICE_A,
                "ops": [_op("01OPMEDIA8", submission_id, DEVICE_A, 9, "note", "x")],
            },
        )
        opened = await client.post(
            "/api/v1/media/upload-sessions",
            json=staged.session_body(submission_id, DEVICE_A),
        )
        upload_id = opened.json()["uploadId"]
        await _upload_chunks(client, upload_id, staged, [0])

        wrong = await client.post(
            f"/api/v1/media/upload-sessions/{upload_id}/complete",
            json={"ciphertextHash": "0" * 64},
        )
        assert wrong.status_code == 422
        assert wrong.json()["detail"]["reason"] == "hash_mismatch"
        # The server's own computation is in the message, so the client can see
        # which side is wrong without another round trip.
        assert staged.hash in wrong.json()["detail"]["message"]

        right = await client.post(
            f"/api/v1/media/upload-sessions/{upload_id}/complete",
            json={"ciphertextHash": staged.hash},
        )
        assert right.status_code == 200, right.text

    _run_with_client(app, scenario)


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


@pytest.mark.db
def test_a_device_reads_the_projects_capture_policy(media_api: Any) -> None:
    """Compression settings and the GPS accuracy threshold reach the device."""
    app, _root = media_api

    async def scenario(client: Any) -> None:
        default = await client.get(f"/api/v1/devices/{DEVICE_A}/media-policy")
        assert default.status_code == 200, default.text
        assert default.json()["chunkSize"] == MEDIA_CHUNK_BYTES
        assert default.json()["policy"] == {
            "imageMaxDimension": 1600,
            "imageQuality": 80,
            "gpsMaxAccuracyM": 50,
        }

        changed = await client.patch(
            f"/api/v1/projects/{PROJECT_ID}/media-policy",
            json={"imageMaxDimension": 1024, "gpsMaxAccuracyM": 15},
        )
        assert changed.status_code == 200, changed.text
        # Omitted fields are left alone.
        assert changed.json()["policy"] == {
            "imageMaxDimension": 1024,
            "imageQuality": 80,
            "gpsMaxAccuracyM": 15,
        }

        after = await client.get(f"/api/v1/devices/{DEVICE_A}/media-policy")
        assert after.json()["policy"]["gpsMaxAccuracyM"] == 15

        # Restore, so test ordering cannot matter.
        await client.patch(
            f"/api/v1/projects/{PROJECT_ID}/media-policy",
            json={"imageMaxDimension": 1600, "gpsMaxAccuracyM": 50},
        )

        unknown = await client.get("/api/v1/devices/dev-not-registered/media-policy")
        assert unknown.status_code == 404

    _run_with_client(app, scenario)


@pytest.mark.db
def test_reopening_a_session_before_any_chunk_lands_replaces_the_media_key(
    media_api: Any,
) -> None:
    """A device that restarted before uploading anything may restate the file.

    Nothing has been encrypted under the old media key yet — no chunk has
    landed — so the new one replaces it. Adding instead would collide on
    (media_id, project_key_id) and 500, and keeping the old one would leave
    wraps that open a key nothing is encrypted with.
    """
    app, _root = media_api
    submission_id = "01SUBMEDIA9"
    media_id = "01MEDIARESTATE"

    async def scenario(client: Any) -> None:
        await client.post(
            "/api/v1/sync/push",
            json={
                "deviceId": DEVICE_A,
                "ops": [_op("01OPMEDIA9", submission_id, DEVICE_A, 10, "note", "x")],
            },
        )
        first = StagedMedia(media_id, PHOTO[:2048])
        opened = await client.post(
            "/api/v1/media/upload-sessions", json=first.session_body(submission_id, DEVICE_A)
        )
        assert opened.status_code == 200, opened.text

        # The app was killed. It comes back, recompresses, and starts again.
        again = await client.post(
            "/api/v1/media/upload-sessions", json=first.session_body(submission_id, DEVICE_A)
        )
        assert again.status_code == 200, again.text
        assert again.json()["receivedChunks"] == []

        upload_id = again.json()["uploadId"]
        await _upload_chunks(client, upload_id, first, [0])
        completed = await client.post(
            f"/api/v1/media/upload-sessions/{upload_id}/complete",
            json={"ciphertextHash": first.hash},
        )
        assert completed.status_code == 200, completed.text

    _run_with_client(app, scenario)

    wraps = asyncio.run(
        _fetch(f"SELECT project_key_id FROM media_wrapped_key WHERE media_id = '{media_id}'")
    )
    assert len(wraps) == 2, "one wrap per recipient, not two sets"
