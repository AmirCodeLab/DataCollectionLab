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

Chunk size is fixed at 4 MiB — fixed, not negotiated, because the nonce for
chunk *n* is derived from `(media_id, n)`: two clients that disagreed about
where the boundaries fall would encrypt different plaintext under the same
nonce. Each chunk is encrypted independently with
`nonce = SHA-256("dcp/v1/media-nonce" || media_id || chunk_index)[0:12]`
and `aad = media_id || chunk_index`, so a chunk cannot be moved to another
index or into another file.

AES-GCM appends a 16-byte tag, so a full chunk is 4 MiB **+ 16 bytes** on the
wire. The 4 MiB is the plaintext chunk size; a server checking the size of what
arrives must check against the larger number.

### 6.1 Media at rest on the device

A photograph of an identity document sitting in cleartext on a phone defeats
everything §14 does for the database beside it. So media is encrypted on the
device too, and by the same mechanism that protects it in transit rather than a
second one:

```
camera buffer -> compress in memory -> encrypt in memory -> write chunks
```

- The **plaintext never reaches the filesystem** — not to a cache file, not to
  a platform MediaStore entry, not to a temporary a compressor wanted.
- The **per-file media key lives in the local database**, which is
  SQLCipher-encrypted under a key the platform keystore holds (§14). The media
  key is therefore protected by the keystore transitively, and there is no
  second key hierarchy to get wrong.
- The **staged file is the upload**: chunks are encrypted once, at capture, and
  uploaded byte for byte. A resumed upload provably sends the same bytes as the
  first attempt, and the content hash computed at capture is the one the server
  verifies.

This holds in **every security mode, including `standard`**. At-rest protection
on the device is not the project's server-side trust model: a `standard`
project trusts its own server, which says nothing about the handset left on a
clinic desk. What the mode decides is whether the *upload* carries ciphertext —
in `standard` mode the chunk is decrypted on the way out, because the server is
entitled to read it, and the hash sent is then over what was actually uploaded.

A device deletes a file's chunks once the server has sealed the upload. The
`media` row stays, so a submission can still say which file its operation names.

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
  media_id, submission_id, op_id, device_id, field_path,
  mime_type, size, chunk_count, ciphertext_hash,
  content_key_id, encrypted BOOLEAN, status, storage_key
  -- op_id is NOT a foreign key to submission_op: an operation referencing a
  -- file is accepted before the file arrives (sync §9), so the operation may
  -- genuinely not exist yet, and a constraint would turn the normal case into
  -- an error.

media_wrapped_key
  media_id, project_key_id, ephemeral_public, nonce, wrapped_key
  -- §6 gives each file its OWN content key, which cannot live in
  -- submission_content_key: that table is UNIQUE (submission_id, device_id) by
  -- design — one operation key per device per submission — and one device
  -- captures several files into one submission.

media_chunk
  media_id, chunk_index, size_bytes, chunk_hash, storage_key
  -- Rows, not a counter. Resumption has to know exactly which indexes
  -- arrived: chunks may be uploaded out of order, and re-sending from the
  -- first gap would re-send chunks the server already holds.
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

A lost or stolen device is covered by §14, not by the sections above. Everything
in §1–§10 is about what *leaves* the device. Until §14 is implemented on a
platform, a seized phone from that platform gives up every answer on it
regardless of the project's security mode, and the entry above is a claim rather
than a defence.

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

---

## 14. Local database encryption on the device

Sections 1–10 describe what leaves the device. This section describes what stays
on it. They are separate mechanisms with separate keys and separate threats, and
conflating them is the mistake this section exists to prevent.

Added after §13 rather than inserted before it so that every existing reference
to a section number in this repository still points at the same text.

### 14.1 The gap it closes

The client stores the operation log, not materialised answers (Sync Protocol §2),
and the operation log holds `value_json` in the clear. A project in
`project_e2e` mode therefore ships ciphertext to a server that cannot read it
and keeps the plaintext in a SQLite file that anyone holding the phone can read
with one command. For most of this platform's users — a field team in a country
where devices get seized at checkpoints — that is the likelier attack by a wide
margin.

This applies in **every** security mode, `standard` included. Local encryption
is not part of a project's mode and is not configurable per project: a device
either encrypts its database or it does not, and it does.

### 14.2 Cipher

SQLCipher 4 defaults, unchanged:

| Property | Value |
|---|---|
| Page cipher | AES-256-CBC, per-page IV |
| Page authentication | HMAC-SHA512 over ciphertext, page number and IV |
| File salt | 16 random bytes, in the file header |
| Key | **Raw 256-bit**, no password KDF |
| Page size | 4096 |

The key is **raw**, given as `PRAGMA key = "x'<64 hex>'"` or the platform
binding's equivalent. SQLCipher's default of 256,000 PBKDF2-HMAC-SHA512
iterations exists to stretch a human passphrase. Our key is 256 uniformly random
bits out of the platform CSPRNG, so the KDF adds no entropy and costs a second
of startup on the low-end hardware this platform targets. Stretching a key that
is already full-entropy is theatre with a battery cost.

Defaults are otherwise not tuned. `cipher_page_size`, `kdf_iter` and the HMAC
settings stay at SQLCipher's values so that a database written by one build
opens in the next.

### 14.3 The database key

- **32 bytes**, from the platform CSPRNG, generated on **first run**.
- It **never leaves the device**: never synced, never wrapped to a project key,
  never in a backup, never logged, never in a crash report.
- It is **not stored by the application**. It is held by the platform keystore,
  or derived from a key the platform keystore holds. It is never written to
  `SharedPreferences`, to a preferences plist, to a file, to an environment
  variable, or into a build.
- It is unrelated to every key in §4. A content key protects one submission
  from the server; the database key protects the whole local store from whoever
  is holding the phone. Neither can substitute for the other, and **the database
  key must never be used to wrap or unwrap anything in §4**.
- **There is no recovery.** If the keystore entry is lost — app uninstalled,
  device wiped, keystore invalidated by a lock-screen change — the local
  database is unreadable and unsynced operations in it are gone. An escrow copy
  would be a second copy of the key somewhere less protected, which is precisely
  the artifact this design refuses to create. Operations that have been pushed
  survive on the server; that is the recovery path, and it is why sync latency
  is a data-durability concern and not only a convenience one.

### 14.4 Where the key lives, per platform

| Platform | Store | Binding |
|---|---|---|
| Android | Android Keystore (TEE or StrongBox where the device has one) | Non-exportable `HmacSHA256` key, alias `dcp_local_db_key_v1`. The database key is **derived**, not stored — see below |
| iOS | Keychain, `kSecClassGenericPassword` | 32 random bytes, `kSecAttrAccessibleWhenUnlockedThisDeviceOnly` |
| Desktop | The OS credential store: macOS Keychain, Windows Credential Manager (DPAPI), Linux Secret Service (`libsecret`) | 32 random bytes |

**Android is derived rather than stored, and this is deliberate.** The Android
Keystore will not return the raw bytes of a key it holds, so the conventional
pattern is to generate a random database key, seal it with a keystore key, and
write the sealed blob to `SharedPreferences` or a file. This specification
forbids that. The sealed blob is one offline-attackable artifact more than the
design needs, it survives in cloud backups and `adb backup` unless separately
excluded, and it makes "the key is in no file the app owns" unverifiable —
there is now a key-shaped object in a file, and the guarantee rests on an
argument about it rather than on its absence.

Instead:

```
db_key = HMAC-SHA256(K_keystore, "dcp/v1/local-db-key")
```

where `K_keystore` is a 256-bit HMAC key generated inside the Android Keystore
and marked non-exportable. Nothing is persisted outside the keystore, the
derivation is deterministic so the same database opens on every run, and an
attacker with the filesystem but not the TEE has nothing to attack. The `info`
string is domain-separated so the same keystore key can safely derive a
different subkey later.

iOS and desktop store the bytes directly because their keystores, unlike
Android's, will give them back. `ThisDeviceOnly` on iOS keeps the key out of
iCloud Keychain and out of encrypted iTunes/Finder backups — a key that
synchronises to a second device is a key that can be seized on the second
device.

### 14.5 Fail closed

Two failure modes here are silent, produce a working application, and leave the
data in the clear. Both MUST be checked at runtime.

1. **A build linked against plain SQLite ignores `PRAGMA key`.** Plain SQLite
   treats an unknown pragma as a no-op and returns no error, so the application
   runs, the tests pass and the database is written in cleartext. After opening,
   an implementation MUST read the first 16 bytes of the database file and
   refuse to continue if they are the ASCII string `SQLite format 3\0` — the
   header a cleartext SQLite file always begins with, and which an encrypted
   file never does because the salt occupies those bytes.

2. **A missing or broken keystore MUST NOT fall back to an unencrypted
   database.** No fallback, no "encryption unavailable, continuing" path, no
   development-only escape hatch that can be shipped. Failing to start is the
   correct behaviour: an enumerator who cannot open the app files a support
   ticket, and an enumerator whose app quietly stopped encrypting files nothing.

An implementation MUST NOT log the key or its hex form, and MUST NOT put the key
into SQL text where the binding offers an alternative — a bound parameter, or a
native keying call such as `sqlite3_key`.

This is not a style rule. **SQLite's error log prints the text of a statement
that fails**, so `ATTACH DATABASE '<path>' AS encrypted KEY 'x''<hex>'''` writes
the key to the device log the first time the attach goes wrong. It did, on an
emulator, during the first run of the Android migration in §14.6; the fix was to
bind both values.

Where a platform binding can key *only* through `PRAGMA key` — SQLiter on iOS,
the JDBC driver on desktop, neither of which exposes `sqlite3_key`, and pragma
arguments cannot be bound — the key is unavoidably in statement text, and a
SQLite error on that statement would log it. That residual exposure is stated
here rather than claimed away. The Android path avoids it: Zetetic's binding
keys through `sqlite3_key`.

### 14.6 Migrating an existing cleartext database

A device upgrading from a build that predates this section has a cleartext
`dcp.db` holding real, possibly unsynced work. It is migrated, never recreated,
for the reason in §4.5: the device's logical counter lives in that file, and a
device that reset its counter and later encrypted would reuse an operation
nonce.

```sql
-- against the cleartext database
ATTACH DATABASE 'dcp.db.migrating' AS encrypted KEY "x'<64 hex>'";
SELECT sqlcipher_export('encrypted');
PRAGMA encrypted.user_version = <the cleartext user_version>;
DETACH DATABASE encrypted;
```

then replace the original by rename. `user_version` must be carried across by
hand: `sqlcipher_export` copies schema and rows and not that pragma, and
SQLDelight reads it to decide which `.sqm` migrations to run. Losing it makes
the next launch replay every migration against a schema that already has them.

The cleartext file MUST be deleted after a successful swap. Deleting a file does
not erase its blocks, so this narrows the window rather than closing it — the
honest statement is that a device that ever ran a cleartext build may leave
recoverable plaintext in unallocated space until the flash is reused. Only a
factory reset closes that.

### 14.7 App lock (optional)

Optional per deployment. When enabled, the keystore entry is bound to user
authentication:

| Platform | Binding |
|---|---|
| Android | `setUserAuthenticationRequired(true)` on the keystore key, with a validity window, satisfied by device credential or a strong biometric |
| iOS | `kSecAccessControl` with `.userPresence` on the Keychain item |
| Desktop | The OS credential store's own unlock (login keychain, Windows sign-in, keyring prompt) |

The lock gates **the key**, not a screen. A lock that only hides the UI protects
nothing: the database file is still readable by anyone who can copy it. If the
platform will not release the key, the application has no database, which is the
whole point.

Enabling the lock on Android invalidates the existing keystore key if the user
later removes their lock screen, and the database becomes unreadable. That is
the platform's behaviour, it is correct, and the product must say so before the
setting is turned on rather than after.

### 14.8 What this does not protect

- A device compromised **while running and unlocked**. The key is in memory and
  the answers are in the page cache. This is already out of scope in §11 and
  stays there.
- Exported files, screenshots, the OS keyboard's learned-word cache.

Media files on disk **were** in this list and are no longer — see §6.1.
- The plaintext of an answer while it is on screen or in a `ViewModel`.
- Data on the server. `standard` mode still means the operator reads everything;
  §14 changes nothing about that.

### 14.9 Conformance

Local database encryption produces no cross-engine vectors — there is no second
implementation to agree with, and the ciphertext is a SQLCipher file rather than
an envelope this specification defines. It is instead defended by tests that
assert the properties directly, which every client implementation MUST carry:

1. The database file on disk contains none of the plaintext answers written
   through it.
2. A database created under one key cannot be opened with another, and cannot
   be opened with no key.
3. The key appears in no file the application owns — `SharedPreferences`
   included — and in no key-value store the platform offers.
4. A cleartext database is migrated to an encrypted one with its rows, its
   schema version and its device counter intact.
5. Opening against a plain-SQLite binding fails rather than writing cleartext
   (§14.5).
