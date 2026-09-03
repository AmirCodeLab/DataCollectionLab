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
   Five sets, because one format cannot express all five questions:
   `conformance/vectors` (evaluation), `crypto` (envelope bytes),
   `sensitivity` (which forms publish refuses, §10.2), `malformed` (which
   documents are refused before compilation, §10.1), `functions` (every §4.3
   function against every value shape, §4.7).

   **`functions` is the only one that is not a selection**, and that is what it
   is for. Every other set holds cases somebody thought of, which is the same
   limitation the coverage ledger exists to work around one layer up. The
   function surface had that hole for its whole existence: nothing in the
   corpus had ever put text where a number belongs, because until dataset
   columns existed nothing could. When the cross product was finally run, 762
   of 1,395 probes disagreed between the engines and three §4.3 functions
   turned out to be unimplemented in Kotlin. Break 46.

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

### The rule, not the list

Everything above is Kotlin-only, and for two years the boundary could be
described that way. It cannot any more, and the general statement is worth more
than the list:

> **A vector fixes the inputs and compares the outputs. So anything that
> decides *which* compiled artifact is used — rather than what that artifact
> evaluates to — is structurally invisible to it.**

That is not a coverage gap to be closed by writing more vectors. A vector hands
an engine one compiled form and one set of answers; the engine never chooses
either. The choosing happens in a caller, and a caller is precisely what the
format cannot express. Five instances so far, in the order they were found:

- **Which form version a submission opens against.** `choice-008` and
  `choice-009` make v1 and v2 *disagree* about one value, which is what makes
  the mistake detectable anywhere at all — but neither vector fails when a
  caller binds wrongly; they fail when the engine gets membership wrong.
  Break 40. Two callers, both needing their own test: the client
  (`FormCatalog.compiledFormForSubmission`, break 30) and the server
  (`forms.service.compiled_form_for_submission`).
- **Which form version the server validates against.** The same choice, made
  in the other process. `test_server_version_binding.py`, break 40.
- **Which dataset version a form's choice lists resolve to.** Item 4 part 2.
  The IR names a dataset by *key* (§3) and a key is not a version, so the
  binding happens at publish, in `form_version_dataset`. Break 42 removed
  `_resolve_dataset_pins` — a form naming three dataset keys then published
  against nothing, and **310 tests and every conformance vector stayed green**,
  because the IR was valid, compiled, and both engines agreed about it either
  way. `test_form_dataset_pinning.py`.
- **Which form versions a device holds at all.** `FormStore` retention, breaks
  25, 28, 29 — the same shape one level further out.
- **Which form version and which dataset version an export explains a
  submission through.** Item 5, and the same shape at the far end of the
  pipeline: one export spans every version its submissions sit on, so the
  binding is per submission or it is wrong. Break 61 renames a village between
  two published lists and watches a v1 submission acquire a name that did not
  exist when it was collected — with every column present, correctly typed, and
  nothing in the file to see.

**The tell is grammatical.** If a change alters what an answer *evaluates to*,
a vector can see it. If it alters *which document, version or list* the
evaluation runs against, no vector can, however many are written. In every case
above, the fix that worked was the same one: remove the choice rather than test
it — `compiledFormForSubmission` takes no version parameter and
`dataset_rows_for` takes none either, so the wrong artifact is not something a
caller can ask for. A test is what catches the mistake being reintroduced; the
missing parameter is what stops it being made.

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
| Which dataset version a form version's lists resolve to | `test_form_dataset_pinning.py` (`backend`, `-m db`) | 42 |
| That a collection screen was given a dataset source at all | nothing — see break 57 | 57 |
| Companion CSVs: read, refused, or reported missing | `test_xlsform_datasets.py` (`backend`) | 43 |
| That an export contains no non-relevant answer | `test_export.py`, `test_export_reads_only_answers.py` (`backend`) | 58, 60 |
| That a repeat row is keyed on a stable id and not a position | `test_export.py` (`backend`) | 59 |
| Which form version and which dataset version an export explains a submission through | `test_export_binding.py` (`backend`, `-m db`) | 61 |
| That a value survives a `.dta`/`.sav` as well as a CSV, and that a column is the type it says | `test_export.py`, `test_statistical_writers.py` (`backend`) | 62, 63, 64, 65 |

These exist because a break in that layer passed the vectors. Break 21 put the
§6.2 finalisation gate one level up, in `FormNavigator.next()` — where a
client-shaped fix would land — and **all 39 vectors stayed green** while the
navigator refused to let an enumerator past an unanswered question. Break 23
removed the date field's click overlay: the question became unanswerable and
every vector still passed, because a form whose date question cannot be opened
evaluates perfectly. Break 42 is the cleanest example of the rule above: a
published form with no record of which villages it offered, and nothing
anywhere to notice, because every vector was still asking the only question a
vector can ask.

**Break 57 is the sharpest instance and the newest.** `CollectionViewModel`
resolved choices through the engine correctly and built its `FormInstance` with
**no `DatasetSource`**, so every dataset-backed select came back empty. 502
backend tests, every conformance vector and every composeApp test passed — the
UI tests construct `QuestionUi` directly and never build an instance, and the
engine tests build one *with* a source. The seam between them is covered by
neither, and only tapping through the form on a handset found it. The fix was
not a test: `FormCatalog.datasetSourceForSubmission` is now the only way to
obtain a source, so a view model cannot forget to ask for one.

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

# XLSForm import (never a second code path — this is the API's importer)
python scripts/import_xlsform.py survey.xlsx --out reports/ --ir form.json
#   exit 0 clean, 1 has errors, 2 not a readable workbook
#   real third-party fixtures: backend/tests/fixtures/xlsform/ (+ PROVENANCE.md)
#   companion CSVs are looked for beside the workbook; --datasets DIR points
#   elsewhere. A file the survey sheet names and cannot be found is an error
#   naming it, never a question that quietly has no options.

# The UCL form's five companion CSVs — synthetic, adversarial, not committed
python scripts/generate_ucl_datasets.py                    # ~3 MB at real scale
python scripts/import_xlsform.py backend/tests/fixtures/xlsform/ucl-biomass.xlsx \
    --datasets backend/tests/fixtures/xlsform/ucl-biomass-datasets --out reports/

# Export (item 5). Same exporter the console will use, same process.
python scripts/export_submissions.py household --out exports/
python scripts/export_submissions.py household --format xlsx --shape wide
python scripts/export_submissions.py household --format dta    # Stata
python scripts/export_submissions.py household --format sav    # SPSS
#   .dta/.sav: names are capped at Stata's 32 chars and shortened
#     deterministically; a column holding ENCRYPTED is stored as TEXT because a
#     numeric column cannot carry it. Both are printed and both are per column
#     in the manifest — read it before writing a do-file against the columns
# …and the same thing over HTTP, which is what the console uses:
#   GET /api/v1/exports/{formId}?format=dta&shape=long   -> a zip

# What an export costs, across the three form versions a real project has
python scripts/measure_export.py                        # 3000 submissions
python scripts/measure_export.py --submissions 12000 --villages 37852
#   Needs Postgres. Seeds its own scratch database and drops it (--keep to
#   keep it, --reuse to skip reseeding). Reports wall clock, Python peak,
#   process RSS and file sizes per format, and counts dataset row fetches so
#   "is a label resolved per row or per version" is measured, not assumed.
#   long (default): parent file + one per repeat, keyed (submission_id,
#     instance_id) — the STABLE id, never a position
#   wide: one row per submission, repeats flattened positionally. Offered
#     because people ask for it; the manifest says not to join on it
#   a CSV bundle carries manifest.json, an .xlsx a `_manifest` sheet

# Conformance — five sets, all of them on both engines
python conformance/generate_vectors.py           # the evaluation vectors
python conformance/generate_function_matrix.py   # the §4.3 function surface
cd backend && pytest tests/test_conformance.py -v
cd backend && pytest tests/test_malformed_conformance.py -v   # document shape, §10.1
cd backend && pytest tests/test_function_conformance.py -v    # §4.3 x every shape
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

# What a dataset costs on a real phone (Form IR §3.2, item 4 part 5)
scripts/measure_datasets_on_device.sh 38000    # needs a connected debug build
#   Reports first-sync write, storage, per-keystroke filter latency and the
#   second-sync delta. Meant to be run and published whatever it says: the
#   first cut cost 1,589 ms on the first keystroke and only a Pixel said so.

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
(ruff and mypy over `app`, `scripts` and `conformance`, the API contract check,
pytest without `db`), **db** (pytest `-m db` against a PostGIS service),
**kotlin** (`:shared:form-engine:jvmTest`, `:shared:core:jvmTest`,
`:clients:composeApp:jvmTest`), **web** (typecheck, lint, test, build), and
**suites**.

These are the same commands listed above. Run them locally before pushing —
but the point of the workflow is that nobody has to remember to.

**Two guards watch the other four, and they ask different questions.**

`check_every_directory_is_gated.py` asks whether every directory holding source
is **read** by something. It exists because the answer was no for the life of
the repository: CI ran `ruff check .` and `mypy app` from `backend/`, so
`scripts/` and `conformance/` were outside both — the API-contract generator,
the XLSForm importer's CLI, the dev seed and every vector generator, none of
them ever linted or type-checked. It read as covered because the job is called
"backend (ruff, mypy, pytest)" and was green. First run: 3 ruff errors and 602
mypy errors, including a wrong return annotation in the function-matrix
generator that had been there since it was written. Break 70.

It parses the gates out of `ci.yml` rather than holding a list, so it tracks
what CI does; and a directory that is neither gated nor named in `ACKNOWLEDGED`
with a **reason** is a failure. The acknowledged gaps today are Kotlin style
(no ktlint or detekt is configured at all), and mypy over `backend/tests` (212
errors) and `backend/migrations`. Being on that list is a decision somebody can
argue with. Being absent from it was the hole.

`check_ci_runs_every_suite.py` asks whether every suite **runs**. It fails if a
test suite exists in this repository and no CI step runs it:

```bash
python scripts/check_ci_runs_every_suite.py            # local
python scripts/check_ci_runs_every_suite.py --strict   # what CI runs
# …and the question one layer out: is every DIRECTORY read by a gate?
python scripts/check_every_directory_is_gated.py --strict
# It also checks every vector on disk was EXECUTED, not merely that the suite
# is wired up — run the Kotlin conformance suites first or it has nothing to
# read. Adding nine vectors once left :shared:form-engine:jvmTest UP-TO-DATE
# reporting 39 tests and BUILD SUCCESSFUL (break 41).
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

Phase 2 part 1 is six items, in this order, and nothing else until a real form
authored by someone other than us is collected on a real phone and exported.
Items 3 and 4 were not in the original list of four: item 3 because choice
membership turned out to be unguarded in shipped code, and item 4 because
external choice lists are their own pipeline rather than an importer feature.
Both are written up below.

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
2. **XLSForm import — done**, and verified on a physical Pixel: a real
   third-party form (`choice_filter_test.xlsx`, pyxform, unmodified) imported
   through `POST /api/v1/forms/import`, published, deployed, delivered, and
   collected. `scripts/import_xlsform.py` runs the same importer in the same
   process. Diagnostics carry sheet/row/column/value as fields; the report is a
   durable .md/.html file grouped by severity and by whose problem it is; the
   whole report is stored on `form_version` (five columns, all-or-nothing by
   CHECK) so "how was this imported and what did not survive" is answerable
   from the database. See below
3. **Choice membership — done.** Split out of item 4 when it turned out
   neither engine read `choices` at all: a `select_one` could hold "purple" and
   both engines called the form valid and finalisable, in production. Form IR
   §6.3/§6.4, error kind `choice`, nine vectors on both engines. See below
4. **Datasets and `select_one_from_file` — DONE.** The acceptance is met: the
   UCL form's cascading region → district → village works on a Pixel 6 Pro,
   through the real collection screen, over 37,852 villages delivered from a
   server on the LAN, and the answers came back to the server resolvable
   through the form version's pins. Written up below. Two measured defects
   remain open and neither blocks collection: a 56-second delta application and
   a filter regression when two dataset versions are held
   (`docs/known-defects.md` 9 and 10), both downstream of defect 4 — nothing
   retires a form deployment
5. **Export: CSV, XLSX, Stata, SPSS — IN PROGRESS.** All four formats are done,
   in both shapes, with the manifest and the version bindings; data now leaves
   this system. What is left is the HTTP route the console needs. Scope, what
   landed and what is still missing are below

**Label interpolation (Form IR §7.1) — done.** Split out of nothing: it was the
`output_in_label` error class, which the UCL form hit six times and which had no
rewrite for the case that mattered. `Minimum circumference for this part of the
plot is ${size_constraint} cm` cannot be written statically because the
threshold is computed, so "rewrite it" meant "delete the number".

Counted before it was built, because that is what decides it: **7 of 22 distinct
corpus forms, 47 cells, 49 references** — and 37 of those 49 point at a
`calculate` or device metadata, values that do not exist until the form runs.

Four decisions worth not re-making:

- **`label` did not change type.** It is still `{lang: string}`; slots are
  `{0}` and the expressions live beside it in `labelArgs`. Every renderer kept
  compiling, and one that ignores the args shows `{0}` — visibly broken rather
  than silently missing a number
- **The isolates are the feature.** Every value is wrapped in U+2068/U+2069 by
  the *engine*, so both engines emit the same string and one vector asserts the
  codepoints by number. Break 55. Without them a Latin number inside Arabic text
  gets dragged out of position — the page-indicator bug again
- **Arguments are dependencies**, which gets the sensitivity refusal and the
  unresolvable-reference check for free. Break 56 is the one that would have
  shipped: dropping the edge leaves every rendered string correct, so the vector
  asserts the edge and not the render
- **Choice labels are excluded** and still report `output_in_label`. One corpus
  form does it, and an option list whose wording changes as answers change is
  confusing to read

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

### Item 4 — datasets and `select_one_from_file`: IN PROGRESS

**Read this before touching datasets.** The decisions below are made, with
reasons; re-deciding them wastes time and the reasons are not obvious from the
code alone.

Why it is its own item and not an importer fix: external choice lists drag in
server-side dataset storage, a `datasets` scope on `/sync/pull`, a local store
inside SQLCipher, engine resolution of `choices.kind = "dataset"`, and
incremental sync. Folding that into XLSForm import makes both half-done.
`select_one_from_file` is also the top missing feature measured across 27 real
forms (16 uses; `atan` was the only missing function), so it is chosen by
evidence rather than guessed.

**Five parts. Parts 1 and 2 are landed; part 3 is next.**

1. **Server — DONE** (`f26ab59`, `2f6cf0f`). Migration 0004:
   `dataset_record.row_hash`, an index on
   `(dataset_version_id, record_key, row_hash)`, and `form_version_dataset`.
   `entities/service.publish_dataset_version` publishes immutable versions,
   idempotent by content, refusing empty datasets and blank or repeated keys.
2. **Import — DONE.** An XLSForm's companion CSVs become dataset versions,
   pinned to the form version at publish. Written up below.
3. **Engine — DONE.** `choices.kind = "dataset"` resolution and the `$row`
   filter, on both engines, with 14 `dataset-*` vectors and 7 `cast-*`.
   Written up below; the performance contract it settles is Form IR §3.2.
4. **Delivery — DONE.** `scope=datasets` on `/sync/pull`,
   `GET /datasets/versions/{id}/rows` paged and resumable, `DatasetStore` in
   SQLCipher, and `StoredDatasetSource` bridging it to the engine. Written up
   below.
5. **Incremental sync — DONE**, with the measurements. Written up below.

### Part 2 — what the importer does with a companion file

`select_one_from_file villages.csv` names a file that is **not in the workbook**.
That is the whole difficulty: an importer reading only the .xlsx cannot know
whether the question has two options or fifty thousand, or any.

So the files travel with the upload. `POST /forms/import` takes repeated
`datasets` parts beside `file`; `scripts/import_xlsform.py` looks in the
directory holding the workbook and `--datasets` points elsewhere. Both hand the
same `companions={name: bytes}` to the same `import_workbook`, because a second
code path would be a second answer about what a form becomes.

**Nothing is lost in silence, one level out from the cell ledger.** Every file
the survey sheet names ends in exactly one of three states — read, refused with
a reason, or reported missing by name — and every file *supplied* that nothing
names is reported too, because that is a rename on one side of the pair and
otherwise shows up as a missing list while the list sits in the upload. A
question whose file did not arrive is **dropped**, not imported with an empty
choice list: an unanswerable question in valid IR is the exact failure the
whole design is about. Break 43 is the sharp edge — reporting a missing file
once per *file* rather than once per *question* left three UCL questions gone
with nothing pointing at their rows, and the coverage ledger caught it.

**A dataset-backed select does not publish yet, and that is deliberate.**
`select_one` is a collectable dataType and a *dataset-backed* `select_one` is
not a collectable question: `CollectionViewModel` reads `choices.items`, which
a dataset-backed list has none of, so the question would deploy and arrive with
nothing under its label. Defect 7, one axis over. So the registry grew a second
list — `choiceSources` in `specs/collectable-types-v0.1.json` — and the
importer asks it per question. When parts 3 and 4 land, `dataset` joins that
line and the refusal stops, from one file, with no code change on either side.

Three more decisions worth not re-making:

- **The pinning is made unexpressible, not tested.** `publish_version` refuses
  a form that names a `choices.dataset` key with no pin, a pin for a key the
  form does not name, a pin twice, a pin to another project's data, and a pin
  whose version is of a different dataset. Break 42: removing the resolver let
  a form publish against nothing while the whole non-db suite and every
  conformance vector stayed green
- **Publishing a dataset is its own call**, `POST /projects/{id}/datasets`,
  multipart, **409** on refusal (422 is the framework's, per "The API
  contract"). Idempotent by content *without* a version number, which matters
  because the console re-sends the files on every Publish: a duplicate version
  would tell every device it is behind and cost it a full re-fetch
- **The key rules live in `entities/rows.py`** and both the publisher and the
  importer call them, so the report an author reads before uploading says
  exactly what the server will refuse. Two copies would be the
  `publishable`-versus-the-gate failure one level down

The report gained a **Reference data** section and a **What worked** block, the
second in both the success and the failure branch. That is not decoration: a
report that itemises only failure cannot tell an author whether the half they
care about survived, and a form with one unsupported question reads like a form
that did not import at all.

**Where the UCL form actually stands.** Its five lists are read, checked,
filtered and pinned; its eight `select_one_from_file` questions import (54
questions became 62); the five knock-on `relevant` errors are gone;
`select_one_from_file` has left the roadmap's missing-types list. It still does
not publish, for three reasons that have nothing to do with datasets and were
all there before: `atan` (2 errors, the only missing XPath function across 27
real forms), `${...}` inserted into six labels and constraint messages (§7,
the author's), and a repeat nested in a repeat (§2.3, deferred to IR v0.2).
Plus the dataset-backed collectability gate above, which parts 3 and 4 lift.

### Part 3 — how a filter resolves, and the §12 contract it closes

**The decision, made before either engine implemented it, because it is far
cheaper to decide once than to reconcile twice.** Form IR §3.2 is the normative
version; this is why.

> **The engine never materialises a dataset.** `choices.filter` is decomposed
> once, at compile time, into a **selector** — the top-level `and`-conjuncts of
> the form `$row.column = <expr>`, which a store can answer from an index — and
> a **residual**, evaluated per candidate row. The engine asks a
> `DatasetSource` for the selector's rows and filters those.

Resolution is therefore O(rows matching the selector), never O(dataset), and
that is a property of the interface rather than an optimisation somebody
remembered. Membership (§6.3) is a *lookup*: the answer is pushed into the
source alongside the selector, so with no residual "is this village in the
list" is one indexed question whatever the dataset's size — never "fetch the
list, then search it".

**The alternative that was rejected, and the reason is the boundary rule
above.** The obvious cheap answer is to let the client pass a pre-narrowed
candidate set — it already has SQLite and an index. That makes the *client* the
thing that decides which rows are candidates, which is deciding what the choice
list is, which is a **which-artifact** decision: structurally invisible to a
vector. Two clients would narrow differently, both would pass everything, and
the enumerator on one would be offered villages the other hides. The source is
allowed to be fast. It is not allowed to be selective.

**The vectors assert the narrowing, not only the answer.** `expect.choices`
alone would pass on an engine that scanned 38,000 rows to build the same list,
and on a handset those are not the same engine. So `expect.selector` and
`expect.candidates` are assertions about *the question the engine asked*,
recorded by the harness's own dataset source. That distinction was not
theoretical: the first version read them off the engine's output and caught
nothing (break 45) — an engine asking for every row and filtering them itself
produced the right selector, the right list and the right count.

**What part 3 found that was already broken.** `dataset-005` and `dataset-006`
failed on Kotlin the first time they ran, and the cause was not datasets:
`int("800")` was `null` on Kotlin and `800` on Python, and `int("8a")` raised
`ValueError` on Python. Both shipped. A CSV holds nothing but text, so
`int($row.population) > 1000` is the ordinary case for a dataset filter — it
silently emptied the list on one engine and would have reached the API as a 500
on the other. Nothing had ever fed text to a cast, because until dataset columns
existed nothing in the corpus could. §4.3.1 now defines the casts and
`cast-00*` holds both engines to it. Break 44.

One consequence worth knowing before part 4: a selector expression makes the
field **depend** on what it reads, so changing the region re-resolves the
village list *and* re-checks the village already chosen (`dataset-004`). An
answer that silently stops being a member of its own list is the failure that
edge exists to prevent.

### Part 4 — delivery, and the failure with no symptom

The manifest shape is the form manifest's, one level down: `scope=datasets` on
`/sync/pull` returns a **complete statement** of what this device must hold, and
the rows are fetched once per version, paged, from
`GET /datasets/versions/{id}/rows`. The UCL village list is 37,852 rows against
a manifest entry of about a hundred bytes, and the manifest travels on every
pull.

**What a device is told is derived from the pins**, not from the datasets its
project owns: every dataset version pinned by a form version deployed to it, and
nothing else. The pinning that makes an answer explicable is the same thing that
decides which rows travel.

**The guard, and why it is a shape rather than a check.** The failure here has
no symptom. A device holding last month's village list collects perfectly, syncs
perfectly, and files answers against places that no longer exist; the form
opens, the list scrolls, the search works, and nothing on any screen is in an
error state. So:

- **The resolver takes a form version, never a key alone.** `rowsFor(formVersionId,
  datasetKey)` on the client, `dataset_rows_for(submission_id, dataset_key)` on
  the server. There is no `rowsFor("villages")` and no overload that takes a
  version id, because the answer to that question would have to be "whichever
  version happens to be here". Same shape as `compiledFormForSubmission`
  (break 30) and `_resolve_dataset_pins` (break 42): stop the caller choosing.
- **A stale or half-transferred list resolves to nothing.** Empty, and visible —
  `missingFor(formVersionId)` turns it into a sentence an enumerator reads
  before they start, rather than an empty dropdown they discover in the middle.
  A version is not readable until the page with no `nextCursor` arrives: a list
  that stopped two thirds of the way through is one you can search, scroll and
  choose from.
- **`datasets` is nullable on the wire and `forms` is not.** Null is "nothing
  was said"; `[]` is "your forms reference none", which is an instruction to
  drop what you hold. Collapsing them would have a device delete a village list
  because it synced against an older server — break 28's rule, sign-flipped.

Break 47 is the proof: resolving by `dataset_key` instead of by the pin fails 4
of `DatasetStoreTest`'s 14 and leaves **all 69 vectors and all 382 backend tests
green**.

**Retention is `FormStore`'s rule followed rather than restated.** A dataset
version is kept while any form version *this device holds* pins to it, and
nothing asks whether the server still deploys it — that is answered
transitively, because a withdrawn form version is pruned by `FormStore` and its
pins go with it. Orphaned pins are swept first, or a 38,000-row list would stay
alive on the strength of a form nobody can open.

**Migration 0005 exists because of break 48**, found on the first run of the
paging test: `dataset_record.id` is a ULID, ULIDs generated in a loop are not in
insertion order, and paging by id delivered 37,852 villages in an order nobody
chose — stable, and scrambled. `ordinal` is the file's own order and doubles as
the cursor.

**Not yet done, and it is the honest half of part 4:** `StoredDatasetSource`
reads a whole version out of SQLCipher and filters in memory. §3.2's contract —
resolution proportional to the rows matching the selector — is *expressible*
through that interface and is not yet *met* by this implementation. An index on
the selector columns is a change to that one class, with the engine, the vectors
and every client untouched. Whether it has to happen is what the Pixel
measurement decides, which is part 5's.

### The acceptance, on the handset, through the screen

The earlier run drove the *engine* from a debug activity. This one is an
enumerator's thumb: `pm clear`, launch, New submission, and tap through.

```
  1/3  Mkoa *          Search ⁨26⁩ options    Mkoa wa Arusha, Mkoa wa Dar es Salaam, …
  2/3  Wilaya *        (7 options, no search — under the threshold)
       Wilaya ya Arusha DC, Wilaya ya Arusha Urban, …
  3/3  Kijiji *        Search ⁨227⁩ options   narrowed from 37,852
       typed "Nyamburi" -> Nyamburi Mpya, Nyamburi Kati, Nyamburi Kaskazini, …
       chose Nyamburi Kati -> button became "Finalize" (§6.2's gate)
```

Then Sync, and on the server:

```
  set       region_id    "TZ01"
  set       district_id  "D0001"
  set       village      "V000023"
  finalize

  resolved through the form version's pins:
    region_id    'TZ01'    -> Mkoa wa Arusha
    district_id  'D0001'   -> Wilaya ya Arusha DC
    village      'V000023' -> Nyamburi Kati
```

That last block is the whole item in four lines: a code collected on a phone,
and the name it meant, recovered months later from the exact list version the
form was published against.

**What the screen needed, and what it cost.** Two things, and the second was
found only by doing this:

- `CollectionViewModel` resolved choices through `FormInstance.choices` instead
  of reading `choices.items` — one line, and it is what let `dataset` join
  `choiceSources` in the collectable registry and removed eight errors from the
  UCL report
- **its `FormInstance` had no `DatasetSource` at all.** Every JVM test passed —
  they construct `QuestionUi` directly — and on the handset the region question
  rendered its label, its hint, and nothing else. `FormCatalog` now hands out
  the source the same way it hands out the form: `datasetSourceForSubmission`,
  bound to the submission, with no sibling that takes a version (break 30's
  rule, again, with a village list instead of a question list)

A long list is searched rather than scrolled, above 20 options. Not a round
number: a UCL district holds 227 villages and every other answer widget composes
its options eagerly in a `Column`, which is right for the twenty-option lists a
form is mostly made of and a visible pause at 227.

### The acceptance run, 2026-09-03

**The cascade works on a real phone against a real server.** Pixel 6 Pro over
Wi-Fi, a server on the LAN, the UCL biomass form's own three cascading questions
lifted verbatim from the import, and the generated village data.

```
  server: http://192.168.2.44:8001
  RESULT sync_wall_ms=33782ms
  RESULT sync_rx_mb=7.047776222229004MB
  RESULT dataset_rows_fetched=38044
  RESULT db_growth_mb=14.94921875MB
    forms held: ucl_cascade v1
    dataset ucl_regions  v1     26 rows complete=true indexed=[name]
    dataset ucl_districts v1   166 rows complete=true indexed=[name, region_id]
    dataset ucl_villages v1  37852 rows complete=true indexed=[district_id, name]
    regions offered: 26
    region TZ01 -> 7 districts
    a district -> 229 villages
  RESULT filter_median_ms=7.336ms
  RESULT chose_village_valid=1.0
  RESULT rejects_absent_village=1.0
```

26 regions narrow to 7 districts, a district narrows to 229 villages, an answer
taken from the list validates, and a village that is not in it is refused by
§6.3. Nothing was bundled: the form and all three lists arrived over the network
on a device that had been `pm clear`ed.

**What it is not.** This is the UCL form's *location group*, not the UCL form.
The whole form still does not publish, and after `atan` (done) the reasons are
`${...}` in six labels and a repeat inside a repeat — neither of which is
dataset work. The acceptance docs/project-conventions.md states is not met and item 4 is not done.

### Part 5 — the delta, and what a Pixel says it costs

`GET /datasets/versions/{held}/delta?formVersionId=…&datasetKey=…` returns the
changes between the version a device holds and the one its form was published
against. Two stages, and the second is the one that earns its keep: the row hash
answers "did anything about this row change", and the **projection onto the
columns that form version actually reads** decides whether anything travels. A
row whose only edit is to a column nothing reads does not move.

Deletions are explicit. Inferring them from absence needs the whole set present
to compare against, which is what a delta exists to avoid sending.

**A mismatch is a 409 and never a full transfer.** A device asking to come from
a version this server never published, or for a list its form was not published
against, is a device whose state nobody understands — and re-sending the list
would leave it correct and the disagreement invisible. `DeltaRefused` is that
rule; the sync client does not fall back from it either.

#### The measurements, and the one that changed the design

Pixel 6 Pro, 38,000 villages, through SQLCipher, driving the real engine.
`scripts/measure_datasets_on_device.sh` reproduces it; §3.2 has the table.

The first cut read a version and filtered it in memory. **The first keystroke on
the village question cost 1,589 ms.** That is not a slow feature, it is an
unusable one, and it is exactly what §12 flagged as open since v0.1.

Indexing the columns fixed it — 45 ms — and then broke something else. Indexing
*every* column made 304,000 entries and took the **second-sync delta from 137 ms
to 14.4 seconds**, because applying a delta copies the index to the new version.
The weekly delta is the number that decides field usability, so that was worse
than what it fixed. Break 52.

Indexing only the columns a filter narrows on — named by the server, which is
what reads the IR — is where it landed:

| | before | after |
|---|---|---|
| First keystroke | 1,589 ms | **45 ms** |
| Keystroke median / p95 | 17.4 / 56.4 ms | **9.8 / 32.3 ms** |
| Heap | 46.3 MB | **11.6 MB** |
| First sync (38,000 rows) | 1.1 s | 3.2 s |
| Storage | 8.4 MB | 11.3 MB |
| Second sync (200 changed) | 137 ms | 2.7 s |

The cost moved to write time, which is where it can be afforded. **Per-keystroke
filtering over 38,000 villages is viable**, and it was not before this was
measured — 7.3 ms median on the device, against 1,589 ms for the first
keystroke before the index existed.

Those are bench figures. The device against a server says the same thing about
filtering and something worse about everything else: the delta transfers 66 kB
instead of 7.05 MB (a 109x saving, exactly what it was for) and then spends **56
seconds** applying it, and filtering degrades to 77 ms once a second version is
held. Both are recorded in `docs/known-defects.md` 9 and 10, both are open, and
both are downstream of nothing retiring a form deployment (defect 4). The
acceptance run above is what produced them.

Two more things the device found and a laptop could not. `datasets.sq` added
three tables with no `.sqm`, so every fresh-database test passed and the phone —
which had the app installed — could not upgrade into it (break 51). And once
`filter_columns` became selective, a lookup on an unindexed column returned *no
rows* rather than falling back, which is an empty village list on a device
holding every village (break 53).

**Decision — the delta mechanism.** Per-row content hashes, delivered as a
diff against the version the device holds.

- `dataset_record.row_hash` is SHA-256 over `canonical_json(data)` — the
  encryption envelope's serialisation (§5.1), reused rather than reinvented,
  because two servers must produce identical bytes or every delta is spurious.
- **Two stages, and this is the part worth not undoing.** The row hash covers
  the *whole* row and answers "did anything change". It is **not** what decides
  whether a device is sent anything: a dataset carries columns no form
  references, and an edit to one must not cost a 50k-row list a transfer over a
  field connection. Stage two compares the **projection** onto the columns that
  device's forms actually reference.
- **Tombstones are explicit.** A deleted village arrives as a key in a
  `deleted` list. Inferring deletion from absence needs the whole set present
  to compare against, which is the thing being avoided. The form manifest can
  be a complete statement because it is 300 bytes; a 50k-row dataset cannot.
- Diffs are **per version pair, `from → to`**, computed server-side and
  cacheable. A device on v3 asking for v7 gets one diff, not four.
- A device holding nothing gets a **full transfer, resumably**, paged with a
  cursor. First sync is the hardest case and cannot be one response.

**Decision — version binding, made unexpressible.** A form version is pinned to
dataset *versions* at publish, in `form_version_dataset`, because the IR names
a dataset by **key** (`"dataset": "districts"`, §3) and a key is not a version.
Resolving at read time would let a draft opened against form v1 see whatever
`districts` is newest — the same mistake as validating a v1 answer against v2's
choice list.

The resolver is `dataset_rows_for(submission_id, dataset_key)`, on both client
and server, with **no version parameter**, following
`FormCatalog.compiledFormForSubmission` (break 30) and
`forms.service.compiled_form_for_submission` (break 40). Retention follows:
a device keeps a dataset version while any form version it holds references it.

**Decision — size on the Pixel, measured before the item is called done:**

- import time for 50k rows into `dataset_record`
- first-sync bytes and wall clock over Wi-Fi
- SQLCipher file growth on device
- **second-sync delta** — a device on v3 receiving v4 with ~200 changed rows.
  This is the number that decides field usability: first sync is a one-off at
  enrolment, the delta path is what happens every week for the life of the
  project
- **filter latency per keystroke** at district → village, which is what §12
  flags as the open performance contract

If per-keystroke filtering is not viable on 2GB RAM, the honest outcome is a
stated limit in §12, not a slow form.

**Item 5 (the mistake that passes every test) — a stale dataset.** The device
holds v1, the server has v2, the sync silently no-ops, and an enumerator picks
from a village list that no longer matches. A diff mechanism makes this *more*
likely, not less: "no changes" and "I failed to ask" look identical.

The guard: the device states the `dataset_version_id` it holds and the server
states the one it expects. **A mismatch refuses loudly and says so — it does
not silently send a full transfer.** A silent 50k-row re-send over a field
connection is its own failure, and the mismatch means something is wrong that a
re-send papers over. Same shape as `WirePullResponse.forms` being nullable:
silence and "nothing deployed" must not collapse into one answer (break 28).

**Acceptance:** the UCL biomass form imports cleanly, deploys, and its
cascading region → district → village selects work on the Pixel. Its five CSVs
do not exist — XLSForm companion files ship beside the workbook and none is in
any corpus — so they are generated **adversarially**: real Tanzanian scale
(~25 regions, ~180 districts, tens of thousands of villages), Swahili
diacritics, names repeating across parents, embedded commas and quotes, blank
and whitespace-only cells, more columns than the form uses, and keys differing
only by case or surrounding whitespace (§3.1). Documented as synthetic in
`PROVENANCE.md`, and the report must say the acceptance proved the pipeline
works with data *shaped like* the real thing — not with UCL's actual files.

### Item 5 — export

**Nothing leaves this system yet.** A customer can author a form, deliver it,
collect on a handset and sync — and then has no way to get the data out. That
blocks everyone, which is why it comes before nested repeats (one form in
twenty-one, and it is UCL).

**Order: CSV and XLSX first**, because every customer needs those and nothing
else is usable without them. Stata `.dta` and SPSS `.sav` after;
`pyreadstat` writes both.

**Wide and long, both.** A household roster is unreadable in wide form past a
few members — `member_1_name` … `member_30_name`, mostly empty — and long form
is what anybody actually analyses. Wide is what people expect and ask for.

**Encrypted values export as a literal `ENCRYPTED` token.** Never blank, never
`NA`, never `NULL`: every statistical tool treats those three as missing and
will compute a mean over the rows that happen to be readable, silently. A token
is a value that no analysis can mistake for an absence.

> Check what the `.dta` and `.sav` writers do with a string in a numeric
> column before trusting this. If either coerces it to missing, that column is
> written as a **string** column instead — the type is worth less than the
> distinction between "encrypted" and "not answered".

**A manifest ships with every export**, naming per column: the field path, why
it is unreadable, and which project key ids can open it. An export that is
partly encrypted and does not say so is worse than one that fails.

**A dataset-backed value exports the code *and* the resolved label**, through
the form version's pins (§3.2) — exactly what the acceptance showed on the
server: `V000023` beside `Nyamburi Kati`. A CSV of `V000023` with no name in it
is not something anybody can analyse, and resolving the code any other way than
through the pin would give it last month's name.

#### The mistake that passes every test

Two, and the second is the one I would bet on.

**A repeat flattened onto the wrong parent.** The column names are right, the
row count is right, and household A's members are filed under household B.
Nothing about the file looks wrong and every conclusion drawn from it is wrong.

The sharp edge is specific to this IR and easy to miss: §2.3 says positional
addressing *resolves against the current ordered list*, and deleting an instance
removes it from that order without renumbering storage. So `members[1]` is not
a person — it is a position, and it means a different person before and after a
deletion. **A long-form export keyed on position is therefore not stable across
time**: yesterday's export and today's disagree about who is who, and a join
between them is silently wrong. The key must be the submission id plus the
**stable instance id**, which is what the op log already carries.

**A non-relevant field's retained value, exported.** §4.4 is explicit — a
non-relevant field *retains* its value and export *excludes* it — and the two
halves exist for different reasons: the op log must not lose an answer somebody
gave, and an analysis must not contain answers to questions nobody was asked.
An exporter that reads `FormInstance.values` rather than `answers()` produces a
column where a household that said "no children" reports the three it had typed
before changing its mind. Every count is right, every type is right, every test
passes.

This is the one I would bet on because it is the *default* mistake: `values` is
the obvious thing to reach for, `answers()` is the one that is correct, and
nothing about the wrong choice looks wrong. The engine already draws the
distinction — the exporter must be unable to reach past it, the same way
`compiledFormForSubmission` and `dataset_rows_for` are unable to name a version.

Two invariants worth building the suite around, because neither is a test of a
case somebody thought of:

- **Round trip.** Export, re-import, compare against the source submission.
- **Cross-form agreement.** Every long-form row's parent key exists exactly
  once in the wide export, and the multiset of (submission, instance) pairs
  matches the op log's. A flattening error breaks this and a wrong column does
  not.

#### What landed: CSV and XLSX, both shapes

`backend/app/modules/export/`, `scripts/export_submissions.py`. Both invariants
above are the suite (`test_export.py`), and both were watched to fail — breaks
58–61.

**Both predicted mistakes are made unexpressible rather than tested for.**

- **`FormInstance.values` is unreachable from the export path.**
  `form_engine/projection.py` is the only door: it builds the instance, reads
  `answers()`, and returns a frozen `ExportProjection` whose repeat cells are
  called `cells` — there is no attribute named `values` anywhere downstream to
  reach for. `test_export_reads_only_answers.py` is the lint on the door and it
  closes all three ways back through it: naming `values`/`states`/`snapshot`,
  constructing a `FormInstance` outside the door, and
  `answers(include_irrelevant=True)`, which is `values` spelled differently and
  the one that would not look wrong in review. The lint checks its own
  instrument first, per the note at the foot of `known-breaks.md`.
- **A repeat row is keyed on `(submission_id, instance_id)`.** The stable id was
  already in the op log; nothing had to be invented. `instance_index` is in the
  file too and its manifest entry says to sort by it and never join on it.

Four more decisions worth not re-making:

- **The fold moved.** `submissions/fold.py` is now the one implementation and
  `sync.service` calls it. Export needs two things `submission_state` cannot
  give it: which paths are ciphertext (it drops them, correctly, because a value
  the server cannot read has no place in a queryable fold) and the **order**
  repeat instances were created in — `data` is JSONB, and JSONB does not
  preserve key order, so the order a roster is displayed and exported in does
  not survive a round trip through it. Export therefore reads the op log in
  `(counter, device_id)` order, which is where that order actually lives.
- **`ENCRYPTED` propagates through `calculate`.** A total over three encrypted
  incomes evaluates to 0, and 0 in a CSV is a number rather than a gap anybody
  can see. Break 60. The manifest distinguishes `encrypted` from
  `computed_from_encrypted`, which is what answers "why is this total a word".
  A field whose *relevance* read an unreadable value is kept — §4.4 coerces null
  to true, the safe direction — and flagged `relevanceUncertain`, because
  "included" is then a guess and the file should not imply otherwise.
- **Wide and long are the parent/child split, not two renderings.** Long is the
  default: a parent table of one row per submission with `<repeat>_count`
  columns, plus one table per repeat. Wide is the single flattened table people
  ask for, its repeat columns are positional by construction, and its manifest
  says so on its face — and `read_bundle` **refuses** a wide bundle rather than
  inventing instance ids for positional rows, which would let the round trip
  pass over a file that has genuinely lost which member is which.
- **One export spans every version its submissions sit on.** Columns are the
  union in document order, oldest version first; each column records the
  versions defining it and every parent row carries `form_version`. Each
  submission is projected through `compiled_forms_for_submissions` and its codes
  named through `dataset_rows_for_submissions` — the **batched** forms of the two
  functions that take no version parameter, batched in how the question is asked
  and never in what is asked. Break 61 is the proof: with the village list
  republished under a rename, resolving through the newest pin gives a v1
  submission a name that did not exist when it was collected.

Two format decisions and their reasons: a structured value decomposes into one
column per component (`dwelling_lat`, `photo_filename`) rather than a packed
string every analyst has to split first, and CSV is written UTF-8 **with a BOM**
because without one Excel reads it as the system code page and a product that is
RTL and Swahili from the start cannot ship an export that is mojibake on a
double-click.

#### What an export costs, measured across three form versions

`scripts/measure_export.py` reproduces this. The shape measured is the one that
actually happens rather than the big one: a project six months in has v1, v2 and
v3 of its form in a single export, **each pinned to its own dataset version**
(§3.2), so one run resolves codes through three separate village lists. Nothing
had exercised that, and it is strictly more work than one version at scale.

Apple Silicon, Postgres 16 in Docker. Three form versions; three dataset
versions each of 37,852 villages, 166 districts and 26 regions; three stems per
submission. `py` is `tracemalloc` (Python allocations); `rss` is the process
high-water mark, one format per process.

**At 5,000 submissions — the current `DEFAULT_LIMIT`:**

| | build | py peak | rss | files |
|---|---|---|---|---|
| csv | 6.8 s | 162 MB | 530 MB | 1.08 + 0.53 MB |
| xlsx | 13.8 s | 162 MB | 551 MB | 0.81 MB |
| dta | 7.9 s | 162 MB | 555 MB | 1.22 + 0.60 MB |
| sav | 8.0 s | 162 MB | 558 MB | 1.56 + 0.84 MB |

**Three findings, and the third decides what to do about it.**

**Label resolution is cached per dataset version, not per row.** Three row
fetches for the whole export whatever the submission count — one per dataset
key, not one per submission and emphatically not one per cell — and per-cell
resolution is an O(1) dict hit. The counter in the script measures this rather
than trusting the source, because the source is what you would be checking. A
naive implementation doing one lookup per cell is the difference between seconds
and hours, and it is not what this does. Identical dataset content across form
versions also dedupes at publish, so three form versions pin **one** region list
and one district list, and only the villages are held three times.

**Multi-version costs little and works.** 27 columns as the union of the three
versions, each submission read through its own pins. The rows-per-lookup ratio
falling as submissions rise — 16.3 at 120, 7.2 at 5,000, 3.0 at 12,000 — is just
the fixed cache amortising over more cells.

**Time is fine. Memory is the limit, and it is per-submission, not
per-dataset.** That distinction is the whole finding, because streaming and
caching are different fixes and only one of them is called for:

| submissions | villages | py peak | rss |
|---|---|---|---|
| 1,000 | 37,852 | 143 MB | 522 MB |
| 3,000 | 500 | 127 MB | 350 MB |
| 3,000 | 37,852 | 155 MB | — |
| 5,000 | 37,852 | 162 MB | 530 MB |
| 12,000 | **500** | **506 MB** | — |
| 12,000 | **37,852** | **506 MB** | **1,083 MB** |

The last two rows are the measurement that settles it: **a 75x larger dataset
changes peak memory by nothing at all.** The dataset sets a floor of roughly
130–150 MB which submissions overtake somewhere around 4,000–5,000 — which is
where `DEFAULT_LIMIT` happens to sit — and above that it grows about 40 KB per
submission. At 12,000 submissions one export request peaks over a **gigabyte**.

The cause is that `export_form` holds everything at once: every op as an ORM
object, every fold, every projection, every table row, and then the writer's own
copy on top. The writers are not where it goes — csv and sav differ by 28 MB,
and xlsx costs twice the *time* of the others and no more memory. So the fix is
**streaming**, and caching would buy nothing because the caching is already
right. That is not done, and `docs/known-defects.md` 13 is the honest record of
it rather than a blind optimisation.

**The limit stays at 5,000, and it is now a measured number rather than a
guess** — about 530 MB for one request, which a 2 GB self-hosted box survives
and two concurrent requests would not. The HTTP route caps at it
(`Query(le=DEFAULT_LIMIT)`); the CLI's `--limit` deliberately does not, because a
CLI run is one at a time and an operator knows how much memory their machine
has. That asymmetry existed before this measurement and is what justifies it now.

#### The route, and the one exemption it needed

`GET /api/v1/exports/{formId}` — `format`, `shape`, `language`, `status`,
`projectId`, `environmentId`, `limit`. Always a zip, even for a form with no
repeats: a bundle is several files and one shape is better than a branch on how
many repeats a form happens to have.

A zip is the **only** non-JSON 2xx body in this API, and
`test_every_success_response_names_a_schema` requires a `$ref` under
`application/json` for every success response — rightly, because a route whose
body FastAPI has to infer publishes an object with no fields. So the exemption
is written exactly as the request side's `application/octet-stream` one is:
**one media type, declared binary, or it fails.** The media type is named rather
than "anything not JSON", so the next binary response is a decision somebody
makes. Break 66 widens it three ways, including the control — a JSON route that
drops its `response_model` still fails, which is the half that matters.

Two things about it worth not rediscovering:

- **The route declares the base `Response`, not `ZipResponse`.** FastAPI
  documents every `responses` entry under the route class's media type, so
  naming `ZipResponse` publishes the 404 and the 413 as `application/zip` —
  bodies this server has never sent, which is break 13 by another road. With no
  media type on the class the 200 is only what the route declares and the
  refusals fall back to JSON, which is what they are.
- **413, not 422.** 422 belongs to the framework and means the request did not
  match the schema; this request matched it and asked for too much. The body is
  the `{"detail": {found, limit, message}}` envelope — declared as the envelope,
  and asserted against a real request as well as against the document, because
  only one of those two can tell you what the server sends. **409** is the other
  refusal: this form's data will not fit the format asked for, which in practice
  means an answer over SPSS's 32,767-byte maximum.

#### Stata and SPSS, and what the formats decide for you

`export/statistical.py`. The question docs/project-conventions.md flagged was asked **first**, as a
probe, before any of it was written — `backend/tests/test_statistical_writers.py`
is that probe kept, asserting library behaviour rather than ours so that a
pyreadstat upgrade which moves one of these answers fails a build instead of
changing what our files mean.

**What the writers actually do**, measured:

- **The token is not coerced to missing.** It survives — by pyreadstat
  **silently retyping the whole column** to string, so `100.0` becomes
  `"100.0"`. The danger is therefore not lost data, it is a column whose type
  depends on whether anything in *this* export happened to be unreadable.
- **A declared pandas dtype does not override that.** readstat types a column
  from its values; there is no way to *ask* for numeric, only to write it and
  look.
- **readstat enforces SPSS's 64-character name limit and not Stata's 32**, so it
  will happily write a `.dta` that Stata itself refuses. Same for variable
  labels: SPSS truncates at 256, Stata's own 80 is not enforced at all.
- **A value label keyed by a string code is written against `0`** in a `.dta` —
  `V000023` labelled `Nyamburi Kati` comes back as `0` labelled `Nyamburi Kati`.

So, in order, the decisions those forced:

- **The exporter decides the type and then verifies it.** Storage type comes
  from the plan; every file is read back after writing and a column that did not
  come back as declared is a `TypeChanged` exception, not a surprise six months
  later. That check earned itself on its first run (break 64): an all-null
  `date` column was coming back as **string**, so an unanswered date question
  gave the same form two schemas. A value that will not fit its column is
  refused at write time too, for the same reason — writing it as missing would
  keep the type tidy and delete an answer.
- **The type change is stated, because it cannot be avoided.** A numeric column
  cannot hold `ENCRYPTED` and writing it as missing is the failure the token
  exists to prevent, so the column becomes text — and the manifest records
  `storageType`, `declaredStorageType` and `storageChangedBecause` per column,
  the notes say the same in a sentence, and the CLI prints it. The instability
  is real: the same form exports numeric one week and text the next. It is
  visible rather than silent, which is the whole of what can be done about it.
- **Names are shortened by us, deterministically, and never merged.** Target is
  `^[A-Za-z][A-Za-z0-9_]*$` at 32 characters — Stata's limit, the tighter of the
  two, so one name works in both files. Collisions replace the tail rather than
  appending, serials are assigned in **plan order** (a function of the form
  versions alone, so a do-file written last month finds the same columns), and
  every shortened name is in the manifest as `storedAs` beside the CSV name.
  Break 63: two 37-character ids differing at character 36 truncate to the same
  32, which would be one column holding two questions' answers.
- **Variable labels carry the question text**, truncated to Stata's 80 and
  qualified — `Dwelling location (lat)`, `Consent given (label)` — because four
  columns of one geopoint all reading `Dwelling location` in `describe` looks
  like four answers to one question rather than one answer in four parts.
- **No value labels.** Our choice codes are strings by design (§3.1: the key is
  the cell's value, exactly) and a `.dta` silently attaches a string-keyed label
  to `0`. The resolved name goes in its own column, exactly as in the CSV.
- **A `date` is stored natively; a `datetime` is not.** Neither format stores a
  UTC offset, so a native datetime means dropping `+03:00` or shifting the
  value, and both change when the interview happened. A date has no offset to
  lose, and a Stata user handed a string date has to parse it before they can do
  anything. `time`, `datetime` and the started/finalized/received stamps are ISO
  text.
- **Each format's longest string is decided here, in bytes.** Measured rather
  than assumed, by reading the file instead of asking the library: over 2,045
  bytes a `.dta` writes a Stata **`strL`** — the type code in
  `<variable_types>` is `32768` — which holds 2 GB, so a long answer is not a
  problem there and needs no limit of ours. A `.sav` is the opposite: readstat
  wrote 40,000 bytes past SPSS's documented 32,767-byte maximum without a word,
  the same shape as its writing a `.dta` name Stata refuses. So that one is
  enforced and **refused**, never truncated and never written out of spec, with
  the refusal naming the formats that do hold it. Breaks 68 and 69. In **bytes**
  and not characters, because 20,000 Arabic characters are 40,000 of them and
  this product meets that case first — `docs/known-defects.md`'s withdrawn entry
  12 records the wrong version of this and why it was wrong.

**The third question — the mistake that passes every test — and its answer.**
The guess was right: a type that round-trips through CSV and not through `.dta`.
It was not hypothetical. `parse`'s boolean branch read `str(cell) not in ("0",
…)`; a CSV hands back the text `0` and a `.dta` hands back the float `0.0`, and
`str(0.0)` is not `"0"`. **Every "no" in a boolean question became a "yes"**, in
two of the four formats, with nothing on the face of the file to see. Break 65,
found rather than injected — by extending the round trip to run against all four
writers, which is the only thing that could have. A round-trip invariant is
worth exactly as much as the formats it runs against.

The second such mistake is one no single-export test can see at all, because it
exists only *between* two exports: the column type that follows the data. That
is why `test_a_columns_type_changes_with_the_data_and_the_manifest_says_so`
exports the same form twice and asserts the difference **and** that both
manifests state it.

**Not done, and named rather than implied:**

- **No per-option indicator columns for `select_multiple`.** Codes are
  space-joined (the XLSForm convention) and labels joined by ` | `. A
  `crops_maize` / `crops_beans` set of 0/1 columns is what some analyses want
  and is additive.
- **No export of media files themselves.** A photograph exports as its
  filename, id, hash and size; the bytes stay in object storage.

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
