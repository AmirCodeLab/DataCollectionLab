# Document-Shape Vectors

Language-neutral fixtures for **Form IR §10.1**: is this a Form IR document at
all? That is a different question from "is this form publishable", and it is
checked first, over the raw document, before any semantic rule applies.

Both implementations must agree, on the outcome **and** on the reason:

- Python: `check_document` in `backend/app/modules/form_engine/document.py`,
  runner `backend/tests/test_malformed_conformance.py`
- Kotlin: `checkDocument` in `shared/form-engine` (`Document.kt`), runner
  `shared/form-engine/src/jvmTest/kotlin/com/dcp/form/MalformedConformanceTest.kt`

## Why this is a separate set

`conformance/vectors` cannot express any of this. Every vector there is a form
plus an ordered list of steps, and every step assumes a form that **compiled** —
there is no way to write "this document must be refused" in that format, so the
whole class of failure was invisible to the suite that exists to catch
divergence.

And it diverged. Before these vectors the Kotlin engine refused all of these
documents at parse, because `FormIr` is a `@Serializable` data class; the Python
engine had no parse step at all and read `ir["formId"]` straight off the dict,
so nine document shapes reached the API as **500s** rather than refusals. A
statically typed runtime gets this gate free and a dynamically typed one gets
nothing, which is exactly why §10.1 had to be specified rather than left to each
implementation.

## Vector shape

```json
{
  "id": "malformed-012",
  "type": "malformed",
  "spec": "10.1",
  "description": "a node with no id",
  "refused": true,
  "reason": "missing_field",
  "where": "children[0].id",
  "form": { ...the document under test... }
}
```

| Key | Meaning |
|---|---|
| `refused` | Whether every engine must refuse this document |
| `reason` | The §10.1 reason code. Present only when `refused` |
| `where` | Where in the document, `""` for the document itself. Present only when `refused` |
| `note` | Why an accepted document is accepted. Present only when not `refused` |

`reason` is one of `not_an_object`, `missing_field`, `wrong_type`,
`unknown_node_type`, `unknown_ir_version` — the table in §10.1.

**`where` is part of the contract, and `message` is not.** A form author needs
to be told which node, and both engines must name the same one; the prose around
it is each engine's own. This is the opposite of `conformance/sensitivity`, where
the message text *is* the contract — there, the message is the whole remedy
("mark this field sensitive too"); here the location is.

## The three accepted documents

A set of nothing but refusals only proves an engine is willing to refuse.
`malformed-020` to `-022` are documents that look suspicious and MUST compile:
`children` absent, a patch release (`0.1.7`), and a lower minor (`0.0`). They
are what stops the gate being tightened past the spec — refusing `0.0` would
strand every form published before the current minor.

## Written, not generated

Like `conformance/sensitivity` and unlike `conformance/crypto`, the expectations
here are written by hand against §10.1 and §9. There are no bytes to reproduce,
only a rule. Blessing one implementation's output would make the vectors agree
with whatever that implementation currently does, including its mistakes — and
one of these implementations was crashing, so there was nothing worth blessing.

When a vector fails, decide which side is wrong by reading the spec. Rule 3 in
`docs/project-conventions.md` applies here as everywhere: a failing vector is never fixed by
editing the expectation.

Run them:

```bash
cd backend && python -m pytest tests/test_malformed_conformance.py -v
./gradlew :shared:form-engine:jvmTest
```
