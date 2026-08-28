"""Runs every crypto conformance vector against the Python reference envelope.

The Kotlin implementation runs the same vectors from shared/core. The vectors
are generated FROM this reference (conformance/generate_crypto_vectors.py), so
here they guard against regressions; the cross-implementation guarantee is that
Kotlin reproduces the same bytes. Any divergence is a release blocker.
"""

from __future__ import annotations

import json
import pathlib

import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from app.modules.crypto import envelope
from app.modules.crypto.envelope import EnvelopeError, WrappedKey

VECTOR_DIR = pathlib.Path(__file__).resolve().parents[2] / "conformance" / "crypto"
VECTORS = sorted(VECTOR_DIR.glob("*.json"))

assert VECTORS, f"no crypto conformance vectors found in {VECTOR_DIR}"


def _load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text())


def _check_canonical_json(vector: dict) -> None:
    for case in vector["cases"]:
        got = envelope.canonical_json(case["value"])
        assert got == bytes.fromhex(case["expected"]), f"canonical_json[{case['name']}]"


def _check_op_nonce(vector: dict) -> None:
    for case in vector["cases"]:
        if case.get("expectError"):
            with pytest.raises(EnvelopeError):
                envelope.op_nonce(case["deviceId"], case["counter"])
            continue
        got = envelope.op_nonce(case["deviceId"], case["counter"])
        assert got == bytes.fromhex(case["expected"]), f"op_nonce[{case['deviceId']}]"


def _check_media_nonce(vector: dict) -> None:
    for case in vector["cases"]:
        got = envelope.media_nonce(case["mediaId"], case["chunkIndex"])
        assert got == bytes.fromhex(case["expected"])


def _check_wrap(vector: dict) -> None:
    for case in vector["cases"]:
        content_key = bytes.fromhex(case["contentKey"])
        wrapped = envelope.wrap_content_key(
            content_key,
            case["contentKeyId"],
            bytes.fromhex(case["recipientPublicKey"]),
            case["projectKeyId"],
            ephemeral_private=X25519PrivateKey.from_private_bytes(
                bytes.fromhex(case["ephemeralPrivateKey"])
            ),
            nonce=bytes.fromhex(case["nonce"]),
        )
        assert wrapped.ephemeral_public == bytes.fromhex(case["expected"]["ephemeralPublic"])
        assert wrapped.wrapped_key == bytes.fromhex(case["expected"]["wrappedKey"])

        private = bytes.fromhex(case["recipientPrivateKey"])
        assert envelope.unwrap_content_key(wrapped, private) == content_key

        for tamper in case.get("tamper", []):
            fields = {
                "project_key_id": wrapped.project_key_id,
                "content_key_id": wrapped.content_key_id,
                "ephemeral_public": wrapped.ephemeral_public,
                "nonce": wrapped.nonce,
                "wrapped_key": wrapped.wrapped_key,
            }
            key = {"projectKeyId": "project_key_id", "contentKeyId": "content_key_id"}[
                tamper["field"]
            ]
            fields[key] = tamper["value"]
            with pytest.raises(EnvelopeError):
                envelope.unwrap_content_key(WrappedKey(**fields), private)


def _check_op_value(vector: dict) -> None:
    for case in vector["cases"]:
        content_key = bytes.fromhex(case["contentKey"])
        params = {
            "op_id": case["opId"],
            "submission_id": case["submissionId"],
            "path": case["path"],
            "form_version": case["formVersion"],
        }
        ciphertext, nonce = envelope.encrypt_op_value(
            case["value"],
            content_key,
            **params,
            device_id=case["deviceId"],
            counter=case["counter"],
        )
        assert nonce == bytes.fromhex(case["expected"]["nonce"]), case["name"]
        assert ciphertext == bytes.fromhex(case["expected"]["ciphertext"]), case["name"]

        assert envelope.decrypt_op_value(ciphertext, nonce, content_key, **params) == case["value"]

        camel = {
            "opId": "op_id",
            "submissionId": "submission_id",
            "path": "path",
            "formVersion": "form_version",
        }
        for tamper in case.get("tamper", []):
            tampered = {**params, camel[tamper["field"]]: tamper["value"]}
            with pytest.raises(EnvelopeError):
                envelope.decrypt_op_value(ciphertext, nonce, content_key, **tampered)


def _check_media(vector: dict) -> None:
    media_key = bytes.fromhex(vector["mediaKey"])
    media_id = vector["mediaId"]
    ciphertexts = []
    for case in vector["chunks"]:
        plaintext = bytes.fromhex(case["plaintext"])
        ciphertext, nonce = envelope.encrypt_media_chunk(
            plaintext, media_key, media_id=media_id, chunk_index=case["chunkIndex"]
        )
        assert nonce == bytes.fromhex(case["expected"]["nonce"])
        assert ciphertext == bytes.fromhex(case["expected"]["ciphertext"])
        assert (
            envelope.decrypt_media_chunk(
                ciphertext, media_key, media_id=media_id, chunk_index=case["chunkIndex"]
            )
            == plaintext
        )
        # A chunk must not decrypt at a different index. Checked far outside
        # the chunk range: BouncyCastle (Kotlin JVM runner) records the nonce
        # of every cipher init and refuses a later encryption with it, so the
        # probe index must never collide with a real chunk's nonce.
        with pytest.raises(EnvelopeError):
            envelope.decrypt_media_chunk(
                ciphertext, media_key, media_id=media_id, chunk_index=case["chunkIndex"] + 100
            )
        ciphertexts.append(ciphertext)

    assert envelope.ciphertext_hash(ciphertexts) == vector["expectedCiphertextHash"]


_CHECKS = {
    "canonical_json": _check_canonical_json,
    "op_nonce": _check_op_nonce,
    "media_nonce": _check_media_nonce,
    "wrap": _check_wrap,
    "op_value": _check_op_value,
    "media": _check_media,
}


@pytest.mark.parametrize("vector_path", VECTORS, ids=lambda p: p.stem)
def test_vector(vector_path: pathlib.Path) -> None:
    vector = _load(vector_path)
    assert vector["envelopeVersion"] == envelope.ENVELOPE_VERSION
    _CHECKS[vector["type"]](vector)
