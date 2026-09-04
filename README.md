# Data Collection Platform (DCP)

Offline-first field data collection and operations platform.

**assignment → collection → validation → supervision → review → approval → analytics**

Not a survey app. The survey is one step; the value is in what surrounds it —
assigning work, catching bad data at the point of collection, supervising
enumerators, reviewing and approving, and getting the data out in a form an
analyst can use. Comparable to SurveyCTO, KoboToolbox and ODK.

Licensed **AGPL-3.0** — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

## Status: pre-release. Do not collect real data with it yet.

Phase 0 (architecture proof) and Phase 1 (Android collection client) are done.
**Phase 2 part 1 — usable by one real customer — is in progress**, currently on
export. The end-to-end chain works on real hardware: a form authored elsewhere
imports, publishes, deploys, reaches a phone that has never held it, is
collected offline, and syncs back encrypted.

What is deliberately not built yet is listed in
[`docs/project-conventions.md`](docs/project-conventions.md) under "Plainly NOT
done yet", and open defects are in
[`docs/known-defects.md`](docs/known-defects.md). Read both before deploying
this anywhere that matters. In particular: the app lock is off and cannot be
toggled, desktop renders collection widgets that do nothing, and key custody is
half built.

## The one thing to understand first

The **Form IR** (`specs/form-ir-v0.1.md`) is the contract. Forms compile into
it; every runtime evaluates it. Two implementations exist — Python (the
reference) and Kotlin (the clients) — and they must agree on every conformance
vector. That agreement is what makes a form behave identically on an Android
phone, an iPhone, a laptop, a browser and the server.

There are **170 vectors in five sets**, because one format cannot express all
five questions:

| Set | Count | Asks |
|---|---|---|
| `conformance/vectors` | 81 | what an expression evaluates to |
| `conformance/functions` | 54 | every spec function against every value shape |
| `conformance/malformed` | 22 | which documents are refused before compilation |
| `conformance/crypto` | 8 | the encryption envelope, byte for byte |
| `conformance/sensitivity` | 5 | which forms publish refuses |

A vector that passes on one engine and fails on the other is a release blocker,
never a platform difference.

**Where that stops protecting you** is documented at length in
`docs/project-conventions.md`, and it is the most useful thing in this
repository: a vector fixes the inputs and compares the outputs, so anything
deciding *which* compiled artifact is used is structurally invisible to it. The
failures that reached real hardware all lived there.

## Layout

One Gradle build, rooted at the repository root.

| Path | Contents |
|---|---|
| `backend/` | Python + FastAPI. Includes the **reference** form engine |
| `shared/form-engine/` | Form IR engine — pure Kotlin library, no UI, no Android framework |
| `shared/core/` | Sync, storage, networking, security |
| `clients/composeApp/` | Shared Compose Multiplatform UI |
| `clients/androidApp/`, `desktopApp/`, `iosApp/` | Platform launchers |
| `web/` | React + TypeScript + Vite console |
| `web-forms/` | Respondent-facing browser runtime |
| `conformance/` | Language-neutral vectors every engine must pass |
| `specs/` | Form IR, sync protocol, ERD, OpenAPI |
| `deploy/` | Docker Compose and deployment tooling |

## Stack

Python 3.12 + FastAPI (modular monolith) · PostgreSQL 16 + PostGIS + JSONB ·
Redis + Celery · S3-compatible storage (MinIO locally) · Kotlin Multiplatform
with SQLDelight, Ktor and Koin · React 19 + TypeScript + Vite · Docker.

No Kafka (transactional outbox instead), no Kubernetes until there is a
measured need, and the console is a Vite SPA specifically so a self-hosted
install does not need a Node runtime beside Python.

## Quick start

Configuration is read from the environment with working defaults that match
`docker-compose.yml`, so a local run needs no `.env` file. Override anything in
`backend/app/core/config.py` by exporting it, or by creating a `.env` beside the
backend.

```bash
docker compose up -d postgres redis minio

cd backend
pip install -e ".[dev]"
alembic upgrade head              # create the schema
python ../scripts/seed_dev.py     # minimum data to be usable — see below
pytest tests/ -v
uvicorn app.main:app --reload
```

API docs at http://localhost:8000/docs — 29 operations, every one generated
from the app.

Kotlin side, from the repository root:

```bash
./gradlew :shared:form-engine:jvmTest    # the engine, and its half of the vectors
./gradlew :shared:core:jvmTest           # sync, storage, local encryption
./gradlew :clients:composeApp:jvmTest    # the shared UI, headless
./gradlew :clients:androidApp:assembleDebug
```

Web console:

```bash
cd web && npm install && npm run dev
npm run typecheck && npm run lint && npm test && npm run build
```

### Seeding

```bash
python scripts/seed_dev.py
```

Creates the minimum a fresh database needs: one organisation, one project with
development, staging and production environments, and the `household_survey`
form at version 1, deployed to all three. Nothing else — devices are not
seeded, because a client registers itself on first sync.

The deployment is the part that makes a device see anything. **Publishing is not
deploying**: a published version nothing has deployed appears in no device's
form manifest, so it never reaches a phone.

It is idempotent — rows are matched by natural key. A published form version is
immutable, so if the example JSON drifts from the stored version the script
warns rather than overwriting it.

Without this step the server has no project to attach devices to, so device
registration fails and every pushed op is rejected. The failure says so, with a
machine-readable `reason` (`project_not_found`, `project_ambiguous`,
`project_mismatch` or `device_revoked`) that the clients surface rather than a
bare status code.

### There is no form in the app

A device that has not synced has no forms and says so. Forms arrive over sync;
`specs/examples/household_survey.json` is the seed's input, not the app's. This
is enforced at build time — `assembleDebug` fails if any APK entry carries a
Form IR document.

### Request logging

In development the server logs every endpoint hit: method, URL, headers, bodies,
status and duration; failures at WARNING.

`Authorization`, `Cookie` and similar headers are **always** redacted, and
bodies are truncated at 4 KB. Because submissions carry respondent data, logging
defaults to on only when `ENVIRONMENT=development`. Set `HTTP_LOG=true` to force
it on, `HTTP_LOG=false` off, or `HTTP_LOG_BODIES=false` to keep the request
lines without payloads.

## Two rules worth knowing before you send a patch

1. **The Form IR spec is normative.** If code and spec disagree, the spec wins —
   or the spec changes deliberately, in its own commit.
2. **Never "fix" a failing vector by editing the expectation.** Change an
   expectation only alongside a spec change explaining why.

The rest — locked decisions, the conformance boundary, conventions, current
phase — is in [`docs/project-conventions.md`](docs/project-conventions.md).
Security policy and how to report a vulnerability: [SECURITY.md](SECURITY.md).
