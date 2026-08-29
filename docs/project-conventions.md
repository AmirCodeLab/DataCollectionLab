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
   `backend/app/modules/crypto/` needs a test proving the property it protects.

6. **Offline-first is a constraint, not a feature.** For any client change, ask:
   what happens with no network for 14 days?

7. **No production form-builder UI until the IR and sync protocol are stable.**
   The builder is the most satisfying thing to build and the most expensive to
   rebuild.

8. **RTL/Arabic from the start.** Not retrofitted.

9. **The console uses the public API.** No private endpoints.

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

# Conformance
python conformance/generate_vectors.py     # regenerate vectors
cd backend && pytest tests/test_conformance.py -v

# Kotlin engine (from the repo root — one build)
./gradlew :shared:form-engine:jvmTest
./gradlew :clients:androidApp:assembleDebug
./gradlew :clients:desktopApp:run

# Web
cd web && npm install && npm run dev
npm run typecheck && npm run lint && npm test && npm run build

# Full stack
docker compose up
```

## CI

`.github/workflows/ci.yml` — four jobs, all of them blocking: **backend**
(ruff, mypy, pytest without `db`), **db** (pytest `-m db` against a PostGIS
service), **kotlin** (`:shared:form-engine:jvmTest`, `:shared:core:jvmTest`),
**web** (typecheck, lint, test, build).

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

**Phase 0 — architecture proof: complete except the OpenAPI contract.**
**Phase 1 — clients: in progress (Android collection app).**

Phase 0 deliverables, with evidence (`./scripts/status.sh` recomputes this):

1. Form IR specification — done incl. screen flow (§11); 29 conformance
   vectors pass identically on the Python and Kotlin engines
2. Sync protocol specification — done; server push/pull implemented
   (`backend/app/modules/sync/`, commit e9f30d7) and the client op log +
   outbox live in `shared/core` (`SubmissionStore`, 5 JVM tests)
3. ERD / database schema — done; Alembic migration 0001 in
   `backend/migrations/versions/`, migration tests green against Postgres
4. OpenAPI contract — **still skeleton**: 4 routes exist, no contract file
   in `specs/`
5. Encryption envelope — done; 8 crypto vectors byte-identical on both engines
6. iOS Compose spike — done: builds and runs on the iPhone 17 Pro simulator;
   the submission list renders with the SQLDelight native driver and the
   bundled form compiling on-device (app link needs `-lsqlite3`, set in
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

Plainly NOT done yet:

- **Local storage is still cleartext** — encryption covers what leaves the
  device. The op log on disk holds plaintext values (plus the cached
  ciphertext); at-rest encryption of the local database is separate work
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
- **OpenAPI contract** — still skeleton (see item 4)
