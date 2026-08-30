"""Where uploaded media chunks are put.

Chunks are stored as individual objects, one per `(media_id, chunk_index)`,
never concatenated into a single file. That is what makes resumption cheap: a
chunk that arrived is a chunk that exists, and the server can list what it has
without reading anything. It also means an interrupted upload leaves no
half-written object to distinguish from a complete one.

The default backend is the local filesystem, and that is deliberate for now.
S3/MinIO is the production target (`S3_ENDPOINT` is already in settings and
docker-compose runs MinIO), but the seam is this module's interface rather than
boto3 calls scattered through the service, so swapping it is one file.

**Nothing here decrypts anything.** For an encrypted project these bytes are
ciphertext the server has no key for (envelope §6), and the store is a place to
put bytes, not a place that understands them.
"""

from __future__ import annotations

import hashlib
import pathlib
import shutil
from typing import Protocol


def chunk_storage_key(media_id: str, chunk_index: int) -> str:
    """The object name for one chunk.

    Zero-padded so a listing sorts in chunk order rather than lexicographically
    putting chunk 10 before chunk 2 — which matters the first time somebody
    reassembles a file by listing the prefix.
    """
    return f"media/{media_id}/{chunk_index:08d}"


def chunk_hash(data: bytes) -> str:
    """SHA-256 of the bytes as stored. Never of plaintext (envelope §6)."""
    return hashlib.sha256(data).hexdigest()


class MediaStore(Protocol):
    """The seam an S3 backend will implement."""

    def put(self, key: str, data: bytes) -> None: ...

    def get(self, key: str) -> bytes: ...

    def delete_prefix(self, prefix: str) -> None: ...


class FilesystemMediaStore:
    """Chunks under a root directory, one file per chunk."""

    def __init__(self, root: pathlib.Path) -> None:
        self._root = root

    def _path(self, key: str) -> pathlib.Path:
        # `key` is built by chunk_storage_key from a media id we generated or
        # validated, never from raw client input, but resolving and checking
        # containment costs nothing and makes that a property of this module
        # rather than of every caller.
        path = (self._root / key).resolve()
        root = self._root.resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"storage key escapes the media root: {key!r}")
        return path

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename: a chunk is either fully there or not there at all.
        # A reader that finds a truncated chunk would compute a hash that does
        # not match and blame the network.
        temporary = path.with_name(path.name + ".partial")
        temporary.write_bytes(data)
        temporary.replace(path)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete_prefix(self, prefix: str) -> None:
        target = self._path(prefix)
        if target.is_dir():
            shutil.rmtree(target)


_store: MediaStore | None = None


def get_media_store() -> MediaStore:
    """The process-wide store, built from settings on first use."""
    global _store
    if _store is None:
        from app.core.config import get_settings

        _store = FilesystemMediaStore(pathlib.Path(get_settings().media_storage_root))
    return _store


def set_media_store(store: MediaStore | None) -> None:
    """Swap the backend. For tests, and for the S3 wiring when it lands."""
    global _store
    _store = store
