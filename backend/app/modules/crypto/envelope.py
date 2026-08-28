"""Reference implementation of the DCP encryption envelope.

Normative for the Kotlin implementation in shared/core. Spec:
specs/encryption-envelope-v0.1.md.

Design summary: the unit of encryption is the operation VALUE, not the
submission, so operation-based sync (resumability, merge, tombstones) keeps
working. Each device holds its own content key per submission, which makes
peer-to-peer contribution possible and lets nonces be derived deterministically
without cross-device coordination.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

ENVELOPE_VERSION = 1

WRAP_INFO = b"dcp/v1/wrap"
OP_NONCE_INFO = b"dcp/v1/op-nonce"
MEDIA_NONCE_INFO = b"dcp/v1/media-nonce"

CONTENT_KEY_BYTES = 32
NONCE_BYTES = 12
MEDIA_CHUNK_BYTES = 4 * 1024 * 1024


class EnvelopeError(Exception):
    """Raised when an envelope is malformed, or authentication fails."""


# ---------------------------------------------------------------------------
# Canonical JSON (spec 5.1)
# ---------------------------------------------------------------------------


def canonical_json(value: Any) -> bytes:
    """Serialise a value identically on every platform.

    Without this, the same answer produces different ciphertext on Android and
    iOS and cross-platform test vectors become impossible to write.
    """
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# Nonce derivation (spec 4.5, 6)
# ---------------------------------------------------------------------------


def op_nonce(device_id: str, counter: int) -> bytes:
    """Deterministic per-operation nonce.

    Safe because each device owns its own content key: a nonce can only repeat
    if a device reuses a logical counter, which the sync protocol already
    forbids. Derivation avoids depending on device RNG quality, which on cheap
    Android hardware is not something to rely on.
    """
    if counter < 0:
        raise EnvelopeError("counter must be non-negative")
    material = OP_NONCE_INFO + device_id.encode("utf-8") + counter.to_bytes(8, "big")
    return hashlib.sha256(material).digest()[:NONCE_BYTES]


def media_nonce(media_id: str, chunk_index: int) -> bytes:
    material = (
        MEDIA_NONCE_INFO + media_id.encode("utf-8") + chunk_index.to_bytes(8, "big")
    )
    return hashlib.sha256(material).digest()[:NONCE_BYTES]


# ---------------------------------------------------------------------------
# Key wrapping (spec 4.4)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WrappedKey:
    project_key_id: str
    content_key_id: str
    ephemeral_public: bytes
    nonce: bytes
    wrapped_key: bytes

    def to_dict(self) -> dict[str, Any]:
        return {
            "projectKeyId": self.project_key_id,
            "contentKeyId": self.content_key_id,
            "ephemeralPublic": self.ephemeral_public.hex(),
            "nonce": self.nonce.hex(),
            "wrappedKey": self.wrapped_key.hex(),
        }


def _wrapping_key(shared: bytes, recipient_public: bytes, content_key_id: str) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=recipient_public,
        info=WRAP_INFO + content_key_id.encode("utf-8"),
    ).derive(shared)


def wrap_content_key(
    content_key: bytes,
    content_key_id: str,
    recipient_public_key: bytes,
    project_key_id: str,
    *,
    ephemeral_private: X25519PrivateKey | None = None,
    nonce: bytes | None = None,
) -> WrappedKey:
    """Wrap a content key to one recipient.

    ``ephemeral_private`` and ``nonce`` are injectable so conformance vectors
    can pin them; production callers must leave both as None.
    """
    if len(content_key) != CONTENT_KEY_BYTES:
        raise EnvelopeError(f"content key must be {CONTENT_KEY_BYTES} bytes")

    ephemeral_private = ephemeral_private or X25519PrivateKey.generate()
    ephemeral_public = ephemeral_private.public_key().public_bytes_raw()

    shared = ephemeral_private.exchange(X25519PublicKey.from_public_bytes(recipient_public_key))
    wrapping_key = _wrapping_key(shared, recipient_public_key, content_key_id)

    nonce = nonce or AESGCM.generate_key(bit_length=128)[:NONCE_BYTES]
    aad = project_key_id.encode("utf-8") + content_key_id.encode("utf-8")
    wrapped = AESGCM(wrapping_key).encrypt(nonce, content_key, aad)

    return WrappedKey(
        project_key_id=project_key_id,
        content_key_id=content_key_id,
        ephemeral_public=ephemeral_public,
        nonce=nonce,
        wrapped_key=wrapped,
    )


def wrap_to_recipients(
    content_key: bytes,
    content_key_id: str,
    recipients: dict[str, bytes],
) -> list[WrappedKey]:
    """Wrap to every active project key (spec 4.3).

    Lost private key means permanently unrecoverable data. Multi-recipient
    wrapping is the answer to that; a server-side escrow would reintroduce the
    trust the mode exists to remove.
    """
    if not recipients:
        raise EnvelopeError("at least one recipient key is required")
    return [
        wrap_content_key(content_key, content_key_id, public, key_id)
        for key_id, public in recipients.items()
    ]


def unwrap_content_key(wrapped: WrappedKey, recipient_private_key: bytes) -> bytes:
    private = X25519PrivateKey.from_private_bytes(recipient_private_key)
    recipient_public = private.public_key().public_bytes_raw()

    shared = private.exchange(X25519PublicKey.from_public_bytes(wrapped.ephemeral_public))
    wrapping_key = _wrapping_key(shared, recipient_public, wrapped.content_key_id)

    aad = wrapped.project_key_id.encode("utf-8") + wrapped.content_key_id.encode("utf-8")
    try:
        return AESGCM(wrapping_key).decrypt(wrapped.nonce, wrapped.wrapped_key, aad)
    except Exception as exc:
        raise EnvelopeError("content key unwrap failed") from exc


# ---------------------------------------------------------------------------
# Operation values (spec 5)
# ---------------------------------------------------------------------------


def _op_aad(op_id: str, submission_id: str, path: str, form_version: int) -> bytes:
    """Bind a ciphertext to its exact location.

    Without `path` in the AAD, a server operator could move an encrypted answer
    from `income` to `age` and the client would decrypt it without complaint.
    Without `form_version`, a ciphertext could be replayed against a version of
    the form where the same path means something else.
    """
    return b"|".join(
        [
            op_id.encode("utf-8"),
            submission_id.encode("utf-8"),
            path.encode("utf-8"),
            str(form_version).encode("utf-8"),
        ]
    )


def encrypt_op_value(
    value: Any,
    content_key: bytes,
    *,
    op_id: str,
    submission_id: str,
    path: str,
    form_version: int,
    device_id: str,
    counter: int,
) -> tuple[bytes, bytes]:
    """Encrypt one operation value. Returns (ciphertext, nonce)."""
    nonce = op_nonce(device_id, counter)
    aad = _op_aad(op_id, submission_id, path, form_version)
    ciphertext = AESGCM(content_key).encrypt(nonce, canonical_json(value), aad)
    return ciphertext, nonce


def decrypt_op_value(
    ciphertext: bytes,
    nonce: bytes,
    content_key: bytes,
    *,
    op_id: str,
    submission_id: str,
    path: str,
    form_version: int,
) -> Any:
    aad = _op_aad(op_id, submission_id, path, form_version)
    try:
        plaintext = AESGCM(content_key).decrypt(nonce, ciphertext, aad)
    except Exception as exc:
        raise EnvelopeError("operation value authentication failed") from exc
    return json.loads(plaintext.decode("utf-8"))


# ---------------------------------------------------------------------------
# Media (spec 6)
# ---------------------------------------------------------------------------


def encrypt_media_chunk(
    chunk: bytes, media_key: bytes, *, media_id: str, chunk_index: int
) -> tuple[bytes, bytes]:
    nonce = media_nonce(media_id, chunk_index)
    aad = media_id.encode("utf-8") + chunk_index.to_bytes(8, "big")
    return AESGCM(media_key).encrypt(nonce, chunk, aad), nonce


def decrypt_media_chunk(
    ciphertext: bytes, media_key: bytes, *, media_id: str, chunk_index: int
) -> bytes:
    nonce = media_nonce(media_id, chunk_index)
    aad = media_id.encode("utf-8") + chunk_index.to_bytes(8, "big")
    try:
        return AESGCM(media_key).decrypt(nonce, ciphertext, aad)
    except Exception as exc:
        raise EnvelopeError("media chunk authentication failed") from exc


def ciphertext_hash(ciphertext_chunks: list[bytes]) -> str:
    """Content address computed over CIPHERTEXT, never plaintext.

    Hashing plaintext would let the server confirm that two submissions contain
    the same photograph — exactly the inference end-to-end encryption exists to
    prevent.
    """
    digest = hashlib.sha256()
    for chunk in ciphertext_chunks:
        digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Sensitivity propagation (spec 5.2)
# ---------------------------------------------------------------------------


def check_sensitivity_propagation(compiled_form: Any) -> list[str]:
    """A calculated field reading a sensitive field must itself be sensitive.

    Otherwise the calculation leaks its input. Returns violation messages; an
    empty list means the form is safe to publish in field_level mode.
    """
    violations: list[str] = []
    for field_id, field in compiled_form.fields.items():
        if field.node.get("sensitive") is True:
            continue
        for dep in field.depends_on:
            base = dep.split("[")[0].split(".")[-1] if "]." in dep else dep
            dep_field = compiled_form.fields.get(base)
            if dep_field is not None and dep_field.node.get("sensitive") is True:
                violations.append(
                    f"{field_id!r} is not sensitive but depends on sensitive field {base!r}"
                )
    return violations
