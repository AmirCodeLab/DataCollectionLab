# Data Collection Platform (DCP)

Offline-first field data collection and operations platform.

**assignment → collection → validation → supervision → review → approval → analytics**

## Status

**Phase 0 — architecture proof.** The form engine and sync protocol are being
proven before any production UI is built.

## Layout

| Path | Contents |
|---|---|
| `backend/` | Python + FastAPI. Includes the **reference** form engine |
| `shared/form-engine/` | Form IR engine — pure Kotlin library, no UI |
| `shared/core/` | Sync, storage, networking, security |
| `clients/composeApp/` | Shared Compose Multiplatform UI |
| `clients/androidApp/`, `desktopApp/`, `iosApp/` | Platform launchers |
| `web/` | React + TypeScript console |
| `web-forms/` | Respondent-facing browser runtime |
| `conformance/` | Language-neutral vectors every engine must pass |
| `specs/` | Form IR, sync protocol, ERD, OpenAPI |
| `deploy/` | Docker Compose and deployment tooling |

## Quick start

```bash
cp .env.example .env
docker compose up -d postgres redis minio

cd backend
pip install -e ".[dev]"
pytest tests/ -v          # conformance suite
uvicorn app.main:app --reload
```

Kotlin side (single Gradle build at the repo root):

```bash
./gradlew :shared:form-engine:jvmTest
./gradlew :clients:androidApp:assembleDebug
```

API docs at http://localhost:8000/docs

## The one thing to understand first

The **Form IR** (`specs/form-ir-v0.1.md`) is the contract. Forms compile into it;
every runtime evaluates it. Two implementations exist — Python (reference) and
Kotlin (clients) — and they must agree on every conformance vector. That agreement
is what makes a form behave identically on an Android phone, an iPhone, a laptop,
a browser and the server.

Read `docs/project-conventions.md` for working conventions and settled decisions.
