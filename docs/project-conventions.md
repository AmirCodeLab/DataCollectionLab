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
   Kotlin — must pass every vector identically. A vector passing on one and
   failing on the other is a release blocker, never a platform difference.
   Four sets, because one format cannot express all four questions:
   `conformance/vectors` (evaluation), `crypto` (envelope bytes),
   `sensitivity` (which forms publish refuses, §10.2), `malformed` (which
   documents are refused before compilation, §10.1).

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
- Refusal is two-stage (§10). **Document errors** (§10.1) are checked first over
  the raw document — is this a Form IR document at all — and only then the
  semantic errors of §10.2. Python does this in `document.py`/`Document.kt`
  rather than leaving it to the deserialiser, because a statically typed engine
  gets that gate free and a dynamically typed one gets nothing: before it
  existed, Kotlin refused nine document shapes and Python raised `KeyError`,
  reaching the API as a 500.
- Expressions are a **typed AST**, never strings. No XPath at runtime.
- `null` is a first-class value. It propagates through arithmetic and comparison
  and only becomes boolean at the relevance/constraint/required boundary.
- `relevant` and `constraint` coerce null to **true**; `required` and `readOnly`
  coerce to **false**.
- Non-relevant fields **retain** their values but are excluded from export.
- Recalculation runs in topological order; document order breaks ties so the
  result is deterministic.

## Where the conformance architecture stops protecting you

Rule 2 is the strongest guarantee in this repository, and it has a boundary that
is not obvious from inside it. **The vectors cover the engine. They cover
nothing above it.**

A vector is a comparison between two implementations. That is what gives it its
power and it is also the whole of its reach: where there is only one
implementation, there is nothing to compare, and a vector cannot be written at
all. So the boundary is not a matter of coverage to be improved — it is
structural.

```
 Python reference  ==  Kotlin engine        <- vectors compare these
 ------------------------------------------------------------------
                       FormNavigator        <- Kotlin only. No vector reaches here
                       FormStore
                       CollectionViewModel
                       CollectionScreen (Compose)
```

Below the line: evaluation, null semantics, relevance and constraints, screen
planning, the crypto envelope bytes, publish-time sensitivity, document-shape
refusal. Four vector sets, both engines, and a disagreement is a release
blocker.

Above the line, Kotlin-only and unreachable by any vector:

- **`FormNavigator`** — the interactive cursor every client drives (`next`,
  `previous`, `canFinalize`, `goToFirstBlocking`). The Python reference has no
  cursor; it answers questions about a form, it does not walk one.
- **`FormStore`** — which form versions a device holds and which it may drop
  (sync §5, retention per Form IR §9). The Python reference has no device and
  nothing to retain.
- **The ViewModels** — `CollectionViewModel`, `SubmissionListViewModel`. Op log
  writing, media capture wiring, error surfacing.
- **The UI** — `CollectionScreen` and everything it renders.

And one thing that is **not** Kotlin-only and still cannot be reached, which is
worth separating because it is the least obvious of the three:

- **Which form version a caller validates against.** A vector hands an engine
  one compiled form; an engine never chooses. So no vector can catch "it
  validated against the wrong version" — the choice happens in the caller, and
  vectors cannot see callers. `choice-008` and `choice-009` make v1 and v2
  *disagree* about one value, which is what makes the mistake detectable
  anywhere at all, but neither vector fails when a caller binds wrongly; they
  fail when the engine gets membership wrong. Break 40 records that as a
  structural gap rather than a coverage one.

  It has two callers and both need their own test: the client
  (`FormCatalog.compiledFormForSubmission`, break 30) and the server
  (`forms.service.compiled_form_for_submission`). In both, the fix was to remove
  the choice rather than test it — neither takes a version parameter, so the
  wrong form is not something a caller can ask for.

What watches that layer, and all there is:

| Layer | Watched by | Break |
|---|---|---|
| `FormNavigator` | `NavigatorTest` (`:shared:form-engine:jvmTest`) | 21 |
| The collection screen's date question | `DateQuestionTest` (`:clients:composeApp:jvmTest`) | 23 |
| `FormStore` retention and the manifest | `FormStoreTest`, `FormDeliveryTest` (`:shared:core:jvmTest`) | 25, 28, 29 |
| Which form version a submission opens against | `FormVersionBindingTest` (`:clients:composeApp:jvmTest`) | 30 |
| The server address, and what a failed sync says | `ServerConfigTest`, `SyncFailureTest`, `SyncClientTest` (`:shared:core:jvmTest`) | 32 |
| The settings screen, and which forms it lists | `SettingsScreenTest`, `HeldFormsTest` (`:clients:composeApp:jvmTest`) | 32 |
| Which form version the **server** validates against | `test_server_version_binding.py` (`backend`, `-m db`) | 40 |

These exist because a break in that layer passed the vectors. Break 21 put the
§6.2 finalisation gate one level up, in `FormNavigator.next()` — where a
client-shaped fix would land — and **all 39 vectors stayed green** while the
navigator refused to let an enumerator past an unanswered question. Break 23
removed the date field's click overlay: the question became unanswerable and
every vector still passed, because a form whose date question cannot be opened
evaluates perfectly.

**So: if you are adding logic above the engine, a green conformance run is not
evidence about your change.** It is evidence about code you did not touch. Add a
Kotlin test in the same commit and record the break in `docs/known-breaks.md` —
the two rows above are the pattern. And prefer to put the logic *below* the
line, where the vectors can see it: §6.2's gate lives in the shared navigator
with the same three functions in the Python reference specifically so that the
clients could not each decide it for themselves, which is what they had been
doing.

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

# Conformance — four sets, all of them on both engines
python conformance/generate_vectors.py     # regenerate the evaluation vectors
cd backend && pytest tests/test_conformance.py -v
cd backend && pytest tests/test_malformed_conformance.py -v   # document shape, §10.1
./gradlew :shared:form-engine:jvmTest      # the Kotlin half of all of them

# Kotlin engine (from the repo root — one build)
./gradlew :shared:form-engine:jvmTest
# assembleDebug depends on verifyNoBundledFormDebug, which fails if any APK
# entry carries a Form IR document. Forms come from the server, not the binary.
./gradlew :clients:androidApp:assembleDebug
./gradlew :clients:desktopApp:run

# The shared UI, above the line the vectors reach — see "Where the conformance
# architecture stops protecting you". Headless: Compose renders offscreen.
./gradlew :clients:composeApp:jvmTest

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

`.github/workflows/ci.yml` — five jobs, all of them blocking: **backend**
(ruff, mypy, the API contract check, pytest without `db`), **db** (pytest
`-m db` against a PostGIS service), **kotlin** (`:shared:form-engine:jvmTest`,
`:shared:core:jvmTest`, `:clients:composeApp:jvmTest`), **web** (typecheck,
lint, test, build), and **suites**.

These are the same commands listed above. Run them locally before pushing —
but the point of the workflow is that nobody has to remember to.

**`suites` watches the other four.** It fails if a test suite exists in this
repository and no CI step runs it:

```bash
python scripts/check_ci_runs_every_suite.py            # local
python scripts/check_ci_runs_every_suite.py --strict   # what CI runs
```

It is there because the answer has been "yes" three times — this workflow was
uncommitted for weeks, `npm run lint` exited 0 with no eslint config, and
`:clients:composeApp:jvmTest` was absent from the kotlin job. None of them was
ever a red build. A suite nobody runs does not read as a gap, it reads as
coverage, which makes it worse than having no suite at all.

It enumerates rather than trusting a list, because a list would drift exactly as
the suites did: Gradle suites from test source directories that contain test
files (a *task* existing is not a suite existing — this build declares nine test
tasks and three have sources), pytest by asking `--collect-only` whether the
`-m db` / `-m "not db"` split covers every test, vitest by asking `vitest list`
whether any test file falls outside its `include` glob. It also fails the other
way, on a CI step that runs an empty suite — green paperwork over nothing.

Two things to know when it fails on you. **Anything it cannot classify is a
failure**, never a pass; a new test source set means teaching
`TEST_SOURCE_SETS`, and that is deliberate, because a guard that ignores what it
does not recognise decays into the thing it was written to prevent. And
`--strict` is what makes a missing toolchain a failure instead of a skip — "we
could not check" reported as green is the whole problem. The one case it cannot
catch from inside CI is the first one: with no workflow there is no job to
notice. `./scripts/status.sh` section 5 asks locally.

## Conventions

- Python: ruff, line length 100, type hints everywhere, mypy strict on `app/`
- Kotlin: official style, explicit visibility on public API
- Commits: imperative mood, scope prefix — `engine: add null coercion at boundary`
- Every behavioural change to the engine ships with a conformance vector
- Migrations must be reversible; self-hosted users run old versions
- **A helper that hands out a database session is an `@asynccontextmanager`,
  never a bare async generator you iterate.** `async for session in _session(…)`
  with a `break` or `return` leaves the generator parked at its `yield`: the
  `async with` never exits, nothing commits, and the write is discarded with no
  error. It cost a fixture's insert once and surfaced as a foreign-key
  violation in a different test in a different file.
  `backend/tests/test_no_session_generator_loops.py` is the lint; the FastAPI
  dependencies in `api/deps.py` are the one exception, because FastAPI drives
  the generator to completion itself
- A guarantee is not defended until its break has been watched to fail —
  record it in `docs/known-breaks.md`
- A defect left unfixed on purpose goes in `docs/known-defects.md` with the
  reason it is still open. Knowing about a defect and having fixed it are
  different claims, in the same way a test existing and a test having caught
  something are

## Current phase

**Phase 0 — architecture proof: complete.**
**Phase 1 — clients: complete enough to move on (Android collection app).**
**Phase 2 part 1 — usable by one real customer: in progress.**

Phase 2 part 1 is four items, in this order, and nothing else until a real form
authored by someone other than us is collected on a real phone and exported:

0. **Form delivery — done**, and verified on an emulator and now on a
   **physical Pixel** against a live server: an APK with no form in it syncs,
   receives the form, opens it, collects answers and pushes them back (see
   item 1's hardware run below, which exercises this end of it too).
   "No form in it" is now a **build guard** rather than a hand check: `:clients:androidApp:verifyNoBundledFormDebug`, which `assembleDebug`
   and `installDebug` both depend on, fails if any APK entry carries a Form IR
   document. It looks for the document (`"irVersion"` and a colon, mandatory
   per §10.1) and not for the seed form's name — the name check does not hold
   on this tree, because `SubmissionListScreenPreview` puts `household_survey`
   in a `@Preview` literal and previews compile into the APK. Writing the guard
   immediately caught the failure it was written for: deleting a bundled form
   from the source tree leaves stale copies under `build/` and the next
   incremental `assembleDebug` packages one. Break 31
1. **Configurable server URL + settings screen — done**, and verified on a
   physical Pixel 6 Pro over Wi-Fi against a server on the LAN — the first time
   a real handset in this project has reached one. See below
2. XLSForm import — not started
3. Export: CSV, XLSX, Stata, SPSS — not started

Item 0 was not in the original list and had to be: `FormCatalog` read one form
out of the app's own resources, so "a form authored by someone other than us,
collected on a real phone" was not a thing the system could do at all. The other
three items do not close that on their own.

How it works (sync §5.1): `GET /sync/pull?scope=forms&deviceId=…` returns a
**manifest** of the versions deployed to that device's environment — ids,
titles and content checksums, a few hundred bytes — and the device fetches the
IR for versions it does not hold from `GET /forms/versions/{formVersionId}`. The
seeded household survey is 36 KB of IR against a 300-byte manifest, which is the
whole argument for the split on the connections this product exists for.

Three rules are load-bearing and each has a break recorded against it:

- **Publishing is not deploying.** A published version nothing has deployed
  reaches no device. `POST /forms/versions` takes `deployTo` and the response
  reports `deployments`, so "published" cannot be misread as "on the phones"
- **Deployment is per environment.** `form_deployment.environment_id` scopes the
  manifest, so a staging form cannot reach a production device
- **A device retains every version it still refers to** (Form IR §9), not just
  the newest. Withdrawal marks a version undeployed; only "withdrawn AND no
  local submission refers to it" deletes it. An enumerator holding a v2 draft
  the morning v3 deploys must still be able to open it — the op log records the
  answers, never the questions

There is **no bundled form and no fallback to one**. A device that has not
synced has no forms and says so. `specs/examples/household_survey.json` is the
seed's input, not the app's.

What item 0 did not close is in `docs/known-defects.md` 3–5: a device's
environment is derived from its project rather than assigned (so every device
gets production), nothing retires a deployment, and the environment rule is
written twice in two modules that agree by inspection rather than construction.

### Item 1 — the server address, and the settings screen

The address was a compile-time constant per platform (`defaultSyncBaseUrl`), so
pointing a phone at a server meant rebuilding the app. That is workable for an
emulator, whose host is always `10.0.2.2`, and it is the reason a **physical
device had never once reached a server**: no constant is right for one.

`ServerConfig` (`shared/core`) now holds the address in the SQLCipher database
and `defaultSyncBaseUrl()` is the **fallback** a fresh install uses until
somebody saves one. Three things about it are load-bearing, and break 32 covers
all of them:

- **The address is asked for, not held, and the caller cannot choose it.**
  `SyncClient` and `MediaUploader` take the `ServerConfig` itself — not a
  `String`, and not a `() -> String`. The lambda was tried first and it is
  exactly wide enough to express the mistake it existed to prevent: the app's
  own wiring passed `{ defaultSyncBaseUrl() }`, all 264 tests passed, and on a
  handset the settings screen reported an address saved while the sync went to
  the compile-time constant and nothing reached the server. It is a compile
  error now (break 35), on the same principle as the form-version fix — the way
  to stop a caller choosing wrongly is to stop it choosing
- **…and read once per sync, not once per request.** `refreshCrypto` caches the
  recipient set of the project the *server* names and the push encrypts to it,
  so a sync split across two servers would wrap content keys to one project and
  hand the ciphertext to another. The second server stores it, reports success,
  and holds answers only a third party's private key can open
- **"Nobody has configured this" is a distinct state.** No row means the
  platform default is in effect, and the screen says so. Seeding the row with
  the default at first launch collapses that into "configured", and the two
  need different next steps

`parseServerUrl` reads what a person types rather than a URL: a missing scheme
becomes `http://`, trailing slashes go (they produce `//api/v1` on every
request, which some servers route and some 404). It **refuses** rather than
guesses on a non-http scheme, a bad port, and — worth naming — an address
ending in `/api/v1`, which is what copying out of the API docs gives you and
which produces a perfectly reachable server on which every request 404s.

**A connection failure names the address and a cause in plain words.**
`SyncFailure.describe` turns `Connect timeout has expired` into a sentence that
says which server was tried, distinguishes a wrong address from a stopped
server from a wrong network, and keeps the platform's original text in
parentheses — the sentence is a guess about a class of failure, the original is
the fact. It matches on class names and message text across the whole cause
chain because there is no common exception type: Ktor CIO raises
`java.net.ConnectException` on the JVM and Android and a `PosixException` on
Native, and `UnresolvedAddressException` has no message at all. It also
explains `10.0.2.2` and `localhost` by name, because those are the two wrong
answers *the app itself supplies*.

The settings screen (`SettingsScreen`, `SettingsViewModel`) answers the three
forms of "why is this phone not working": which server, how the last sync went,
and which form versions are actually here. Two things about the form list, both
found the hard way:

- it is `FormCatalog.observeHeld()` and **not** `startable()` — a device retains
  every version a local submission still refers to (Form IR §9), and answering
  with the narrower list would report a form as absent while a draft was open
  against it. Withdrawn versions carry a chip saying so
- it is **observed, not read once**. Read at construction, it reported "no
  forms" after a successful sync had just delivered one — with the form in the
  database underneath it and no error anywhere. Relaunching the app cleared it,
  which is the worst symptom available: it reads as an intermittent sync fault.
  Break 33, and it was found on a device rather than constructed

**Test connection** asks `GET /health` and moves no data, which is what makes
it safe to press against an address you are not sure of yet. It reports the
server's `environment`, because the failure a reachability check cannot
otherwise see is the one where everything works and the address is wrong: a
phone on staging syncs perfectly and files a morning's interviews where nobody
will look for them.

There is deliberately **no Sync button on the settings screen**. Sync belongs to
the submission list, where the outbox is.

### The run on real hardware, 2026-09-02

The reason this item existed: a physical device had never reached a server. It
has now. Pixel 6 Pro, Wi-Fi, a server on the LAN — not `10.0.2.2`, which is a
loopback alias the emulator resolves to its own host and therefore cannot stand
in for a network hop.

Fresh install (`pm clear`, device `dev_aecfb103`), then, entirely from the
phone:

1. Settings showed `http://10.0.2.2:8000` and *"Using this build's default
   address. No address has been set on this device."*
2. Typed `192.168.2.44:8001`; stored as `http://192.168.2.44:8001` — scheme
   added, and on the emulator run a trailing `/` was dropped
3. **Test connection:** *"Reached http://192.168.2.44:8001 — this is the
   development server."* Save greyed out (draft equals what is in effect),
   Reset appeared
4. **Sync:** manifest, then the document. Settings then listed *"Household
   Survey — household_survey · v2 · fetched 2026-09-02 09:25"*
5. Started a submission on it. The form opened at 1/3; answering the consent
   question expanded the screen plan to 25 — live relevance on a handset
6. Navigation past an unanswered required date was **allowed** and the button
   only offered Finalize on the last screen (§6.2: navigation is never gated,
   finalisation always is)
7. Synced the answers back. `submission_op` on the server holds
   `set enumerator_name` and `set consent` from `dev_aecfb103`, both as
   **ciphertext** (32 and 21 bytes) — the project is `project_e2e` and the
   server stored what it cannot read

So the whole chain is closed on real hardware: a form published on a server,
deployed to an environment, delivered to a phone that had never held it,
opened, answered, and pushed back encrypted.

One practical note for whoever repeats this: adb-over-Wi-Fi to this handset
drops whenever its DHCP lease changes, and it changed twice mid-run
(`192.168.2.49` → `.12`). Run the sequence as one script rather than as a
series of calls.

Phase 0 deliverables, with evidence (`./scripts/status.sh` recomputes this):

1. Form IR specification — done incl. screen flow (§11); 34 conformance
   vectors pass identically on the Python and Kotlin engines
2. Sync protocol specification — done; server push/pull implemented
   (`backend/app/modules/sync/`, commit e9f30d7) and the client op log +
   outbox live in `shared/core` (`SubmissionStore`, 5 JVM tests)
3. ERD / database schema — done; Alembic migration 0001 in
   `backend/migrations/versions/`, migration tests green against Postgres
4. OpenAPI contract — done; `specs/openapi.json`, generated from the app by
   `scripts/generate_api_contract.py` and never hand-written. 24 operations,
   every one with a `response_model` and a typed request body. The console's
   wire types are generated from it too, so the last hand-mirrored copy —
   `SUBMISSION_STATUSES` in `web/src/api/types.ts` — is gone along with the
   test that watched it. CI regenerates both and fails on any difference
5. Encryption envelope — done; 8 crypto vectors byte-identical on both engines
6. iOS Compose spike — done: builds and runs on the iPhone 17 Pro simulator;
   the submission list renders with the SQLDelight native driver and a form
   compiling on-device (the app supplies SQLite at link time — now SQLCipher
   rather than `-lsqlite3`, see §14 below and
   `clients/iosApp/Configuration/Config.xcconfig`). The form was the bundled
   one when this was verified; forms now arrive over sync (Phase 2 item 0) and
   the spike has not been re-run on a device since

Media capture is built for image, signature and GPS point (§6, sync §9).
Capture goes camera buffer → compress in memory → encrypt in memory → write
chunks, so the plaintext photograph never reaches the filesystem; the per-file
media key lives in the SQLCipher database, which is what makes a staged file
encrypted at rest without a second key hierarchy (§6.1). The staged chunks ARE
the upload — encrypted once, sent byte for byte — so a resumed upload provably
sends the same bytes as the first attempt. CameraX behind expect/actual on
Android, AVFoundation on iOS, **nothing at all on desktop** (see below); the
viewfinder is `clients/composeApp` and `shared/core` constructs no View.

Upload is resumable per §6: 4 MiB chunks, each under its own derived nonce,
content hash over CIPHERTEXT. `POST /media/upload-sessions` is idempotent and
returns the chunks the server already holds — that is the whole of resumption,
and there is deliberately no second endpoint that answers the same question. An
op referencing a file that has not arrived is accepted and marked pending, and
the pair resolves in either order; there is no foreign key between them, because
one is routinely first. Image compression and the GPS accuracy threshold are per
project (`GET /devices/{id}/media-policy`), and a fix worse than the threshold is
refused and shown with its accuracy rather than stored — a phone indoors reports
a two-kilometre fix with exactly the authority of a good one.

Extending the engine was the price of this: `FormValue` in Kotlin could not
represent a media reference or a geopoint's accuracy, both of which are in Form
IR §2.1. `FormValue.MediaRef` and `GeoPoint.alt/accuracy` close that, with five
new conformance vectors (`media-00*`, `geopoint-00*`) passing identically on both
engines. The Python reference needed no change — it holds values as plain Python
and always read both shapes, which is exactly the kind of divergence a typed
engine hides until something tries to use it.

Phase 1 so far: Android collection screen in `clients/composeApp` — paged
navigation driven by the shared engine's screen plan, live relevance and
constraints, local op log, RTL, tested on a real device with a 52-question form.

Whether an invalid answer stops the enumerator moving on is now decided in the
spec rather than per platform (§6.2): **navigation is never gated, finalisation
always is.** It was unspecified before — §11 says nothing about validity, no
vector covered it, and the clients were observed differing, which is the drift
the conformance architecture exists to prevent hiding in an undefined rule
rather than a wrong one. The gate lives in `FormNavigator`
(`canFinalize`, `finalizationBlockers`, `goToFirstBlocking`) with the same three
functions in the Python reference, five vectors (`screens-004`…`008`) and
`NavigatorTest` — which exists because the vectors cannot see the navigator
class, so a gate added to `next()` would pass all 39 of them.

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
- **Desktop collects nothing, and currently pretends otherwise.** Desktop was
  never in Phase 1 scope — it is the supervision and review client — but the
  collection screen is shared code and renders there anyway, with the media
  widgets drawn and inert: the gallery button calls a `rememberGalleryPicker`
  that reports "nothing chosen", the signature canvas draws strokes and its
  Save button returns at `mediaCapture ?: return`, and Capture position answers
  the permission request `true` before doing nothing. No message, no refusal —
  the enumerator sees a widget behaving as though they had not tapped it. Filed
  as defects 1 and 2 in `docs/known-defects.md`; do not read the media section
  above as covering desktop
- **Media beyond image, signature and geopoint.** Audio, video and file upload
  are not built. They are in the IR and deliberately NOT in the collection
  screen's supported types: rendering a widget that cannot answer a question is
  worse than skipping it, because the enumerator thinks they have answered.
  `geotrace` and `geoshape` likewise
- **No thumbnail of a captured photograph.** The image question shows the file
  name and its upload state, not the picture. Decoding a staged chunk back for
  display is one call (`MediaStaging.readChunk`); what is missing is the
  platform bitmap plumbing to draw it
- **Media has been exercised in tests and on the JVM, not on real hardware.**
  The Android APK builds and all three targets compile, but no photograph has
  been taken on a device or a simulator through this path. Everything a test can
  hold is held — staging, encryption, chunking, resumption, the accuracy
  threshold, the server's three endpoints — and the CameraX and AVFoundation
  actuals are the part that only a device can prove
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
- **One gap the contract work found and did not close.** Three endpoints
  return 422 for a domain refusal, colliding with FastAPI's own
  request-validation 422, so only one of the two bodies can be declared.
  Moving those refusals to their own status code would fix it, and that is an
  API change rather than a patch. (The other gap that work found — a 500 from
  `POST /forms/compile` on a malformed document — is closed: §10.1, both
  engines, 22 vectors in `conformance/malformed`)
