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

## Rules

1. A vector never encodes platform-specific behaviour.
2. When the spec is ambiguous, **write the vector first**, then amend the spec.
3. A failing vector blocks release. It is never "fixed" by changing the expectation without a spec change.

Run them:

```bash
cd backend && python -m pytest tests/test_conformance.py -v
```
