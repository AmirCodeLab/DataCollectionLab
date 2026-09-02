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
alembic upgrade head            # create the schema
python ../scripts/seed_dev.py   # seed the minimum data (see below)
pytest tests/ -v                # conformance suite
uvicorn app.main:app --reload
```

### Seeding

Run it from anywhere — the repo root works too, and the script finds the
backend venv itself:

```bash
python scripts/seed_dev.py
```

`scripts/seed_dev.py` creates the minimum a fresh database needs to be usable:
one organisation, one project with its development, staging and production
environments, and the `household_survey` form at version 1, loaded from
`specs/examples/household_survey.json` and deployed to all three environments.
Nothing else — devices are not seeded, because a client registers itself on
first sync (`POST /api/v1/devices`, sync protocol §4).

The deployment is the part that makes a device see anything. A published version
nothing has deployed appears in no device's form manifest (sync §5), so it never
reaches a phone.

It is idempotent: rows are matched by natural key, so running it twice is safe
and changes nothing. A published form version is immutable, so if the example
JSON drifts from the stored version the script warns rather than overwriting
it — publish a new version deliberately instead.

Without this step the server has no project to attach devices to, so device
registration fails and every pushed op is rejected. The failure says so:

```json
{ "detail": { "reason": "project_not_found",
              "message": "The server has no active project ... Run scripts/seed_dev.py ..." } }
```

Registration failures always carry a machine-readable `reason` —
`project_not_found`, `project_ambiguous`, `project_mismatch` or
`device_revoked` — which the clients report in their sync error rather than a
bare status code.

### Request logging

In development the server logs every endpoint hit: method, URL, headers,
request body, response status, response body and duration. Failures are logged
at WARNING so they stand out.

```
WARNING:     POST /api/v1/devices -> 409 (131ms)
  request headers: {"content-type": "application/json", "authorization": "<redacted>"}
  request body:
    { "deviceId": "dev-x", "platform": "android" }
  response body:
    { "detail": { "reason": "project_not_found", "message": "..." } }
```

`Authorization`, `Cookie` and similar headers are **always** redacted, and
bodies are truncated at 4 KB. Because submissions carry respondent data,
logging defaults to on only when `ENVIRONMENT=development`; set `HTTP_LOG=true`
to force it on, `HTTP_LOG=false` off, or `HTTP_LOG_BODIES=false` to keep the
request lines without any payloads.

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
