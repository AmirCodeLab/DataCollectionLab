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

**O-1 is closed.** First market: **survey and research agencies**, with RCons
as the pilot customer — decided 4 September 2026 by which existing relationship
signed first, not by market size. Self-hosting, data residency and SSO move
back; assignment, supervision and review move forward, which is what Phase 3 is.
`docs/DCP-Product-and-System-Architecture-v1.0.md` §2.3.

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

11. **Nothing that must never be published may enter a commit.** As of
    2026-09-04 `main` is protected by a ruleset requiring a pull request, so
    every change reaches it through one — and GitHub freezes
    `refs/pull/<n>/head` at the commits the PR opened with. No force-push, no
    `git filter-repo`, no history rewrite reaches those refs. They stay
    fetchable by anyone, forever, including the commits a rewrite was meant to
    erase.

    This is not hypothetical. The previous repository was abandoned and rebuilt
    from a clean history on 2026-09-04 for exactly this reason: four merged pull
    requests held pre-rewrite commits — attribution trailers and a home
    directory path — permanently reachable, and nothing could remove them. The
    rebuild bought a repository with zero pull refs. Requiring pull requests
    spends that, deliberately, in exchange for a default branch that cannot go
    red unnoticed; two merges had just landed on a red `main`, which is the
    failure a bypass would have made permanent.

    The consequence is a working rule, not a preference. **The check happens
    before `git commit`, not before `git push`.** A secret, a signing key, a
    home directory path, a real customer or network name, a device id, a
    respondent's data: once committed on a branch that becomes a pull request,
    it is published and it cannot be withdrawn. "We can strip that later" is no
    longer true of this repository.

    Two things follow. `.gitignore` is not this check — it only covers what
    somebody already thought of, and everything caught by the public-readiness
    audit was in a *tracked* file. And when something does turn out to be
    committed, treat it as published: rotate the key, accept the disclosure,
    tell whoever it concerns. Do not plan a rewrite; there is no longer one that
    works.

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
| That a repeat's instance list stays in creation order — which is what makes §2.3's "shrinking discards the trailing instances" true | `test_instance_order_invariant.py` (`backend`), `InstanceOrderTest` (`:shared:form-engine:jvmTest`) | 77 |
| That the ordering guard above can still read an id at all — the minter and the assertion agreeing is what stops it going dark | the same two files, one test each | 78 |
| That every question in an imported form can actually be put on a screen — a repeat's cannot, and the form used to publish anyway | `test_xlsform_template.py` (`backend`) | 79 |
| That the "N of M" an enumerator reads counts only screens somebody can answer | `NavigatorTest` (`:shared:form-engine:jvmTest`) — the vectors pin the plan, this pins the displayed pair | 80 |

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

### A spec sentence that names two operations needs two vectors

The boundary above is structural: those things are invisible to a vector however
many you write. This one is the opposite, and worth keeping separate for that
reason — **it is perfectly visible to a vector, and the vector was not written.**

> **When a sentence in the spec names two operations, or two bounds, or a rule
> and its inverse, each half needs its own vector. One half passing is not
> evidence about the other. Prose reads symmetric far more easily than code
> behaves symmetrically.**

Three breaks on 2026-09-04, all against Form IR §2.3, all the same shape:

- **74.** "bounded by `minInstances` / `maxInstances`" — the ceiling was
  enforced on the add and the floor was enforced nowhere, so a roster declaring
  `minInstances: 1` could be emptied. Neither bound had a vector at all.
- **75.** "the user cannot add or remove instances" — the add refused and the
  delete did not. And the delete was the dangerous half: `recalculate()` restores
  the *count* by appending a fresh instance, so the answers were destroyed, the
  stable id changed, and every count on every screen still read correctly.
- **76.** "shrinking discards the **trailing** instances" — the engine is right,
  but `repeat-006` claimed to cover it and could not see it. It answered two of
  three instances and asserted a count plus the first survivor, both of which
  hold when the *middle* instance is discarded instead.

74 and 75 are one operation of a pair going unimplemented. 76 is one half of a
pair going unasserted while the vector's title says otherwise, which is worse,
because it reads as covered. All three were found by reading §2.3 against the
code rather than by any test.

**The tell is the conjunction.** `and`, `or`, `/`, "cannot X or Y", "X creates
and Y discards" — a sentence joining two operations is one an engine can
implement half of and look finished, and a vector can assert half of and look
thorough. When you meet one, write down both halves before writing either
vector, and make the second one's failure message name which half it is.

## Commands

```bash
# Backend — the lockfile is what CI installs, so develop against it
cd backend && pip install -r requirements.lock && pip install -e . --no-deps
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

**The Python toolchain is pinned in two files, and both are load-bearing.**
`.python-version` is the interpreter — every `setup-python` in the workflow
reads it rather than repeating a literal — and `backend/requirements.lock` is
the resolved dependency set, installed with `pip install -e backend --no-deps`
on top so the lock stays authoritative. `pip check` then fails if the lock no
longer satisfies what `pyproject.toml` declares, which is what stops the two
from drifting apart.

The pin exists because of the contract check. `specs/openapi.json` is compared
byte for byte, every dependency in `pyproject.toml` is a `>=` floor, and the
interpreter matters too: CPython renamed 413's reason phrase in 3.13, so the
same app generated a different document on 3.14 than CI checked on 3.12 (break
72). An unpinned toolchain makes that check fail on a morning nobody touched
the API — and a gate that goes red at random stops being read, which is the
failure mode this whole file is written against. Regenerate the lock on Linux
and the pinned interpreter, not on a laptop; the header in the file says how.

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
**Phase 2 part 1 — the collection chain, end to end: complete.** A form
authored elsewhere, imported, deployed, delivered to a handset that had never
held it, collected offline, synced encrypted and exported in four formats. The
write-up — items 0–5, the hardware runs, the measurements and the decisions
worth not re-making — is `docs/phase2-record.md`. Source comments and tests
that cite this file for "item 4", "item 5" or "Plainly NOT done yet" mean that
one: the text moved, unchanged, and the section names did not.

**Phase 3 — the RCons pilot: in progress.** Scope agreed 4 September 2026 and
re-ordered the same day: `docs/phase3-pilot-scope.md`, resting on
`docs/rcons-current-system.md`. Read those before starting an item — what is
below is the order and the reason for it, not the scope.

The collection chain is necessary and not sufficient: the platform knows a
device but not a person. Phase 3 closes that. Seven items, in this order:

0. **The visual form builder.** RCons authors their own forms in the dashboard,
   and **nothing else starts without it** — until they can, we are in the loop
   for every change to every questionnaire. Three decisions are already made and
   are binding: it produces Form IR and holds no form logic; **preview runs the
   same engine the handset runs**; the relevance editor is visual **with** a code
   escape hatch. Publishing goes through the **same** path an import does, not a
   second route into `form_version`. Scope doc §2 for why each
1. **Login and permissions.** Everything below depends on it. A user belongs to
   the organization, not to a project; a role is a set of permissions plus a
   scope, never a hard-coded branch, and every console screen checks a permission
2. **Sample assignment and supervisor isolation.** Isolation is visibility, not
   only assignment — which is why scope is part of the role rather than a filter
   applied in the UI. A filter can be forgotten in one query; a scope cannot
3. **Repeat screen flow**, and the roster it unblocks. The engine already manages
   instances; what is missing is a screen to put a roster on, because Form IR
   §11.1 excludes repeats from the screen plan and defers their flow to v0.2. A
   spec decision first, then the planner on both engines, then the UI
4. **Separate sync for sample and form.** A 37,000-row sample over a village
   connection is a different proposition from a small form update, and the person
   holding the handset should decide which they are doing
5. **Supervisor monitoring**, within scope only
6. **Review and correction.** Reviewing what is flagged rather than everything is
   the differentiator, and it is a project setting

**The skip-to prototype was item 0 and is now optional** (scope doc §12): RCons's
tool can emit XLSForm once given a template, and their existing surveys are
finished. Giving them that template is a real dependency of item 0.

**There is no timeline, deliberately** — the pilot happens when the platform is
ready, not on a date. The "roughly two months" this section used to carry
predated both item 0 and the item 3 correction, and survived them by looking
like a fact. Scope doc §11.

**Not in this phase**, named so the absence is a decision: desktop data entry
(the phase after this one — see `docs/known-defects.md` 1 and 2), the `Person
Id` / `Structure Map` / `Custom` selection types, entity relationships and
longitudinal linking, nested repeats (IR v0.2), the workflow engine beyond
review, and text/audio audits. Reasons are in `docs/phase3-pilot-scope.md` §9.
