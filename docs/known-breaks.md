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

## A note on the instruments

Break 6 is a negative guarantee — "the key is in no storage and no request" —
and a negative passes just as cheerfully when the instrument is broken. It very
nearly did: under this jsdom, `window.localStorage` reads back `undefined`, so
the break would have **thrown** rather than leaked and the test would have
reported "nothing leaked" about a channel it could not observe.

`web/src/test/harness.test.ts` exists for that reason. It writes to every sink
`watchForEscapes` claims to watch and asserts each one is recorded. When a row
in this register is a negative, check the instrument before trusting the green.
