# The wasmJs spike — one day, 6 September 2026

Step 1 of item 0's build order. Browser preview needs the engine the handset
runs, not an approximation (`docs/phase3-pilot-scope.md` §2.1), and this was the
only unknown in the proposal. Everything here is what was measured, including
the parts that were more awkward than expected.

**It works.** The recommendation is option (a) — ship the Kotlin engine to the
console — but the decision touches open decision O-3 and is not mine to make.
Option (b) is still open and §4 of this document says what it would cost
instead.

---

## 1. Does `wasmJs()` build, with kotlinx-serialization?

**Yes, after a one-line fix — and that fix is the most valuable thing the spike
found.**

The first compile failed:

```
e: .../commonMain/kotlin/com/dcp/form/Datasets.kt:125:29 Unresolved reference 'toSortedMap'.
```

`toSortedMap()` returns a `java.util.SortedMap`. It is JVM-only, it was in
`commonMain`, and **the same line fails for Kotlin/Native**:

```
$ ./gradlew :shared:form-engine:compileKotlinIosSimulatorArm64
e: .../Datasets.kt:125:29 Unresolved reference 'toSortedMap'.
```

So the engine did not compile for iOS either, and had not for as long as that
line existed. Defect 18 recorded that Android and iOS "are declared build
targets that execute no vector". The truth was worse: **iOS was a declared
target that did not compile at all**, and nothing noticed because the only
target anything ever built was the JVM.

The fix is behaviour-preserving — the field is declared `Map<String, Expr>`, and
`entries.sortedBy { it.key }.associate { … }` is a `LinkedHashMap` in that
order, which is the iteration order the code always relied on. After it, both
`wasmJs` and `iosSimulatorArm64` compile.

kotlinx-serialization 1.11.0 needed nothing: it compiles, links and parses IR on
wasm with no source changes and no shims.

## 2. Bundle size

**~128 KB over the wire with brotli**, for an export surface a preview would
actually use.

| | raw | gzip | brotli |
|---|---|---|---|
| `.wasm` | 451,348 | 159,822 | 127,989 |
| JS glue | 7,640 | 3,226 | 2,886 |
| **total** | **~448 KB** | **~159 KB** | **~128 KB** |

**The first measurement was wrong and the reason matters.** With nothing
exported, the optimiser produced a **490-byte** `.wasm` — binaryen is entitled
to delete a module nobody can call, so that number measured the export list and
not the engine. Anyone re-running this must export a realistic surface first or
they will measure 490 bytes and believe it.

The surface used is `shared/form-engine/src/wasmJsMain/.../WasmFacade.kt`:
compile-and-plan, evaluate-and-report, and the publish-time sensitivity check.
JSON in, JSON out — **not a concession to the spike**: on wasmJs only primitives
and strings cross the `@JsExport` boundary, the IR is already JSON on the wire,
and this is the same boundary `POST /forms/compile` has.

One constraint worth knowing before designing against it: **`@JsExport` applies
to functions only on wasmJs**, not to objects. A JS-facing facade is a flat list
of names.

## 3. Can the conformance vectors run on it?

**Yes, and the CI job is in this commit.** This was the question the whole spike
was for, because a target with no test task is a guarantee covering a build
nobody runs — the pattern this repository has recorded four times, and adding
the target without a job would have been the fifth.

- `wasmJsNodeTest` runs on a Linux runner. No browser, no Karma.
- A wasm test **can read the corpus from disk**:
  `process.getBuiltinModule('fs')` is synchronous and works from the test's ES
  module. `require` does not — the test runs as an `.mjs`, and the first attempt
  failed with `globalThis.require is not a function`.
- **All 113 vector forms compile on wasm and their screen plans are built**
  (`WasmVectorReadTest`). That is the compile half of rule 2 running somewhere
  other than the JVM for the first time.
- Four behavioural assertions now live in `commonTest` and therefore run on
  **both** targets (`EngineParityTest`) — relevance of an unanswered
  dependency, relevance flipping, §2.3's label chain falling through to the
  position, and the screen plan.

**What is not done, stated plainly.** The vector *step* runner — `set`,
`addInstance`, `expect.relevant` and the rest — lives in
`jvmTest/ConformanceTest.kt` and was not ported. Running the full behavioural
corpus on wasm means moving that runner into a shared test source set, which is
a real piece of work and not a line of build config: the file reads vectors, and
file reading is the part that differs per target. Estimate: half a day, and it
would then cover Android and iOS too. Until it is done, wasm is verified for
**compilation and screen planning over the whole corpus, plus four behavioural
assertions** — which is more than any non-JVM target had before today, and less
than rule 2.

**The repository's own guard enforced this.** Creating
`shared/form-engine/src/wasmJsTest` made
`scripts/check_ci_runs_every_suite.py --strict` fail:

```
- shared/form-engine/src/wasmJsTest is a test source set this script does not know.
  Add 'wasmJsTest' to TEST_SOURCE_SETS with the Gradle task that runs it —
  an unrecognised suite must not read as a covered one.
```

That is break 24(d), unprompted, on a real change. The source set is now
registered against `wasmJsNodeTest` and the CI job runs it.

## 4. What it costs to load in the console

Measured on Node 26.8 on this machine. **A browser will differ** — network
transfer and streaming compilation are not modelled here — so treat instantiate
time as a floor, not a promise.

```
module import + instantiate                     14.7 ms
first previewCompile (2 questions, cold)        21.7 ms
```

Full parse + compile + recalculate, per call, by form size:

```
 100 questions    0.96 ms
 500 questions    3.77 ms
1000 questions    8.00 ms
```

Those numbers are the **whole pipeline every call**, because the spike facade
re-parses the IR each time. A real preview compiles once and only recalculates,
so per-keystroke cost is well below these. RCons's instrument is 95 sections;
even at 1,000 questions and re-parsing everything, this is one frame.

**This is the number that decides preview.** Option (b) — preview over
`POST /forms/evaluate` — cannot beat 8 ms on a village connection, and it runs
the Python reference rather than the engine the handset runs, which is the thing
§2.1 says it must not do.

## 5. What this changes if option (a) is chosen

- The `toSortedMap` fix is worth keeping **regardless of the decision**, because
  it is what makes the iOS target compile.
- Defect 18 is not closed by this. Android and iOS still execute no vector; wasm
  now executes some. The row should be updated rather than struck.
- O-3 is half-decided as a side effect, which is a reason to decide it
  deliberately rather than let it follow from a spike.
- `WasmFacade.kt` is spike code and is marked as such. It is not an API and
  nothing should be built against it until the export surface is designed.
