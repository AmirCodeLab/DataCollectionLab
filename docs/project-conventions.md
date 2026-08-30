# DCP — Project Context

Read this before making changes. It encodes decisions that are already settled;
re-litigating them wastes time.

## What this is

An offline-first field data collection and operations platform. Not a survey app.
Full cycle: assignment → collection → validation → supervision → review → approval → analytics.

Competitors: SurveyCTO (primary), KoboToolbox and ODK (secondary).

Full plan: `docs/DCP-Product-and-System-Architecture-v1.0.md`.

## Repository layout

```
settings.gradle.kts     ONE Gradle build for the whole repo
gradle/                 wrapper + libs.versions.toml (single version catalog)
backend/                Python + FastAPI, modular monolith
shared/form-engine/     Form IR engine — pure library, NO UI, NO Android framework
shared/core/            Sync, storage, networking, security — no UI
clients/composeApp/     Shared Compose UI (iOS framework baseName "Shared")
clients/androidApp/     Android launcher
clients/desktopApp/     Desktop launcher
clients/iosApp/         Xcode project, consumes the composeApp framework
web/                    React + TypeScript + Vite console
web-forms/              Respondent-facing runtime
conformance/            Language-neutral vectors — the contract between engines
specs/                  Form IR, sync protocol, ERD, OpenAPI
deploy/                 Docker Compose and deployment tooling
```

**One Gradle build, rooted at the repo root.** Do not add a `settings.gradle.kts`
inside `clients/` or `shared/` — that was the original mistake and it stops the
apps depending on `:shared:form-engine` directly.

**`shared/form-engine` must stay dependency-free of UI and Android framework
code.** It has to run on the server and in a browser via Wasm. If something needs
Compose, it belongs in `clients/composeApp`.

## Locked decisions — do not change without an explicit discussion

| Area | Decision |
|---|---|
| Backend | Python 3.12 + FastAPI, modular monolith |
| Database | PostgreSQL 16 + PostGIS + JSONB |
| Cache / jobs | Redis + Celery workers |
| Storage | S3-compatible (MinIO locally) |
| Analytics | Postgres now, Parquet + DuckDB later. No warehouse |
| Web console | React 19 + TypeScript + **Vite SPA** |
| Shared client code | Kotlin Multiplatform |
| Local DB | SQLDelight |
| Networking | Ktor |
| DI | Koin |
| Form representation | Own versioned Form IR — **not** XForms/XPath |
| Sync | Operation-based, resumable, idempotent, snapshots + tombstones |
| Events | Transactional outbox. **No Kafka** |
| Deployment | Docker. **No Kubernetes** until measured need |

**Not Next.js.** The console is a Vite SPA specifically so a self-hosted install
does not need a Node runtime beside Python.

## Open decisions — ask before assuming

- **O-1** First target market (survey agencies vs government/health)
- **O-2** Server-side form evaluation: JVM engine sidecar vs Python port
- **O-3** Web forms runtime: Compose Web vs engine-to-Wasm + React
- **O-4** Pricing model (affects whether metering is core)
- **O-5** Open-core: open-source the engine only?
- **O-6** Extensibility: constrained custom widget SDK

## The rules that matter

1. **The Form IR spec is normative.** `specs/form-ir-v0.1.md`. If code and spec
   disagree, the spec wins — or the spec changes deliberately, in its own commit.

2. **Conformance vectors are the contract.** Every engine — Python reference and
   Kotlin — must pass every vector in `conformance/vectors` identically. A vector
   passing on one and failing on the other is a release blocker, never a platform
   difference.

3. **Never "fix" a failing vector by editing the expectation.** Change the
   expectation only alongside a spec change explaining why.

4. **Null semantics are the highest-risk area** (spec 4.4). Every change to
   comparison, arithmetic or boolean coercion needs a new vector.

5. **Crypto rules are not negotiable.** `specs/encryption-envelope-v0.1.md`
   is normative. Never remove a field from an AAD, never make a nonce constant
   or random-without-justification, never hash media plaintext. Every change to
   `backend/app/modules/crypto/` needs a test proving the property it protects,
   and so does every change to `shared/core/src/*/kotlin/com/dcp/core/security/`
   — §14 has no cross-engine vectors to catch a regression, only tests that read
   the bytes on disk.

6. **Offline-first is a constraint, not a feature.** For any client change, ask:
   what happens with no network for 14 days?

7. **No production form-builder UI until the IR and sync protocol are stable.**
   The builder is the most satisfying thing to build and the most expensive to
   rebuild.

8. **RTL/Arabic from the start.** Not retrofitted.

9. **The console uses the public API.** No private endpoints.

10. **The API contract is generated. Never hand-write it, never hand-edit it.**
    `specs/openapi.json` and `web/src/api/types.ts` are both produced by
    `scripts/generate_api_contract.py` from the FastAPI app, and CI fails when
    either is not what the app generates right now. See below.

## The API contract

The app is the source of truth. Everything downstream is generated from it:

```
backend/app/main.py  ──►  specs/openapi.json  ──►  web/src/api/types.ts
     (the truth)          (committed snapshot)      (console wire types)
```

`specs/openapi.json` is committed so an API change shows up as a change to a
reviewable file. `web/src/api/types.ts` is generated so the console's types
cannot drift from it — that file used to hand-mirror `SUBMISSION_STATUSES` from
a database CHECK constraint and needed a test of its own to catch the copy going
stale.

**Never edit either file.** An edit survives until the next run of the generator
and until then it says something untrue about the server. Change the Pydantic
model, then:

```bash
python scripts/generate_api_contract.py          # rewrite both files
python scripts/generate_api_contract.py --check  # what CI runs
```

Commit the regenerated files **in the same commit as the API change**. An API
change without a contract change is a red build, deliberately.

What that requires of a route:

- **Every route has a `response_model`.** Without one FastAPI infers the body
  from the return annotation, and `dict[str, Any]` infers to an object with no
  fields — `Record<string, unknown>` in the console, which type-checks
  everywhere and describes nothing. `test_openapi_contract` fails the build for
  an inline 2xx schema and names the route.
- **Every request body is a Pydantic model.** Same rule, same reason.
- **Every closed value set is a named `type` alias**, not a plain assignment:

  ```python
  type SubmissionStatus = Literal["draft", ...]   # one named schema
  SubmissionStatus = Literal["draft", ...]        # inlined at every use site
  ```

  Pydantic gives the PEP 695 alias its own entry in the document, so the
  console gets `SubmissionStatus` **and** a `SUBMISSION_STATUSES` array to
  render a dropdown from. A plain assignment gets neither.
- **A declared error model is the `{"detail": ...}` envelope**, not the payload
  inside it — that is what FastAPI actually sends.
- **422 belongs to the framework.** It means "the request did not match the
  schema". Three endpoints also return 422 for a domain refusal with a
  different body (`POST /forms/compile`, `POST /forms/versions`,
  `POST /projects/{id}/keys`); only one shape can be declared under one status,
  so those refusals are documented in the route's description and not in its
  schema. Anything new gets its own status code.

The remaining hand-copied link is the one no generator can see: a database
CHECK constraint and the Python `Literal` that mirrors it are written in
different languages by different hands. `backend/tests/test_wire_enum_mirrors.py`
is what holds those together.

## Form engine

Two implementations that must agree:

- `backend/app/modules/form_engine/` — Python **reference implementation**. When
  behaviour is ambiguous, this defines it.
- `shared/form-engine/` — Kotlin, runs on Android, iOS, desktop, Wasm and
  potentially the server.

Key design points:
- Expressions are a **typed AST**, never strings. No XPath at runtime.
- `null` is a first-class value. It propagates through arithmetic and comparison
  and only becomes boolean at the relevance/constraint/required boundary.
- `relevant` and `constraint` coerce null to **true**; `required` and `readOnly`
  coerce to **false**.
- Non-relevant fields **retain** their values but are excluded from export.
- Recalculation runs in topological order; document order breaks ties so the
  result is deterministic.

## Commands

```bash
# Backend
cd backend && pip install -e ".[dev]"
uvicorn app.main:app --reload
pytest tests/ -v
ruff check . && mypy app

# API contract (run from the repo root; never edit the generated files)
python scripts/generate_api_contract.py            # openapi.json + console types
python scripts/generate_api_contract.py --check    # what CI runs

# Conformance
python conformance/generate_vectors.py     # regenerate vectors
cd backend && pytest tests/test_conformance.py -v

# Kotlin engine (from the repo root — one build)
./gradlew :shared:form-engine:jvmTest
./gradlew :clients:androidApp:assembleDebug
./gradlew :clients:desktopApp:run

# Local database encryption (envelope §14)
./gradlew :shared:core:jvmTest --tests "com.dcp.core.security.*"
scripts/prove_local_encryption.sh          # against a connected device
scripts/build_sqlcipher_ios.sh             # once, before the first iOS build

# Web
cd web && npm install && npm run dev
npm run typecheck && npm run lint && npm test && npm run build

# Full stack
docker compose up
```

## CI

`.github/workflows/ci.yml` — four jobs, all of them blocking: **backend**
(ruff, mypy, the API contract check, pytest without `db`), **db** (pytest
`-m db` against a PostGIS service), **kotlin** (`:shared:form-engine:jvmTest`,
`:shared:core:jvmTest`), **web** (typecheck, lint, test, build).

These are the same commands listed above. Run them locally before pushing —
but the point of the workflow is that nobody has to remember to.

## Conventions

- Python: ruff, line length 100, type hints everywhere, mypy strict on `app/`
- Kotlin: official style, explicit visibility on public API
- Commits: imperative mood, scope prefix — `engine: add null coercion at boundary`
- Every behavioural change to the engine ships with a conformance vector
- Migrations must be reversible; self-hosted users run old versions
- A guarantee is not defended until its break has been watched to fail —
  record it in `docs/known-breaks.md`

## Current phase

**Phase 0 — architecture proof: complete.**
**Phase 1 — clients: in progress (Android collection app).**

Phase 0 deliverables, with evidence (`./scripts/status.sh` recomputes this):

1. Form IR specification — done incl. screen flow (§11); 29 conformance
   vectors pass identically on the Python and Kotlin engines
2. Sync protocol specification — done; server push/pull implemented
   (`backend/app/modules/sync/`, commit e9f30d7) and the client op log +
   outbox live in `shared/core` (`SubmissionStore`, 5 JVM tests)
3. ERD / database schema — done; Alembic migration 0001 in
   `backend/migrations/versions/`, migration tests green against Postgres
4. OpenAPI contract — done; `specs/openapi.json`, generated from the app by
   `scripts/generate_api_contract.py` and never hand-written. 16 operations,
   every one with a `response_model` and a typed request body. The console's
   wire types are generated from it too, so the last hand-mirrored copy —
   `SUBMISSION_STATUSES` in `web/src/api/types.ts` — is gone along with the
   test that watched it. CI regenerates both and fails on any difference
5. Encryption envelope — done; 8 crypto vectors byte-identical on both engines
6. iOS Compose spike — done: builds and runs on the iPhone 17 Pro simulator;
   the submission list renders with the SQLDelight native driver and the
   bundled form compiling on-device (the app supplies SQLite at link time —
   now SQLCipher rather than `-lsqlite3`, see §14 below and
   `clients/iosApp/Configuration/Config.xcconfig`)

Phase 1 so far: Android collection screen in `clients/composeApp` — paged
navigation driven by the shared engine's screen plan, live relevance and
constraints, local op log, RTL, tested on a real device with a 52-question form.

Client-side encryption is wired into the sync path: a device fetches its
project's security mode and recipient set from
`GET /api/v1/devices/{id}/crypto`, generates a content key per submission,
wraps it to every active project key, and encrypts op values per the mode —
nothing in `field_level`, sensitive fields only, or everything. The server
stores ciphertext it cannot read and refuses a repeated
`(content_key_id, nonce)` with a stated reason. Sensitivity propagation is
enforced at publish time in both engines against `conformance/sensitivity`.

The data comes back out again (§7): `GET /api/v1/submissions/{id}` relays each
encrypted op's ciphertext, nonce and content key id beside the wrapped keys from
`GET /api/v1/submissions/{id}/keys`, and decryption happens where the private
key is — in the browser (`web/src/lib/decryptSubmission.ts`, shown on the
submission page with the key held in tab memory only) or in a terminal
(`scripts/decrypt_submission.py`, TEST ONLY). Both handle a submission with
content keys from several devices, and both say which content keys a given
private key does not open rather than reporting no answers.

A key whose private half is published — the fixed keypairs in
`scripts/dev_project_key.py` — is refused outside a development environment,
both when registering it as a recipient and when handing the recipient set to a
device (`backend/app/modules/crypto/published_test_keys.py`).

The local database is encrypted at rest (§14, added in this repository —
§1–§10 are about what leaves the device, §14 about what stays on it). SQLCipher
4 with a raw 256-bit key on all three clients: `net.zetetic:sqlcipher-android`,
SQLite3 Multiple Ciphers on the JVM (substituted for `org.xerial:sqlite-jdbc`,
which has no cipher), and a SQLCipher static library on iOS built by
`scripts/build_sqlcipher_ios.sh` and linked from `Config.xcconfig` in place of
`-lsqlite3`.

The key is generated on first run, never leaves the device, and is not stored by
the app: Android **derives** it inside the Keystore
(`HMAC-SHA256(K_keystore, "dcp/v1/local-db-key")`, nothing persisted outside the
TEE — no sealed blob in SharedPreferences), iOS keeps 32 bytes in the Keychain
as `WhenUnlockedThisDeviceOnly`, desktop in the OS credential store. There is no
fallback and no recovery: a build linked against plain SQLite writes cleartext
while looking perfectly healthy, so every driver checks the file header after
opening and refuses to start if it says `SQLite format 3` (§14.5). Existing
cleartext databases are migrated, never recreated — the device's logical counter
lives in that file and operation nonces derive from it (§4.5). Verified on an
emulator and an iOS simulator, both carrying real pre-§14 data:
`scripts/prove_local_encryption.sh`.

Plainly NOT done yet:

- **The app lock is off and cannot be toggled.** `AppLock.ENABLED` is a build
  constant. The keystore side of §14.7 is built — an auth-bound Android
  Keystore key, `kSecAccessControlUserPresence` on the iOS Keychain item — but
  the binding is fixed when the key is generated, so switching it on a device
  that already holds data needs a re-key of the database, and that is not
  written. A settings toggle without it would silently destroy every answer on
  the device
- **Media** (capture, chunked upload) — not started, and it is the remaining
  half of the envelope: §6 media keys and chunk nonces have no callers
- **Key custody is half built** — the console generates a project keypair with
  WebCrypto, downloads the private half and registers only the public one
  (`web/src/pages/ProjectKeysPage.tsx`, `POST /api/v1/projects/{id}/keys`), and
  `scripts/dev_project_key.py` installs a TEST ONLY fixed keypair for local
  work. Decryption with a held private key works (above). Revocation now exists
  (`POST /api/v1/projects/{id}/keys/{keyId}/revoke`, with a Revoke button on the
  keys page): it stops future wrapping, keeps the row so the console can still
  name whose private key opens old submissions, is idempotent, and refuses to
  retire the last active recipient of an encrypting project — which would stop
  collection in the field silently. What is still missing is the rest of the §8
  *flow*: no rotation (register-new-then-revoke-old is manual and unguided), no
  re-registration of a holder, and no import of a keypair generated elsewhere
- **Two gaps the contract work found and did not close.** Both are in
  `/forms`, both need a decision rather than a patch. (a) Three endpoints
  return 422 for a domain refusal, colliding with FastAPI's own
  request-validation 422, so only one of the two bodies can be declared —
  moving the refusals to their own status code would fix it and is an API
  change. (b) `POST /forms/compile` returns **500**, not 422, for a Form IR
  document missing a required top-level key: the engine raises `KeyError`
  where §10 says it should report an error. The contract says 200 or 422, so
  the document is currently wrong about that route in one direction the
  generator cannot see
