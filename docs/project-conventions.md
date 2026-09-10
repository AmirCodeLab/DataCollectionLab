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

**O-3 is closed.** Web forms runtime: **the Kotlin engine compiled to Wasm**,
rendered by React — decided 6 September 2026 on a spike and not a preference.
~128 KB brotli, 14.7 ms to instantiate, 8.0 ms to parse, compile and fully
recalculate a 1,000-question form, and all 113 vector forms compiling on the
target with a CI job that runs them. `docs/wasm-spike.md`, and
`docs/DCP-Product-and-System-Architecture-v1.0.md` §18.4.

It is written down because it was being decided sideways: item 0's browser
preview needs the engine the handset runs, and shipping the engine to a browser
for preview is the same shipping this decision is about. **One implementation
of form behaviour, everywhere** — not a second one for the web.

- **O-2** Server-side form evaluation: JVM engine sidecar vs Python port. Not closed by item 0's preview, which settled the console's engine (Wasm, no route to `/forms/evaluate`) and nothing about the server's — the Python reference is still production for `/forms/evaluate` and the publish gate
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

12. **Work that exists only in a terminal does not exist.** Any substantial
    finding — an analysis, a measurement, a probe result — is written to a file
    as soon as it is complete, before the session that produced it can end. It
    does not have to be committed to be safe; it has to be on disk.

    Like rule 11, **the check is at the point of creation, not the point of
    loss.** By the time work is missing there is nothing left to decide. The
    two rules are not in tension and they meet precisely: disk is what makes
    work safe, a commit is what makes it published, and rule 11 is the reason
    the answer to losing something is never "commit it faster".

    Three times, in three different ways, and none of them looked like a risk
    at the time:

    - **The pre-rewrite backup in `/private/tmp`.** Held outside the repository
      during the 2026-09-04 rebuild, in a directory the operating system is
      entitled to clear.
    - **Seven conformance vectors the generator deleted** — `repeat-009..012`
      and `screens-009..011`, hand-written straight to JSON, removed by any run
      of `generate_vectors.py` because `main()` cleared the directory before
      writing. Every suite stayed green: the runners glob, so a vector that
      stops existing is not a failure, it is simply not run. Break 82.
    - **An analysis that lived only in terminal output** — the Phase 3 item 0
      builder scope, the longest piece of reasoning produced for this
      repository, gone when the session holding it was cleared on 2026-09-06.
      Part of it was recovered from what had been pasted back into the
      conversation; the rest was rewritten from scratch, and
      `docs/phase3-item0-builder-scope.md` marks which sections are which,
      because recovered text and text written afterwards are not worth the
      same and must not read as though they were.

    The shape is the same each time and it is the shape this file keeps
    recording: **absence does not announce itself.** A deleted vector looks
    like a smaller suite, a cleared temporary directory looks like an empty
    directory, and an analysis nobody saved looks exactly like an analysis
    nobody did. Nothing goes red. That is why the rule is a habit at the moment
    of finishing a piece of work rather than a check somewhere later — there is
    no later that can catch it.

    Cheap, and therefore not worth arguing about in the moment: the scratchpad
    is a file write away, `docs/` is a file write away, and neither costs a
    review or a branch. A finding written down and thrown away later has cost
    nothing. A finding not written down is the only one that cannot be
    recovered.

13. **A step meant to check state must not contain a command that changes
    it.** A diagnostic that mutates is not a diagnostic. The shape to refuse is
    a listing pipeline with a mutating command inside it — `git branch -d` in
    a loop written to *show* which branches are merged, a `rm` in a script
    written to *count* files, an `UPDATE` in a query written to *see* a row.
    Check first, in a command that can only read; act second, in a command
    that only acts; never both in one.

    It happened on 2026-09-07, during the branch cleanup after PRs #33 and
    #34. The first pass refused two merged branches (`git branch -d` compares
    against a gone upstream and says "not fully merged"), and the rule for a
    refusal is to stop. The next step was meant to *explain* the refusal —
    show the message, count the commits not on `main` — and was written with
    `-d` as its first line. It deleted both branches. Both were at zero
    commits ahead of `main`, so nothing was lost, which is exactly why this is
    written down now: the next time the check says "not fully merged" it may
    be telling the truth, and a check that deletes what it is checking would
    have destroyed the evidence along with the work.

    The tell is grammatical. A step described as "show", "list", "count",
    "confirm" or "see why" must be built only from commands that read. If a
    mutating command is in it, the description is wrong or the command is,
    and either way the step is not run until they agree. Rule 12's cousin:
    that one is about work that vanishes because nobody wrote it down; this
    one is about work that vanishes because the person looking at it was
    holding the wrong tool.

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
| That the cursor re-reads its position after the instance list changes, and refuses an instance id that does not exist | `NavigatorTest` (`:shared:form-engine:jvmTest`) — §11.3's rules are pure functions the vectors reach; *calling* them from the cursor is not | 89 |
| That two engines agree about which forms compile, for every §10.2 error except the sensitivity leak | `test_repeat_in_field_list.py` (`backend`) and `ScreensRepeatTest` (`:shared:form-engine:jvmTest`) — a matched pair, and nothing else. See below | — |
| That both engines refuse the same four `rowSource` shapes, and that the one refusal meant to be **deleted** says so in its message | `test_row_source_refusals.py` (`backend`) and `RowSourceRefusalTest` (`:shared:form-engine:jvmTest`) — the second matched pair, same exposure. §2.3's `kind: "dataset"` is valid and unbuildable, not wrong | — |

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

### A guard that enumerates what exists cannot see what stopped existing

**The fourth blind spot, and the one that was found the hard way.** On
2026-09-05 seven conformance vectors were destroyed in a single command —
`repeat-009`…`repeat-012` and `screens-009`…`screens-011`, which was the whole
of the previous day's output and the evidence behind breaks 74 to 81. **Every
gate stayed green.** `conformance/generate_vectors.py` cleared the directory
before writing and those seven were hand-written straight to JSON rather than
added to it; `pytest tests/test_conformance.py` reported 96 passed, and every
other check passed too.

The reason is not that a check was missing. It is that **every check we have
asks whether what exists is in order, and a deleted thing does not exist.**

```
check_ci_runs_every_suite.py    "is every suite on disk run by CI?"
                                "was every vector on disk executed?"
check_every_directory_is_gated  "is every directory holding source read by a gate?"
test_conformance.py             "does every vector on disk pass on both engines?"
```

Read them together and the shape is obvious in hindsight: each one **starts by
enumerating the present** and then asks a question about what it found. Break 41
is the closest relative — a vector that existed and was not executed — and even
that is a question about something present. None of them can ask *"is what used
to be here still here"*, because none of them has any idea what used to be here.
A vector that is deleted is not a failing vector. It is an absence, and absence
is the raw material every one of these guards is built out of.

**A count is not a guard.** `test_conformance.py` printed `96 passed` where it
had printed `103`, and that number moved past three people and two CI-shaped
runs without anyone reacting, because nothing anywhere held an expectation of
it. A number that nothing compares against is decoration. If a count is the
signal, something has to assert the count.

**So the fix cannot come from inside.** A guard over a set can never notice the
set shrinking; it needs an **external reference** — some other artifact that
names what ought to exist and is maintained for its own reasons. Maintained for
its own reasons is the load-bearing half. A list kept up to date *for the guard*
decays exactly as the thing it is guarding does, which is why
`check_ci_runs_every_suite.py` enumerates rather than holding a list in the first
place.

`docs/known-breaks.md` turned out to be that reference, already written and
already maintained: every row names the vector that catches its break, because a
row is worthless without one. So `backend/tests/test_known_breaks_cite_live_vectors.py`
asserts that every vector named in a code span there is still on disk. It caught
all seven, and it catches a single file deleted by hand. Break 82.

**The sweep that followed, because one loss is a reason to look for others.**
Every vector id cited anywhere — `docs/`, `specs/`, every Python and Kotlin
source and test file, and every commit message on every branch — checked against
every vector on disk and against what the generator produces. **105 distinct ids
cited, one absent: `choice-999`, which is the hypothetical inside break 41's
quoted error message and never named a file.** History agrees: 191 vector files
have ever been added and 191 are on disk, with no deletion recorded on any
reachable branch. Nothing else went the same way.

Two things the sweep turned up that were not the thing it was looking for.
`media-001` exists in **both** `conformance/vectors` and `conformance/crypto` —
a media round trip and per-chunk media encryption, two claims wearing one name —
so a bare citation of it names both files and the guard above is genuinely
weaker for that one id. That is now stated in `KNOWN_COLLISIONS` and a *new*
collision fails the build, so the next one is a decision rather than a hole. And
86 vectors on disk are cited nowhere at all: not a problem, but it is the exact
measure of how far the guard reaches — it protects what somebody wrote down as
load-bearing, which is not the same as everything.

**Where to apply this next.** The question to ask of any new guard is not "what
does it check" but *"what would it say if the thing it checks were gone"*. If
the answer is "nothing", find the artifact that already names what should be
there:

| Set | Would notice a deletion? | Reference that names it |
|---|---|---|
| `conformance/vectors` and the other four sets | **yes**, since break 82 | `docs/known-breaks.md` citations |
| Test suites | **no** — a deleted suite is a suite that never existed | nothing yet; `check_ci_runs_every_suite.py` enumerates |
| The rows of `docs/known-breaks.md` itself | **no** | nothing |
| A `TEST_SOURCE_SETS` entry | **no** | nothing |

The bottom three rows are honest gaps, not work items pretending to be done.
Delete `NavigatorTest.kt` today and nothing in this repository says a word.

### The refusals no vector format can express

`conformance/vectors` is a form plus an ordered list of steps, and **every step
assumes a form that compiled**. There is no way to write "this document must be
refused" in it. Two sets were built to cover that: `malformed` for §10.1, and
`sensitivity` for exactly one §10.2 rule.

**The rest of §10.2 is held by a test in each engine and nothing else** — the
nested-repeat refusal, and now the repeat-inside-a-field-list refusal. That is a
real exposure rather than a tidy division of labour: two engines that disagree
about which forms compile is a form author meeting a refusal their builder told
them was not there, which is the same failure the sensitivity set was built to
prevent and is prevented here only by whoever edits one file remembering the
other. The pairs are named in the table above so the second file is findable
from the first.

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

### A sequential fixture cannot see an ordering bug

The rule above is about a sentence with two halves. This one is about a fixture
with one shape, and it is the same failure arriving through the data rather than
through the prose.

> **A fixture whose ordering, numbering or naming is sequential cannot see an
> ordering bug. When what is under test is an order — of rows, of instances, of
> screens, of keys — make the fixture's natural orders disagree on purpose.**

The tell is that two different right answers coincide. If the rows are `V000`,
`V001`, `V002`, then key order, insertion order, published order and
alphabetical order are all the same sequence, and an engine that picked any of
them passes. The fixture is not weak evidence about ordering; it is **no**
evidence about ordering, while reading as though it were.

Three in one week, all found by reading rather than by any test:

- **`repeat-006`** claimed "shrinking discards the **trailing** instances" and
  asserted a count plus the first survivor — both true when the *middle*
  instance is discarded instead (break 76).
- **`screens-022`** was written with two instances and the enumerator in the
  first, so a stale ordinal fell out of range and any clamp landed on the right
  person by luck. **The break passed.** Rewritten to three instances with the
  enumerator in the middle, the stale ordinal stays in range and points at the
  next person (break 87).
- **`test_rows_page_resumes_from_its_cursor_and_says_when_it_is_done`** publishes
  `V000`…`V249`, where the file's order and the key order are one sequence. It
  is the guard that closed break 48 and it would pass against a store that
  sorted by key — which is exactly what the device does, and why
  `docs/known-defects.md` 16 went unseen for two versions of that schema.

The fix is cheap and it is a habit, not a technique: give the fixture a
published order that is not its key order, put the interesting instance in the
middle rather than at an end, and name rows so that alphabetical and intended
disagree. `rows-007` is written that way deliberately, and says so in its
description.

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

# The development database, recreated from nothing (drop, migrate, login for
# dcp_app, seed). Recreating is the fix for a drifted local database; the
# script's docstring says why.
python scripts/reset_dev_db.py --seed

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
- **There is one connection factory, and the application is never the
  owner.** `backend/app/infrastructure/database.py` hands out every session
  (`session_as`, `session_for_organization`) and builds every engine; the
  application role is `dcp_app`, which the row-level security policies bind,
  and the factory refuses at connect time a superuser, a BYPASSRLS role or the
  owner of the tables, because those are exempt from every policy and every
  screen looks correct while none applies. The principal the policies read is
  declared at the start of every transaction and never at session level (ERD
  §1.1); the pool discards a connection that comes back still carrying one.
  `tests/test_one_connection_factory.py` fails on a second engine, a raw
  asyncpg connection or a `postgresql://` literal in `app/` or `scripts/`;
  `tests/conftest.py` fails the db suite before its first test if the
  application connection is privileged; `tests/test_tenant_isolation.py` is
  the rest. Migrations and provisioning run as the owner through
  `DATABASE_ADMIN_URL` (`create_admin_engine`, `admin_connection`), and that
  is the only thing that does
- **Every route declares who may call it, and scope is a policy, not a
  filter.** A route carries exactly one of `access(permission=…, app=…)` or
  `public("why")` from `backend/app/api/access.py`;
  `tests/test_every_route_declares_access.py` walks the app's route table and
  fails on one that declares neither, naming it, and pins the public set. That
  declaration is the courtesy — the 401 or 403 a screen can show. The
  guarantee is the connection's principal: a person's `scope_kind` and
  `visible_user_ids`, computed from `user_role` at login and declared on every
  transaction, which `submission`'s policy reads whether the query came from a
  screen, an export, a report or a sync endpoint. A supervisor's team boundary
  is never a `WHERE` somebody has to remember. Whether a person may hold a
  session is the session policy's decision too: the login inserts the row and
  reports the policy's refusal; it has no status check of its own
  (`test_auth.py::test_04`). Authority is on the principal too
  (`app.permissions`, `app.project_ids`, `app.team_ids`, 010_people.sql):
  what a screen offers and what the database permits come from one list, and
  `test_people.py` goes under the routes with a real principal to show the
  refusal is the database's. A person is scoped like a submission, so the
  auth path — find the login, find the session, compute the principal, name a
  refusal, note the login — is five named SECURITY DEFINER functions and
  nothing else reads a person without one
- A guarantee is not defended until its break has been watched to fail —
  record it in `docs/known-breaks.md`
- **Commit the implementation before running a break.** A break is reverted
  with `git checkout -- <file>`, and that reverts the *file*, not the break: if
  the file also holds implementation that is not committed yet, the break takes
  it with it. This is rule 12's pair — rule 12 says work has to be on disk,
  this says the disk has to hold a version you can get back to — and it is
  written here because it has already cost an afternoon's engine work, on
  2026-09-06, in the middle of proving the very breaks that work was for. The
  order is: implement, run the suites, **commit**, then break, watch, revert.
  Committing first also makes the break's evidence exact, because `git diff`
  after the revert is empty or the revert did not finish
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
   second route into `form_version`. Scope doc §2 for why each. **Status,
   7 September 2026:** steps 1 and 3–6 of the scope doc's build order are
   done — the editor is `/forms/{id}` in the console, over `form_draft`,
   `POST /forms/compile` and `POST /forms/expressions`, holding no form logic
   (every screen number, diagnostic and parsed expression on that page is
   the server's answer, and `docs/known-breaks.md` 122–132 are the guards).
   Step 2 (reachability and liveness in `check_publishable`) landed the day
   after, closing the gap under the publish gate the scope doc's §0 describes
   — `conformance/reachability` is the six shapes it probed, and
   `docs/known-breaks.md` 133–136 the guards; step 7 (preview, trace, test
   mode) landed 7 September 2026 on the handset's engine compiled to Wasm
   (PR #36, breaks 137–150). **Item 0 is done**; what it leaves behind is one
   list in the scope doc, "What item 0 leaves behind", and defects 22–25
1. **Login and permissions.** Everything below depends on it. A user belongs to
   the organization, not to a project; a role is a set of permissions plus a
   scope, never a hard-coded branch, and every console screen checks a permission.
   **Status, 9 September 2026:** the schema is merged (PR #40 — migration
   0008, every policy from one helper, the coverage test that fails closed,
   `pending_approval` structural on `platform_session`), and the connection
   layer with it: the application connects as `dcp_app` through the one
   factory, every request carries the deployment's organisation as its
   principal (`ORGANIZATION_SLUG`, resolved before anything else is read),
   and the isolation tests run on that path. **Login landed the same day:**
   `POST /auth/login` for console and app (HttpOnly, SameSite=Strict cookie;
   the row holds the token's hash), `GET /auth/me`, `POST /auth/logout`; a
   person's scope replaces the organisation's on every request; every route
   declares its access and the route table is linted; the console has a
   sign-in page and a permission-gated nav, the handset a sign-in on its
   settings screen with the session kept in the encrypted database; the seed
   creates an admin, a PM, a supervisor with a team, an enumerator and a
   pending enumerator (`dcp-dev`). **The people screens closed item 1 the same
   day** (PR after #42): `/people`, `/teams`, `/roles`, the approval queue;
   migration 0010 puts the person's authority — permissions, projects, teams —
   on the principal and the database reads it, so a membership is created
   active only by an approver (the column DEFAULT), approval and deactivation
   are the matching permission's to make, a grant sits inside the grantor's
   own authority, a role carries only permissions its editor holds, and the
   standard roles cannot be edited. A person sees their scope, the people they
   created, and themself. Walked in the browser with real cookies: a
   supervisor sees Team A only, an admin both teams and the queue, an approved
   enumerator signs in and is told their work is on the handset. **Item 1 is
   done.** Two seeded teams now; seven people, password `dcp-dev`
2. **Sample assignment and supervisor isolation.** Isolation is visibility, not
   only assignment — which is why scope is part of the role rather than a filter
   applied in the UI. A filter can be forgotten in one query; a scope cannot.
   **Status, 9 September 2026:** the analysis is
   `docs/phase3-item2-sample-assignment.md` (approved, A1–A7), and the schema
   is migration 012 — a case is a sample row, held at two levels, and one
   rule, `dcp_case_in_scope`, decides what is in scope for every table under
   a case; reassignment moves the view and not the rows; an enumerator sees
   only their own work (defect 26, fixed ahead of this item). Breaks 172–180.
   The routes, screens and both runs are on `feat/item2-routes` (PR #48,
   stacked on #47): the sample upload (CSV, key columns, `case_key` on every
   row, migration 013), cases with their holders, the split by team and by
   person, `GET /sync/pull?scope=assignments` as a complete statement of the
   live assignments, `not_assigned` — the push path's one scope refusal,
   named, one op's cost; the console's sample page; the handset's case list,
   `case_record` (schema v9, never deleted), a draft on a released case kept,
   listed, openable and pushable. Walked in the browser (PM upload, split
   across two supervisors, each assigning to their enumerator, the pool
   invisible to both) and on the emulator (sign in, pull, one case, collect,
   sync, the case moved away, pull with the draft open → "no longer assigned
   to you — drafts kept", the pending op accepted; then `not_assigned` from
   the server explained in the sync bar). The runs found three things no
   test looked at, fixed on the same PR: a pending person could hold a case
   (migration 014), a stale case line on the collection screen, a device
   stranded by a recreated server. Record: `docs/e2e-run-2026-09-09-item2.md`.
   Breaks 181–189. Left: merge #47 then #48, the cleanup pass; the roster's
   `rowSource: dataset` (item 3) can now read `_metadata.case_key`
3. **Repeat screen flow**, and the roster it unblocks. **Spec and engines done,
   5 September 2026; the UI is what is left.** Form IR §11.3 decides it — a
   repeat is one screen holding the instance list, an instance is entered and
   left, and no instance count enters the screen plan, so the "N of M" a
   household of six reads is the one it read at five. Both engines implement it
   under `screens-012`…`screens-025`, and defect 14 is closed. `addLabel` /
   `summaryLabel` landed on both engines 6 September 2026 —
   `repeat-013`…`repeat-015`, `sensitivity-006`/`007`, breaks 99–104, and known
   defect 19 closed in the same commit. Remaining: the roster UI and §2.3's
   `rowSource` — a roster's
   rows also come **preloaded from the sample** or from a **fixed list in the
   form**, and all four sources render as the same one screen. The inline half
   is buildable now; the dataset half waits on `_metadata.case_key` (item 2) and
   on `docs/known-defects.md` 16. **A rowSource filter cannot read an answer**,
   and since 6 September that rests on the work rather than on a judgement: the
   rows come from the case the enumerator selected from their assigned sample,
   so there is no typed-id shape to design re-resolution for. Still open, and
   asked rather than assumed: what an enumerator *reads* to tell one roster row
   from another — scope doc §5.1 and §13 question 7
4. **Separate sync for sample and form.** Reference data over a village
   connection is a different proposition from a small form update, and the person
   holding the handset should decide which they are doing. Analysis:
   `docs/phase3-item4-separate-sync.md` (9 September 2026). Its §0 corrects the
   number this line used to carry: RCons's sample is 1,129 rows, and the
   38,000-row / 11.3 MB artefact is the village reference list (break 52,
   measured), so the expensive scope is reference data rather than the sample.
   **Status, 9 September 2026:** analysis on #49 (A1–A8 confirmed). The schema
   step is `feat/item4-schema`, stacked on it: handset **v10** —
   `form_version.ir_json` nullable, so a deployed version that has not been
   downloaded has somewhere to live, plus `sync_scope` — one pin-readiness
   answer (`DatasetStore.pinnedLists`, read only through `ReferenceData`, and
   lint-enforced), a finalisation gate that refuses by name ("Cannot finalise:
   villages v8 not downloaded — tap Reference data"), and the server's one
   validator, `limit=0` on the pull. Breaks 190–195; the first was watched to
   fail against main before the feature existed. **The routes, screens and both
   runs are on the same branch:** three actions (`syncWork` fetches no document
   and no row; `updateForms` and `updateReferenceData(datasetKey)` ask with
   `limit=0`), an Updates screen whose every card states what the tap will cost
   — "Update from v1 — only the rows that changed" against "Full download —
   about 11.3 MB", measured off rows this device holds of that same list — one
   button on the submissions screen so work is never a peer of the other two,
   and the empty message split four ways. Breaks 196–204, five of them found on
   a phone. Run record: `docs/e2e-run-2026-09-10-item4.md`. Left: merge #49
   then #50, then the cleanup pass
5. **Supervisor monitoring**, within scope only. Analysis:
   `docs/phase3-item5-supervisor-monitoring.md` (10 September 2026). Every
   number is a `COUNT` over the same policy-carrying table its list reads, on
   the same connection under the same principal — no summary table, no cache,
   no admin connection — because a dashboard that aggregates through a second
   query drifts from the list beneath it and only one of them is right. Target
   is the live-assigned case count and needs no new field; a zero is shown only
   where a non-zero was possible. Device scoping lands here, through
   `device.user_id` and `visible_user_ids`, with `WITH CHECK` written
   separately so public registration keeps working. One thing §7 asks for that
   the server cannot know: pending ops live in the device's outbox, so the
   device reports them. **Status, 10 September 2026:** analysis on #49's
   successor #51; the schema is migration **015** on `feat/item5-device-scope`
   — the device policy gains the person (no new column: `device.user_id` is
   bound at login), `USING` and `WITH CHECK` deliberately differ with the
   reason written at the policy, three definer functions carry the statements
   that must work before anybody has signed in, and
   `reported_pending_ops`/`reported_at` are named for whose word they are.
   `test_monitoring_scope.py` is the agreement guard: a supervisor's figure
   equals their list, is strictly less than org-wide, and matches an expected
   subset. Breaks 205–209. Next: the routes, the console page, and the runs
6. **Review and correction.** Reviewing what is flagged rather than everything is
   the differentiator, and it is a project setting

**The skip-to prototype was item 0 and is closed** (scope doc §12): the source
skip logic is Urdu prose in a codes column, and a person converts it to relevance
when entering the question in the dashboard. The conversion happens before any
tool sees it, so there was never a machine-readable corpus to convert. Giving
RCons the XLSForm template is still a real dependency of item 0.

**There is no timeline, deliberately** — the pilot happens when the platform is
ready, not on a date. The "roughly two months" this section used to carry
predated both item 0 and the item 3 correction, and survived them by looking
like a fact. Scope doc §11.

**Not in this phase**, named so the absence is a decision: desktop data entry
(the phase after this one — see `docs/known-defects.md` 1 and 2), the
`Structure Map` / `Custom` selection types, entity relationships and
longitudinal linking, nested repeats (IR v0.2), the workflow engine beyond
review, and text/audio audits. Reasons are in `docs/phase3-pilot-scope.md` §9.
