# Conformance Vectors

Language-neutral test cases that **every** Form IR engine must pass identically:

- the Python reference implementation (`backend/app/modules/form_engine`)
- the Kotlin engine (`shared/form-engine`), on the **JVM**, **wasmJs** and
  **Android** — the same vectors, executed three times

This line named four platforms until 6 September 2026 and was true of one. The
runner lived in `src/jvmTest` and read files with `java.io`, so the corpus could
not leave the JVM; Android and iOS executed nothing and Wasm was not a target.
It now lives in `commonTest` with a per-target reader, and each target's count
is read from **that target's own JUnit XML** by
`scripts/check_ci_runs_every_suite.py`:

```
conformance/vectors on jvmTest              116 vectors
conformance/vectors on wasmJsNodeTest       116 vectors
conformance/vectors on testAndroidHostTest  116 vectors
```

**iOS still executes nothing**, and that is deliberate rather than overlooked:
it needs a macOS runner the project does not have, and the same guard refuses
an `iosTest` source set without one (break 24(h)). Known defect 18 holds what
is left.

A vector is a JSON file with a form IR and an ordered list of steps.

```json
{
  "id": "relevance-001",
  "description": "what this proves",
  "spec": "4.4.7",
  "form": { ...Form IR... },
  "context": { "today": "2026-08-28" },
  "steps": [
    { "set": { "age": 20 } },
    { "expect": { "relevant": { "pregnancy": true } } }
  ]
}
```

## Step kinds

| Key | Meaning |
|---|---|
| `set` | Apply answers, then recalculate |
| `addInstance` | Add a repeat instance, by repeat id |
| `deleteInstance` | Delete one, by `{repeat, index}` |
| `refuse` | Wraps an `addInstance` or `deleteInstance` the spec says must be **refused** |
| `expect.relevant` | Expected relevance per field path |
| `expect.values` | Expected values (after calculations) |
| `expect.required` | Expected required flag per field |
| `expect.valid` | Expected per-field validity |
| `expect.errors` | Expected error kinds per field |
| `expect.formValid` | Expected whole-form validity |
| `expect.instanceCount` | Expected number of instances per repeat |
| `expect.rowKeys` | The source row each instance came from, in instance order — null for one the enumerator added (§2.3) |
| `expect.summaryLabels` | What each row of the instance list says, in instance order, per language (§2.3) |
| `expect.addLabels` | The text on a repeat's add control, per language — null where the form does not name it (§2.3) |
| `expect.choices` | Expected option values, in order (§3.2) |
| `expect.labels` | Expected option labels, per language |
| `expect.selector` | The selector **the source was asked for** (§3.2) |
| `expect.selectorOrder` | The selector's column order — sorted, so two engines emit it identically |
| `expect.candidates` | Rows the source handed back, before the residual ran |
| `expect.scans` | Whether the filter narrows at all, or is a full scan |

A vector may also carry a top-level `datasets` block — `{key: [rows]}` — for the
lists a `choices.kind = "dataset"` field chooses from.

## Why `refuse` asserts nothing about the message

A refusal's message is English, and these files are the contract between two
engines written by different people in different languages. Asserting the
wording would make a translation a release blocker and a reworded sentence a
false alarm; the `malformed/` set exists precisely because a *reason code* is
the thing worth comparing, and the runtime's bound refusals do not carry one.

So `refuse` asserts only that the operation was refused, and the vector around
it is what makes that specific. `repeat-009` deletes a valid index that a
permitted delete has already exercised two steps earlier, then asserts the
instance and its answer survived — so an engine that refused for the wrong
reason, or refused by throwing after mutating, fails anyway. `repeat-010` is
its control: the same step kind over `maxInstances`, which was already enforced,
so a failing `repeat-009` is the engine and not the harness.

## Why `rowKeys` is a list and not a lookup

`expect.rowKeys` names a whole ordered list rather than an index-to-key map, and
that is the assertion doing its job. What a `rowSource` is evidence about is the
**order** — an engine that sorted the rows, or renumbered them after a delete,
produces the same *set* of keys and would satisfy any per-index check written
against a fixture whose keys were already in order.

`rows-007` is built against exactly that. Its four keys are chosen so document
order, alphabetical order and reverse-alphabetical order are three different
sequences, and the row it deletes is a middle one. Measured: a copy of that
vector with its keys renamed `p1`…`p4` — identical in every other respect —
**passes** a break that sorts the rows, while `rows-007` fails it. See
`docs/project-conventions.md`, "A sequential fixture cannot see an ordering
bug", and breaks 94 and 48.

## Why a dataset vector asserts three things and not one

`expect.choices` alone is not enough, and this is the one place the format does
more than compare outputs. An engine that scanned all 38,000 villages and one
that looked up twelve by index produce the **same list**; on a handset they are
not the same engine. So `selector` and `candidates` are assertions about the
*question the engine asked*, recorded by the harness's dataset source rather
than read off the engine's own output — which was watched to catch nothing
(break 45). A change that quietly stops narrowing fails on those two while every
answer stays right.

## The other vector sets

This directory holds the **evaluation** vectors: a form that compiled, plus
steps over it. Three sets sit beside it because they assert things this format
cannot express, each with its own README and its own runner on both engines:

| Set | Asserts |
|---|---|
| `crypto/` | Envelope bytes are identical across engines |
| `sensitivity/` | Which forms the publish gate refuses, and with which message (§10.2) |
| `reachability/` | Which forms can never ask a question they hold — refused, warned, or clean — and the "never shown" list a builder badges (§10.2, §10.3) |
| `malformed/` | Which documents are refused before compilation, and why (§10.1) |
| `functions/` | Every §4.3 function against every value shape (§4.7) |

`malformed/` exists because there is no way to write "this document must be
refused" here — every step above assumes a form that compiled, so a document
the Python engine crashed on and the Kotlin engine rejected looked identical to
this suite: absent.

## Rules

1. A vector never encodes platform-specific behaviour.
2. When the spec is ambiguous, **write the vector first**, then amend the spec.
3. A failing vector blocks release. It is never "fixed" by changing the expectation without a spec change.

Run them:

```bash
cd backend && python -m pytest tests/test_conformance.py -v
```
