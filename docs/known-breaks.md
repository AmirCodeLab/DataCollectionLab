# Known breaks

Every guarantee in this project is defended by a test. A test is only a defence
if it has been watched to fail. This file is the register of the breaks we have
deliberately introduced to watch them fail, and — just as importantly — the ones
we have not.

The distinction is the whole point. "There is a test for that" and "we have seen
that test catch it" are different claims, and only the second one is worth
anything. Until this file existed the difference lived in chat history, which is
to say nowhere: a break run in a session six weeks ago left no trace in the
repository, so the next person had no way to tell a proven guarantee from a
hoped-for one.

## How to use it

To re-verify a row: apply the change in **Break**, run the command in **Caught
by**, confirm it fails, revert, confirm it passes again. Then update **Verified**
with the date.

Two rules carry over from `docs/project-conventions.md` and matter here:

- **Never leave a break in.** Revert it in the same sitting. A break committed by
  accident is a silent hole in exactly the property this file says is defended.
- **Never fix a failing vector by editing the expectation** (rule 3). If a break
  makes a vector fail, that is the vector working. Reverting the break is the
  fix.

A row marked **unverified** is a guarantee we have only claimed. It is not a bug,
but it is not evidence either, and it should not be cited as though it were.

## The register

| # | Break | Caught by | Guarantee it protects | Verified |
|---|---|---|---|---|
| 1 | **Null coerced to `false` at the relevance boundary.** In `backend/app/modules/form_engine/expression.py`, make `coerce_boolean(..., null_is=True)` return `False` for null — and the same in `Evaluator.coerceBoolean` in `shared/form-engine/src/commonMain/kotlin/com/dcp/form/Expression.kt`. | `conformance/vectors/relevance-001.json` and `relevance-002.json` must fail — on **both** engines: `cd backend && pytest tests/test_conformance.py -k test_vector` and `./gradlew :shared:form-engine:jvmTest` | Spec 4.4: a field whose relevance expression is unknown stays **visible**. Coercing to false silently hides questions the moment a referenced answer is blank, so an enumerator never sees them and the data is missing with no trace of why. | Yes — date not recorded (predates this file) |
| 2 | **`path` removed from the op AAD.** In `backend/app/modules/crypto/envelope.py`, drop `path` from the AAD tuple; same in the Kotlin `EncryptionEnvelope`. | `conformance/crypto/op-value-001.json` must fail, including its `tamper` cases: `pytest tests/test_crypto_conformance.py` and `./gradlew :shared:core:jvmTest` | Envelope §5: a value is bound to its exact location. Without `path`, a server operator can move an encrypted answer from `income` to `age`, or into another form version where the path means something else, and decryption succeeds without complaint. | Yes — date not recorded (predates this file) |
| 3 | **Op nonce made constant.** In `envelope.py`, return a fixed 12 bytes from the op nonce derivation instead of deriving it from `(deviceId, counter)`. | `backend/tests/test_envelope.py::test_op_nonce_is_deterministic_and_correct_length`, `::test_op_nonce_differs_across_devices_and_counters`, `::test_op_nonce_never_repeats_over_a_long_counter_run`, and `conformance/crypto/op-nonce-001.json` | Envelope §4.5. Reusing an AES-GCM nonce under one key is catastrophic, not degraded: two ciphertexts under the same (key, nonce) leak the XOR of their plaintexts and forfeit authentication. The server's `(content_key_id, nonce)` uniqueness constraint is the last line of defence, not the first. | Yes — date not recorded (predates this file) |
| 4 | **Ordering by `wall_clock` instead of `(counter, device_id)`.** In `backend/app/modules/sync/service.py`, change the fold's `ORDER BY`. | `backend/tests/test_sync.py::test_two_devices_converge_regardless_of_arrival_order` must fail (it is built so the two orderings disagree) | Sync §6: last-writer-wins by logical counter, with `deviceId` as the tiebreak. Device clocks in the field are wrong — flat batteries, no NTP, manual changes — so a wall-clock fold makes the answer depend on whose phone was more confused, and two servers replaying the same log can disagree. | Yes — date not recorded (predates this file) |
| 5 | **`sensitive` flag ignored in `field_level` mode.** In `shared/core/.../SyncCrypto.kt`, treat every field as non-sensitive so nothing is encrypted. | `EncryptedSyncTest`: `field_level encrypts only the sensitive fields`, `a repeat path resolves to its field, so members income is still encrypted`, and `field_level encrypts everything when the form version is unknown` — `./gradlew :shared:core:jvmTest` | Envelope §3.1 with sensitivity propagation. `field_level` is a promise that the fields marked sensitive never reach the server readable. Ignoring the flag sends them in the clear while every screen still shows the project as encrypted — the failure is invisible from the console. | Yes — date not recorded (predates this file) |
| 6 | **Private key persisted to storage (console).** In `web/src/pages/SubmissionPage.tsx`, in `loadKeyFile`, after `parsePrivateKeyFile` write the scalar to `localStorage`. | `web/src/pages/SubmissionPage.test.tsx` → `never reaches localStorage, sessionStorage, IndexedDB or a request` — `cd web && npm test` | Envelope §7. The page states in bold that the key is "never uploaded, never stored and never logged". A key in `localStorage` outlives the tab, survives a reload, and is readable by anything that can run script on the origin — so the console becomes a place where a project's private key can be found, which is the one thing it must never be. | **Yes — 2026-08-30** |
| 7 | **The local database driver stops passing the key.** In `shared/core/.../DatabaseDriverFactory.jvm.kt`, make `keyProperties` return an empty `Properties()` — what a build that lost its cipher looks like. | Ten of the twenty tests in `LocalDatabaseEncryptionTest` must fail, including `the database file on disk contains none of the plaintext answers` and `a database created under one key cannot be opened with another` — `./gradlew :shared:core:jvmTest` | Envelope §14.1: a seized or stolen phone. Every answer the device has collected sits in the local op log, and unencrypted that file gives all of them up to anyone holding the handset — for many of this platform's users the likelier attack by a wide margin, and the one thing the §1–§10 envelope does nothing about. | **Yes — 2026-08-30** |
| 8 | **The cleartext guard always answers "encrypted".** In `shared/core/.../LocalDatabaseGuard.kt`, make `isCleartext` return `false` unconditionally. | `LocalDatabaseEncryptionTest`: `a cleartext database is refused rather than used`, `the driver refuses to hand back a driver whose file turned out to be cleartext`, `an existing cleartext database is migrated…`, `a cleartext database with no key is a normal upgrade…` — `./gradlew :shared:core:jvmTest` | Envelope §14.5. SQLite treats an unrecognised pragma as a no-op and returns no error, so a build linked against plain SQLite instead of SQLCipher runs perfectly, passes every functional test, and writes the whole op log to disk in the clear. The header check is the only thing that can see that from inside the app — and it is also what tells the migration a database still needs converting. | **Yes — 2026-08-30** |
| 9 | **The lost-key guard removed.** In `shared/core/.../CoreFactory.kt`, drop the `databaseState() == ENCRYPTED && !keyStore.exists()` check in `createSubmissionStore`. | `LocalDatabaseEncryptionTest`: `an encrypted database with no key in the keystore is refused, not replaced` — `./gradlew :shared:core:jvmTest` | Envelope §14.3: there is no recovery for the local database key, so an encrypted database plus an empty keystore means the key is **lost**, not that this is a first run. Minting a replacement opens a new empty database beside the real one and every unsynced answer on the device becomes unreachable forever — while the app reports itself perfectly healthy and the enumerator sees an empty list. The keystore cannot make this call itself: macOS reports a keychain it cannot open with the same `errSecItemNotFound` it uses for a key that is genuinely absent. | **Yes — 2026-08-30** |
| 10 | **An enum member added to the wire type without regenerating the contract.** Add `"archived"` to `type SubmissionStatus` in `backend/app/modules/submissions/schemas.py` and commit nothing else. | `python scripts/generate_api_contract.py --check` exits 1 naming both files, and `backend/tests/test_openapi_contract.py::test_committed_contract_matches_the_app` and `::test_committed_console_types_match_the_contract` fail — as does `test_wire_enum_mirrors.py::test_submission_status_mirrors_the_check_constraint`, because the database constraint has no `archived` either | The committed contract is what the console, the Kotlin clients and anyone integrating read. A snapshot that has fallen behind the server is worse than no snapshot: it is wrong and it looks authoritative. The byte comparison is what makes "the app is the source of truth" enforceable rather than a convention. | **Yes — 2026-08-30** |
| 11 | **A route written without a `response_model`.** In `backend/app/api/v1/forms.py`, drop `response_model=EvaluateResponse` from `/evaluate` and return `dict[str, object]` — then regenerate the contract, so the byte comparison is satisfied and only the shape rule is left. | `backend/tests/test_openapi_contract.py::test_every_success_response_names_a_schema`, which names the route: `POST /api/v1/forms/evaluate → 200 returns an inline schema` | FastAPI infers an undeclared body from the return annotation, and `dict[str, Any]` infers to an object with **no fields**. That generates as `Record<string, unknown>`: it type-checks in the console, it runs, and it has quietly stopped describing the API. The route looks documented and is not — which is the failure mode a generated contract is otherwise blind to, because regenerating makes the diff go away. | **Yes — 2026-08-30** |
| 12 | **A closed value set declared as a plain assignment.** Change `type SubmissionStatus = Literal[...]` back to `SubmissionStatus = Literal[...]`. | `backend/tests/test_openapi_contract.py::test_every_closed_value_set_is_a_named_schema`, naming the property: `components.schemas.SubmissionDetail.properties.status has an inline enum` | Pydantic inlines an unnamed alias at every use site, so one closed set becomes six anonymous unions the generated client cannot name — and cannot produce a runtime array from. The console renders its status filter and key-role dropdown from those arrays; without them they go back to being hand-written, which is the drift this whole chain removed. | **Yes — 2026-08-30** |
| 13 | **An error model declared as the payload instead of the envelope.** In `backend/app/api/v1/devices.py`, declare `403: {"model": DeviceRegisterError}` in place of `DeviceRegisterErrorResponse`. | `backend/tests/test_openapi_contract.py::test_every_declared_error_body_names_a_schema`, naming the route and the fields it found | This was a real defect in the API before the contract was committed: FastAPI wraps an `HTTPException`'s `detail` in `{"detail": ...}`, so declaring the payload published a body the server has never once returned. A generated client written against it fails on the first refusal it meets — and a refusal is exactly when a client can least afford to be surprised. | **Yes — 2026-08-30** |

## What is not on this list

Guarantees with no break recorded against them. These are the honest gaps —
tests exist for all of them, but none has been watched to fail:

| Guarantee | Test that should catch it | Status |
|---|---|---|
| Recalculation is topologically ordered, ties broken by document order | `conformance/vectors/calculate-*.json` | **Unverified** |
| A wrap addressed to another recipient fails to authenticate rather than silently producing garbage | `conformance/crypto/wrap-multi-001.json` tamper cases | **Unverified** |
| A small-order public key is refused as a recipient | `backend/tests/test_project_keys.py::test_small_order_points_are_not_usable_recipients` | **Unverified** |
| A published test keypair is refused outside development | `backend/tests/test_published_test_keys.py` | **Unverified** |
| Migration 0001 round-trips: `downgrade` then `upgrade` yields the identical schema | `backend/tests/test_migrations.py` (`db`-marked) | **Unverified** |
| A revoked key stops receiving wraps but still opens what it already opened | `backend/tests/test_project_keys.py::test_a_revoked_key_stops_receiving_wraps_but_keeps_opening_what_it_has` | **Unverified** |
| The key upload payload carries only `publicKey`, `role` and `label` | `web/src/pages/ProjectKeysPage.test.tsx` | **Unverified** |
| The Android database key is derived inside the Keystore and never lands in a file | `scripts/prove_local_encryption.sh` step 6 — and it is a *structural* check (no `shared_prefs` exists at all), because there is no key material outside the process to search for | **Unverified** — the break would be rewriting `DatabaseKeyStore.android.kt` to seal a random key and store the blob, which is a redesign rather than a one-line break |
| The iOS Keychain item is `WhenUnlockedThisDeviceOnly`, so the key is in no backup and on no second device | nothing — the attribute is set in `DatabaseKeyStore.ios.kt` and never read back | **Unverified**, and there is no test at all. The simulator does not model backup or iCloud Keychain, so this needs a device and a restore to check |
| The app lock actually gates the key on Android and iOS | nothing | **Unverified**, and untestable as written: the keystore key's auth binding is fixed at generation, and no automated environment here has a lock screen to satisfy. `AppLock.ENABLED` is off |
| The desktop Linux (`secret-tool`) and Windows (Credential Manager) stores work | nothing — `MacKeychainCredentialStoreTest` covers macOS against a scratch keychain; CI is a headless Linux runner with no Secret Service daemon | **Unverified**. The Windows implementation has never run on Windows |
| A locked macOS keychain is told apart from an absent key | nothing, and it cannot be from `security(1)`: everything that is not a hit is `errSecItemNotFound`, and a locked keychain answers with an interactive prompt rather than an exit code | **Unverified by design.** Break 9 is what stands in for it — the guard moved up to `createSubmissionStore`, where the *database file* settles the question instead of the keystore |

## A note on the instruments

Break 6 is a negative guarantee — "the key is in no storage and no request" —
and a negative passes just as cheerfully when the instrument is broken. It very
nearly did: under this jsdom, `window.localStorage` reads back `undefined`, so
the break would have **thrown** rather than leaked and the test would have
reported "nothing leaked" about a channel it could not observe.

`web/src/test/harness.test.ts` exists for that reason. It writes to every sink
`watchForEscapes` claims to watch and asserts each one is recorded. When a row
in this register is a negative, check the instrument before trusting the green.
