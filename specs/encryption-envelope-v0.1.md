# Encryption Envelope Specification v0.1

**Status:** Draft — Phase 0
**Depends on:** Sync Protocol v0.1 (operation model), Form IR v0.1 (field paths)
**Reference implementation:** `backend/app/modules/crypto/envelope.py`

This specification defines how submission data is encrypted so that the server
cannot read it, while operation-based synchronisation continues to work.

---

## 1. Security modes

A project runs in exactly one mode. The mode is fixed at project creation and
cannot be changed afterwards — changing it would require re-encrypting or
decrypting historical data, which defeats the purpose of having chosen it.

| Mode | What is encrypted | What the server can do |
|---|---|---|
| `standard` | Storage-level at rest only | Everything: validation, quality checks, dashboards, exports |
| `field_level` | Values of fields marked `sensitive: true` | Everything except read the sensitive values. Monitoring and QC on non-sensitive fields still work |
| `project_e2e` | Every operation value and every media file | Route, store and order operations. Read nothing |

`field_level` is expected to be the common choice for health and identifying
data. It is the mode that keeps the product useful — dashboards, duplicate
detection and quality rules keep functioning on the non-sensitive remainder.

`project_e2e` exists for ethics-board and IRB-governed research where the
guarantee has to be absolute. **Server-side validation, quality checks,
dashboards and server-side calculations are unavailable in this mode.** That is
a deliberate trade, not a limitation to be worked around later.

---

## 2. Primitives

| Purpose | Algorithm | Note |
|---|---|---|
| Key agreement | **X25519** | Small keys, constant-time, available identically on JVM, Kotlin/Native, Python and Wasm via libsodium |
| Key wrapping | X25519 + HKDF-SHA256 → AES-256-GCM | Ephemeral sender key per wrap |
| Content encryption | **AES-256-GCM** | 96-bit nonce, 128-bit tag |
| Hashing | SHA-256 | Media content addressing |
| Key derivation | HKDF-SHA256 | Domain-separated by a fixed info string |

X25519 is chosen over RSA-2048 deliberately. SurveyCTO uses RSA-2048 and IRB
reviewers are familiar with it, but familiarity is not a sufficient reason to
adopt a larger, slower primitive. X25519 keys are 32 bytes and the operation is
fast enough to run per-op on a low-end Android device.

**No algorithm agility.** There is no ciphersuite negotiation. The envelope
carries a `version` field; a future version may specify different primitives,
and implementations reject versions they do not know. Negotiation is a common
source of downgrade attacks and buys nothing here.

---

## 3. The core problem this design solves

SurveyCTO encrypts one submission as one blob at finalisation. That is simple
because their sync model uploads whole submissions.

Our sync model is an **operation log**: each answer is a separate operation, so
uploads are resumable, mergeable across devices, and produce a correction audit
trail for free (Sync Protocol §2).

Encrypting the whole submission as a single blob would destroy all of that.
So the unit of encryption is the **operation value**, not the submission.

```
Operation (project_e2e mode)
┌──────────────────────────────────────────────────┐
│ opId, submissionId, formVersion   ← plaintext    │
│ path  = "members[i3].age"         ← plaintext    │
│ counter, deviceId, wallClock      ← plaintext    │
│ keyId                             ← plaintext    │
│ nonce                             ← plaintext    │
│ valueCiphertext                   ← ENCRYPTED    │
└──────────────────────────────────────────────────┘
```

### 3.1 What this leaks, stated plainly

The server learns: which field paths were answered, when, by which device, in
what order, and how long the interview took. It does not learn any answer.

This is an accepted trade. Personal and health information lives in values, not
in field paths. Field paths come from the form definition, which the server
already holds.

**It must be documented for ethics review, not hidden.** If a project's field
paths are themselves sensitive — a form where the presence of an answer to
`hiv_status_confirmed` is disclosive regardless of its value — then
`project_e2e` at the operation level is not sufficient and the project should
not use this platform for that data.

---

## 4. Keys

### 4.1 Project keypair

Generated in the browser at project creation. The private key is downloaded by
the user and **never transmitted to the server**.

```
project_key
  key_id          ULID
  project_id
  public_key      32 bytes, X25519
  role            'primary' | 'backup' | 'recovery'
  label           human-readable, e.g. "Programme lead — Fatima"
  created_at
  revoked_at      nullable
```

Multiple active keys per project are normal — see §4.3.

### 4.2 Content keys, one per device per submission

Each device generates its **own** content key for each submission it
contributes to.

This is not a convenience. It follows from two requirements:

**Peer-to-peer transfer.** A device receiving a submission from a peer holds
only the project public key, so it cannot unwrap another device's content key.
It must be able to add operations regardless.

**Nonce safety.** AES-GCM catastrophically fails on nonce reuse. Because each
device owns its own key, nonces can be derived deterministically from
`(deviceId, counter)` with no coordination and no possibility of collision
between devices. A random nonce per op would work too, but derivation removes
the dependency on device RNG quality, which on cheap Android hardware is not
something to rely on.

```
submission_content_key
  key_id             ULID — referenced by every operation it encrypts
  submission_id
  device_id
  created_at
```

The content key itself is never stored server-side in plaintext form. Only its
wrapped copies are (§4.3).

### 4.3 Wrapping, multi-recipient

A content key is wrapped **once per active project key**.

```
submission_wrapped_key
  submission_id
  content_key_id
  project_key_id     which recipient this wrap is for
  ephemeral_public   32 bytes
  nonce              12 bytes
  wrapped_key        48 bytes (32-byte key + 16-byte GCM tag)
```

Each wrap costs 92 bytes. Wrapping to three recipients costs under 300 bytes
per submission per device — negligible.

**Why multi-recipient is in v0.1 rather than deferred:** lost private key means
permanently unrecoverable data. That is the honest consequence of end-to-end
encryption and it will happen to a real customer. The correct answer is not a
server-side escrow — that reintroduces the trust we removed — but wrapping to
more than one recipient key. Adding this later is a schema migration on
historical data, so it goes in from the start.

### 4.4 Wrap construction

```
ephemeral_private, ephemeral_public = X25519.generate()
shared          = X25519(ephemeral_private, recipient_public)
wrapping_key    = HKDF-SHA256(
                      ikm  = shared,
                      salt = recipient_public,
                      info = "dcp/v1/wrap" || content_key_id,
                      len  = 32)
nonce           = random(12)
wrapped_key     = AES-256-GCM(wrapping_key, nonce, content_key,
                              aad = project_key_id || content_key_id)
```

The `aad` binds the wrap to its recipient and content key, so a wrap cannot be
transplanted between submissions or recipients.

### 4.5 Nonce derivation for operation values

```
nonce = SHA-256("dcp/v1/op-nonce" || device_id || counter)[0:12]
```

`counter` is the device's monotonic logical counter and never resets
(Sync Protocol §2). Each device has its own content key, so a nonce can only
repeat if a device reuses a counter — which is already forbidden because
operation ordering depends on it.

**Implementations MUST reject an operation whose `(key_id, nonce)` pair has
already been recorded.** The server can enforce this without decrypting
anything, and it is the last line of defence against a device with a broken
counter.

---

## 5. Operation value encryption

```
plaintext   = canonical_json(value)          // §5.1
aad         = op_id || submission_id || path || form_version
ciphertext  = AES-256-GCM(content_key, nonce, plaintext, aad)
```

Binding `path` into the `aad` means a ciphertext cannot be moved from one field
to another. Without it, a server operator could relocate an encrypted answer
from `income` to `age` and the client would decrypt it without complaint.

Binding `form_version` means a ciphertext cannot be replayed against a different
version of the form where the same path means something else.

### 5.1 Canonical JSON

Values must serialise identically on every platform, or the same answer produces
different ciphertext and cross-platform tests become impossible to write.

- UTF-8, no BOM
- Object keys sorted by Unicode code point
- No insignificant whitespace
- Integers without a decimal point; decimals in the shortest round-tripping form
- `null` for absent values

### 5.2 Field-level mode

Identical construction, applied only to fields whose IR node carries
`"sensitive": true`. Non-sensitive operation values are stored in plaintext.

One consequence to be explicit about: a **calculated** field that reads a
sensitive field must itself be marked sensitive, or the calculation leaks the
input. The form compiler MUST propagate sensitivity through the dependency
graph and refuse to publish a form where a non-sensitive field depends on a
sensitive one.

This is a compile-time check and belongs in the linter (Form IR §10).

---

## 6. Media

Each media file gets its **own** content key, independent of the operation key.

```
media_key = random(32)
ciphertext = AES-256-GCM(media_key, nonce = random(12), file_bytes,
                         aad = media_id)
```

The media key is wrapped exactly as an operation content key is (§4.4), to the
same recipient set.

Per-file keys rather than one submission key because:
- Chunked resumable upload can encrypt and upload chunks independently
- A single media file can later be shared with a third party without disclosing
  the rest of the submission
- A corrupted upload affects one file

**Content addressing:** the `hash` used for deduplication and resumption is
computed over the **ciphertext**, not the plaintext. Hashing plaintext would let
the server confirm whether two submissions contain the same photograph, which
is exactly the kind of inference end-to-end encryption exists to prevent.

Chunk size is fixed at 4 MiB. Each chunk is encrypted independently with
`nonce = SHA-256("dcp/v1/media-nonce" || media_id || chunk_index)[0:12]`.

---

## 7. Decryption

Decryption happens only in the browser (Wasm) or the desktop application. The
private key is loaded into memory for the session and never persisted by the
application, never sent to the server, and never written to logs.

```
1. Load private key (file or hardware token)
2. Fetch wrapped keys for the submission, filtered to keys this private key can open
3. Unwrap each content key
4. Fetch operations; for each, decrypt value with the content key named by key_id
5. Fold the operation log into materialised state (Sync Protocol §2)
6. Render
```

Decryption of a submission requires **every** content key that contributed
operations to it. A submission built by two devices via peer-to-peer transfer
has two content keys, both wrapped to the same recipients, so a single private
key opens both.

---

## 8. Key rotation and revocation

**Rotation** adds a new project key and marks the old one revoked. New
submissions wrap to the new key set. **Historical submissions are not
re-wrapped** — the server cannot, since it cannot unwrap them. Holding the old
private key remains necessary to read old data.

This must be stated plainly in the product UI at rotation time. A customer who
rotates and then discards the old private key has destroyed their historical
data.

**Revocation** stops future wrapping to that key. It does not and cannot
invalidate wraps already produced.

---

## 9. Storage schema implications

These feed directly into the ERD.

```
project
  security_mode          'standard' | 'field_level' | 'project_e2e'

project_key
  key_id, project_id, public_key, role, label, created_at, revoked_at

submission_content_key
  key_id, submission_id, device_id, created_at

submission_wrapped_key
  submission_id, content_key_id, project_key_id,
  ephemeral_public, nonce, wrapped_key

submission_op
  op_id, submission_id, form_id, form_version, path,
  counter, device_id, wall_clock,
  value                  -- plaintext, NULL when encrypted
  value_ciphertext       -- NULL when plaintext
  content_key_id         -- NULL when plaintext
  nonce                  -- NULL when plaintext
  UNIQUE (content_key_id, nonce)   -- enforces §4.5

media
  media_id, submission_id, ciphertext_hash, size, chunk_count,
  content_key_id, encrypted BOOLEAN
```

The `UNIQUE (content_key_id, nonce)` constraint is the database-level
enforcement of nonce uniqueness. It costs one index and removes an entire class
of catastrophic failure.

Note that `submission_op` carries both a plaintext and a ciphertext column.
A project in `field_level` mode uses both, per operation, depending on whether
that field is marked sensitive.

---

## 10. What breaks in `project_e2e` mode

Stated explicitly so it is designed for rather than discovered:

| Feature | Status in `project_e2e` |
|---|---|
| Server-side validation | Unavailable — client validation only |
| Automated quality rules | Unavailable |
| Duplicate detection | Unavailable |
| Dashboards and charts | Metadata only (counts, timing, submission rate) |
| Text audits | Available — timing metadata is not encrypted |
| Audio audits | Available but encrypted; reviewable only after client-side decryption |
| Exports | Client-side only, in browser or desktop |
| Review workflow | Available for status transitions; a reviewer must decrypt locally to see values |
| Case pre-population from prior rounds | Unavailable server-side |

The product must surface these as a checklist when a project is created in this
mode, not as small print.

---

## 11. Threat model

**In scope.** A malicious or compromised server operator; database exfiltration;
backup theft; a subpoena served on the hosting provider; a lost or stolen
device.

**Out of scope.** A compromised client device *during* an active session; a
malicious enumerator who can see the data they collect by definition; traffic
analysis of operation metadata (§3.1); coercion of a private key holder.

**Explicitly not claimed.** This does not protect against a supervisor with
legitimate access exporting data. Access control is a separate mechanism.

---

## 12. Test vectors

Cryptographic behaviour is verified like form semantics: language-neutral
vectors that every implementation must reproduce.

`conformance/crypto/*.json`, containing fixed keys, fixed nonces, plaintexts and
expected ciphertexts. Both the Python reference and the Kotlin implementation
must produce byte-identical output.

Fixed test keys are marked `TEST ONLY` and must never appear outside the
conformance directory.

---

## 13. Open questions for v0.2

- Hardware token support (YubiKey / PIV) for private key custody
- Whether `field_level` should encrypt to a separate, narrower recipient set than the project keys
- Threshold schemes (k-of-n) as an alternative to multi-recipient wrapping
- Whether audio audit files warrant a separate key hierarchy, since they are reviewed far more often than submission data
- Post-quantum key agreement — X25519 is not PQ-safe; a hybrid X25519+ML-KEM wrap is the likely migration path
