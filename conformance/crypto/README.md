# Crypto Conformance Vectors

Language-neutral test vectors for the encryption envelope
(`specs/encryption-envelope-v0.1.md` §12). Every implementation must reproduce
every byte:

- Python reference: `backend/app/modules/crypto/envelope.py`,
  runner `backend/tests/test_crypto_conformance.py`
- Kotlin: `shared/core` (`com.dcp.core.crypto`),
  runner `shared/core/src/jvmTest/kotlin/com/dcp/core/crypto/CryptoConformanceTest.kt`

A vector passing on one implementation and failing on the other is a release
blocker, never a platform difference. Never "fix" a failing vector by editing
the expectation — regenerate only alongside a deliberate spec change.

Vectors are generated from the reference implementation:

```bash
backend/.venv/bin/python conformance/generate_crypto_vectors.py
```

## ⚠ TEST ONLY key material

Every key, nonce and ephemeral scalar in these files is fixed and public **by
design** — that is what makes the expected ciphertext reproducible. None of
these values may ever appear outside `conformance/`. Production code paths
never accept caller-supplied ephemeral keys or wrap nonces; the injection
parameters exist solely for these vectors.

## Vector types

| `type` | Proves | Spec |
|---|---|---|
| `canonical_json` | Identical plaintext bytes on every platform: Python-repr float formatting, code-point key order, minimal escaping, UTF-8 | 5.1 |
| `op_nonce` | Deterministic operation nonce from `(deviceId, counter)` | 4.5 |
| `media_nonce` | Deterministic chunk nonce from `(mediaId, chunkIndex)` | 6 |
| `wrap` | X25519 + HKDF-SHA256 → AES-256-GCM key wrap, AAD binding to recipient and content key, unwrap roundtrip | 4.3, 4.4 |
| `op_value` | Operation value encryption, AAD binding to `opId\|submissionId\|path\|formVersion`, tamper rejection | 5 |
| `media` | Per-chunk media encryption and content addressing over ciphertext | 6 |

`tamper` entries list field substitutions that MUST make authentication fail;
`expectError` marks inputs that MUST be rejected before any crypto runs.
