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

5. **Offline-first is a constraint, not a feature.** For any client change, ask:
   what happens with no network for 14 days?

6. **No production form-builder UI until the IR and sync protocol are stable.**
   The builder is the most satisfying thing to build and the most expensive to
   rebuild.

7. **RTL/Arabic from the start.** Not retrofitted.

8. **The console uses the public API.** No private endpoints.

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

# Full stack
docker compose up
```

## Conventions

- Python: ruff, line length 100, type hints everywhere, mypy strict on `app/`
- Kotlin: official style, explicit visibility on public API
- Commits: imperative mood, scope prefix — `engine: add null coercion at boundary`
- Every behavioural change to the engine ships with a conformance vector
- Migrations must be reversible; self-hosted users run old versions

## Current phase

**Phase 0 — architecture proof.** Run `./scripts/status.sh` for the live,
evidence-based report; the list below mirrors its output and goes stale the
moment code changes.

1. Form IR specification — **DONE** for v0.1, repeat scope included, nested
   repeats deferred to v0.2. Evidence: `specs/form-ir-v0.1.md`; both engines
   pass 24/24 vectors in `conformance/vectors/`.
2. Sync protocol specification — **PARTIAL**: drafted, conflict-resolution
   detail missing. Evidence: `specs/sync-protocol-v0.1.md` exists,
   `backend/app/modules/sync/` is empty.
3. ERD / database schema — **NOT STARTED**. Evidence: no migrations in
   `backend/migrations/versions/`, no ERD spec in `specs/`.
4. OpenAPI contract — **PARTIAL**: 2 routes in `backend/app/api/`, no contract
   file in `specs/`. Evidence: `backend/app/api/v1/forms.py`.
5. Encryption envelope design — **NOT STARTED**. Evidence: no spec in
   `specs/`, no crypto code in `shared/` or `backend/app/`.
6. iOS Compose spike — **NOT STARTED** (MANUAL check — the script cannot
   verify this). Evidence: `clients/iosApp` is still the unmodified KMP
   template.

Engine status: the Python reference and the Kotlin port agree on all 24
conformance vectors, repeats included — verify with
`cd backend && pytest tests/test_conformance.py -v` and
`./gradlew :shared:form-engine:jvmTest`.

Do not start Phase 1 (builder UI, Android app) until 1 and 2 are stable.
