# Conformance Vectors

Language-neutral test cases that **every** Form IR engine must pass identically:

- the Python reference implementation (`backend/app/modules/form_engine`)
- the Kotlin engine (`shared/form-engine`) on JVM, Android, iOS and Wasm

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
| `expect.relevant` | Expected relevance per field path |
| `expect.values` | Expected values (after calculations) |
| `expect.required` | Expected required flag per field |
| `expect.valid` | Expected per-field validity |
| `expect.errors` | Expected error kinds per field |
| `expect.formValid` | Expected whole-form validity |
| `expect.choices` | Expected option values, in order (§3.2) |
| `expect.labels` | Expected option labels, per language |
| `expect.selector` | The selector **the source was asked for** (§3.2) |
| `expect.selectorOrder` | The selector's column order — sorted, so two engines emit it identically |
| `expect.candidates` | Rows the source handed back, before the residual ran |
| `expect.scans` | Whether the filter narrows at all, or is a full scan |

A vector may also carry a top-level `datasets` block — `{key: [rows]}` — for the
lists a `choices.kind = "dataset"` field chooses from.

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
