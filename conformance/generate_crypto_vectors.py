"""Generates the crypto conformance vectors in conformance/crypto.

Expected outputs are produced by the reference implementation
(backend/app/modules/crypto/envelope.py), so regenerating after a reference
change is deliberate and reviewable. The Kotlin implementation must reproduce
every byte. Run: backend/.venv/bin/python conformance/generate_crypto_vectors.py

ALL KEY MATERIAL IN THIS FILE IS TEST ONLY. The keys and nonces are fixed and
public by design; none of them may ever appear outside conformance/.
"""

import json
import pathlib
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from app.modules.crypto import envelope

OUT = pathlib.Path(__file__).parent / "crypto"

WARNING = (
    "TEST ONLY - fixed keys and nonces, public by design. "
    "Never use any value from this file outside conformance testing."
)


def tb(seed: int, n: int) -> bytes:
    """Deterministic filler bytes so vectors are reproducible."""
    return bytes((seed + 7 * i) % 256 for i in range(n))


def x25519_keypair(seed: int) -> tuple[bytes, bytes]:
    private = tb(seed, 32)
    public = X25519PrivateKey.from_private_bytes(private).public_key().public_bytes_raw()
    return private, public


CONTENT_KEY = tb(0x11, 32)
CONTENT_KEY_ID = "01J9TESTCONTENTKEY0000000A"
MEDIA_KEY = tb(0x55, 32)

# Recipient project keys, one per role (spec 4.1/4.3).
RECIPIENTS = {}
for role, seed in [("primary", 0x40), ("backup", 0x60), ("recovery", 0x80)]:
    private, public = x25519_keypair(seed)
    RECIPIENTS[role] = {
        "projectKeyId": f"01J9TESTPROJECTKEY{role.upper():0>8}"[:26],
        "privateKey": private.hex(),
        "publicKey": public.hex(),
    }

VECTORS: list[dict[str, Any]] = []


def vector(vid: str, vtype: str, description: str, spec: str, **body: Any) -> None:
    VECTORS.append(
        {
            "id": vid,
            "type": vtype,
            "description": description,
            "spec": spec,
            "envelopeVersion": envelope.ENVELOPE_VERSION,
            "warning": WARNING,
            **body,
        }
    )


# ---------------------------------------------------------------------------
# Canonical JSON (spec 5.1)
# ---------------------------------------------------------------------------

SCALAR_CASES = [
    ("null", None),
    ("true", True),
    ("false", False),
    ("zero", 0),
    ("negative int", -17),
    ("large int", 1234567890123456789),
    ("simple decimal", 3.14),
    ("half", 0.5),
    ("negative small decimal", -0.0075),
    ("integral float keeps .0", 100.0),
    ("fixed threshold high", 9999999999999998.0),
    ("scientific high", 1e16),
    ("scientific high mantissa", 1.5e16),
    ("fixed threshold low", 0.0001),
    ("scientific low", 1e-05),
    ("negative zero float", -0.0),
    ("ascii string", "hello"),
    ("unicode string", "héllo ✓ عربي"),
    ("emoji surrogate pair", "family 👍"),
    ("escapes", 'quote " backslash \\ newline \n tab \t'),
    ("control char", "bell \x07 unit sep \x1f"),
]

STRUCTURE_CASES: list[tuple[str, Any]] = [
    ("empty object", {}),
    ("empty array", []),
    ("key sorting ascii", {"b": 1, "a": 2, "B": 3, "1": 4}),
    ("key sorting unicode", {"é": 1, "e": 2, "z": 3}),
    # U+FF61 sorts before U+1F600 by code point; a UTF-16 comparison would
    # order them the other way. This is the case that catches it.
    ("key sorting beyond bmp", {"\U0001F600": "emoji", "｡": "halfwidth"}),
    ("nested", {"person": {"name": "Amina", "age": 34, "tags": ["a", "b"]}}),
    ("array mixed", [None, True, 0, -1.5, "x", {"k": []}]),
    ("rtl values", {"الاسم": "أمينة", "المدينة": "عمّان"}),
]


def canonical_cases(pairs: list[tuple[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"name": name, "value": value, "expected": envelope.canonical_json(value).hex()}
        for name, value in pairs
    ]


vector(
    "canonical-json-001",
    "canonical_json",
    "Scalar canonicalisation: Python repr float formatting, UTF-8, escapes",
    "5.1",
    cases=canonical_cases(SCALAR_CASES),
)

vector(
    "canonical-json-002",
    "canonical_json",
    "Structural canonicalisation: code-point key order, no whitespace, nesting",
    "5.1",
    cases=canonical_cases(STRUCTURE_CASES),
)

# ---------------------------------------------------------------------------
# Nonce derivation (spec 4.5, 6)
# ---------------------------------------------------------------------------

OP_NONCE_CASES = [
    ("device-a", 0),
    ("device-a", 1),
    ("device-a", 2**40),
    ("device-b", 0),
    ("جهاز-١", 7),
]

vector(
    "op-nonce-001",
    "op_nonce",
    "Deterministic operation nonces from (deviceId, counter)",
    "4.5",
    cases=[
        {"deviceId": device_id, "counter": counter,
         "expected": envelope.op_nonce(device_id, counter).hex()}
        for device_id, counter in OP_NONCE_CASES
    ]
    + [{"deviceId": "device-a", "counter": -1, "expectError": True}],
)

MEDIA_NONCE_CASES = [
    ("01J9TESTMEDIA000000000000A", 0),
    ("01J9TESTMEDIA000000000000A", 1),
    ("01J9TESTMEDIA000000000000A", 255),
    ("01J9TESTMEDIA000000000000B", 0),
]

vector(
    "media-nonce-001",
    "media_nonce",
    "Deterministic media chunk nonces from (mediaId, chunkIndex)",
    "6",
    cases=[
        {"mediaId": media_id, "chunkIndex": index,
         "expected": envelope.media_nonce(media_id, index).hex()}
        for media_id, index in MEDIA_NONCE_CASES
    ],
)

# ---------------------------------------------------------------------------
# Key wrapping (spec 4.4) and multi-recipient (spec 4.3)
# ---------------------------------------------------------------------------


def wrap_case(
    recipient: dict[str, Any], eph_seed: int, nonce_seed: int
) -> dict[str, Any]:
    ephemeral_private = tb(eph_seed, 32)
    nonce = tb(nonce_seed, 12)
    wrapped = envelope.wrap_content_key(
        CONTENT_KEY,
        CONTENT_KEY_ID,
        bytes.fromhex(recipient["publicKey"]),
        recipient["projectKeyId"],
        ephemeral_private=X25519PrivateKey.from_private_bytes(ephemeral_private),
        nonce=nonce,
    )
    assert envelope.unwrap_content_key(
        wrapped, bytes.fromhex(recipient["privateKey"])
    ) == CONTENT_KEY
    return {
        "contentKey": CONTENT_KEY.hex(),
        "contentKeyId": CONTENT_KEY_ID,
        "projectKeyId": recipient["projectKeyId"],
        "recipientPublicKey": recipient["publicKey"],
        "recipientPrivateKey": recipient["privateKey"],
        "ephemeralPrivateKey": ephemeral_private.hex(),
        "nonce": nonce.hex(),
        "expected": {
            "ephemeralPublic": wrapped.ephemeral_public.hex(),
            "wrappedKey": wrapped.wrapped_key.hex(),
        },
        # The AAD binds the wrap to its recipient and content key; changing
        # either must make unwrap fail authentication.
        "tamper": [
            {"field": "projectKeyId", "value": "01J9TESTPROJECTKEYEVIL0000"},
            {"field": "contentKeyId", "value": "01J9TESTCONTENTKEY0000000B"},
        ],
    }


vector(
    "wrap-001",
    "wrap",
    "X25519 + HKDF-SHA256 + AES-256-GCM content key wrap, single recipient",
    "4.4",
    cases=[wrap_case(RECIPIENTS["primary"], eph_seed=0xA0, nonce_seed=0xB0)],
)

vector(
    "wrap-multi-001",
    "wrap",
    "One content key wrapped to three project keys; each private key unwraps it",
    "4.3",
    cases=[
        wrap_case(RECIPIENTS["primary"], eph_seed=0xA1, nonce_seed=0xB1),
        wrap_case(RECIPIENTS["backup"], eph_seed=0xA2, nonce_seed=0xB2),
        wrap_case(RECIPIENTS["recovery"], eph_seed=0xA3, nonce_seed=0xB3),
    ],
)

# ---------------------------------------------------------------------------
# Operation value encryption (spec 5)
# ---------------------------------------------------------------------------

OP_VALUE_CASES = [
    ("string value", "Amina", "name"),
    ("int value", 34, "age"),
    ("decimal value", 12.5, "weight_kg"),
    ("null value", None, "notes"),
    ("array value", ["opt_a", "opt_c"], "symptoms"),
    ("object value", {"lat": 31.95, "lon": 35.91, "acc": 4.0}, "location"),
    ("repeat path", "أمينة", "members[i3].name"),
]


def op_value_case(
    name: str, value: Any, path: str, counter: int
) -> dict[str, Any]:
    op_id = f"01J9TESTOP{counter:016d}"
    submission_id = "01J9TESTSUBMISSION0000000A"
    device_id = "device-a"
    form_version = 3
    ciphertext, nonce = envelope.encrypt_op_value(
        value,
        CONTENT_KEY,
        op_id=op_id,
        submission_id=submission_id,
        path=path,
        form_version=form_version,
        device_id=device_id,
        counter=counter,
    )
    assert (
        envelope.decrypt_op_value(
            ciphertext, nonce, CONTENT_KEY,
            op_id=op_id, submission_id=submission_id,
            path=path, form_version=form_version,
        )
        == value
    )
    return {
        "name": name,
        "value": value,
        "contentKey": CONTENT_KEY.hex(),
        "opId": op_id,
        "submissionId": submission_id,
        "path": path,
        "formVersion": form_version,
        "deviceId": device_id,
        "counter": counter,
        "expected": {"nonce": nonce.hex(), "ciphertext": ciphertext.hex()},
        # AAD binds opId | submissionId | path | formVersion; changing any of
        # them must make decryption fail authentication.
        "tamper": [
            {"field": "path", "value": "age_moved"},
            {"field": "formVersion", "value": 4},
            {"field": "opId", "value": "01J9TESTOP9999999999999999"},
            {"field": "submissionId", "value": "01J9TESTSUBMISSION0000000B"},
        ],
    }


vector(
    "op-value-001",
    "op_value",
    "Operation value encryption: canonical JSON plaintext, derived nonce, location-bound AAD",
    "5",
    cases=[
        op_value_case(name, value, path, counter)
        for counter, (name, value, path) in enumerate(OP_VALUE_CASES)
    ],
)

# ---------------------------------------------------------------------------
# Media chunks and ciphertext hashing (spec 6)
# ---------------------------------------------------------------------------

MEDIA_ID = "01J9TESTMEDIA000000000000A"
CHUNKS = [tb(0x00, 1024), tb(0x91, 100), b""]

chunk_cases = []
ciphertexts = []
for index, chunk in enumerate(CHUNKS):
    ciphertext, nonce = envelope.encrypt_media_chunk(
        chunk, MEDIA_KEY, media_id=MEDIA_ID, chunk_index=index
    )
    assert (
        envelope.decrypt_media_chunk(
            ciphertext, MEDIA_KEY, media_id=MEDIA_ID, chunk_index=index
        )
        == chunk
    )
    ciphertexts.append(ciphertext)
    chunk_cases.append(
        {
            "chunkIndex": index,
            "plaintext": chunk.hex(),
            "expected": {"nonce": nonce.hex(), "ciphertext": ciphertext.hex()},
        }
    )

vector(
    "media-001",
    "media",
    "Per-chunk media encryption and content addressing over ciphertext",
    "6",
    mediaKey=MEDIA_KEY.hex(),
    mediaId=MEDIA_ID,
    chunks=chunk_cases,
    # Hash over ciphertext, never plaintext: hashing plaintext would let the
    # server confirm two submissions contain the same photograph.
    expectedCiphertextHash=envelope.ciphertext_hash(ciphertexts),
)

# ---------------------------------------------------------------------------

OUT.mkdir(exist_ok=True)
for v in VECTORS:
    path = OUT / f"{v['id']}.json"
    path.write_text(json.dumps(v, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(OUT.parent.parent)}")
