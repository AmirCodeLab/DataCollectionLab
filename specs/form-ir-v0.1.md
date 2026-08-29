# Form IR Specification v0.1

**Status:** Draft — Phase 0
**Applies to:** all form evaluation on every platform (Android, iOS, Desktop, Web, server)

The Form IR is the internal representation of a form. It is the contract between the form builder, the importers, and every runtime. XLSForm and ODK are *import sources*, not the runtime format.

Every runtime MUST produce identical results for the same IR and the same input sequence. Divergence is a bug, not a platform difference.

---

## 1. Document structure

```json
{
  "irVersion": "0.1",
  "formId": "household_survey",
  "version": 1,
  "title": { "en": "Household Survey" },
  "defaultLanguage": "en",
  "languages": ["en", "ar"],
  "children": [ <node>, ... ]
}
```

| Field | Type | Notes |
|---|---|---|
| `irVersion` | string | IR schema version. Runtimes reject unknown major versions |
| `formId` | string | Stable identifier, `^[a-z][a-z0-9_]*$` |
| `version` | integer | Published version number. Immutable once published |
| `title` | i18n string | See §7 |
| `defaultLanguage` | string | Must appear in `languages` |
| `languages` | string[] | BCP-47 tags |
| `children` | node[] | Ordered tree of nodes |

## 2. Nodes

Three node types: `question`, `group`, `repeat`.

### 2.1 question

```json
{
  "type": "question",
  "id": "age",
  "dataType": "integer",
  "label": { "en": "Age of respondent" },
  "hint": { "en": "Completed years" },
  "required": <expr|bool>,
  "relevant": <expr>,
  "constraint": <expr>,
  "constraintMessage": { "en": "Age must be between 0 and 120" },
  "calculate": <expr>,
  "default": <expr>,
  "readOnly": <expr|bool>,
  "sensitive": false,
  "appearance": "string",
  "choices": <choices>
}
```

All of `required`, `relevant`, `constraint`, `calculate`, `default`, `readOnly` are optional.

`sensitive` defaults to `false`. It marks a field whose **value** carries personal
or health information, and it is the input to `field_level` encryption
(Encryption Envelope §5.2): in a `field_level` project the values of sensitive
fields are encrypted end-to-end and everything else stays plaintext and
queryable. In `standard` and `project_e2e` projects the flag changes no runtime
behaviour, but it is still checked at publish time (§10) so a form does not
acquire a leak the day it is copied into a `field_level` project.

Sensitivity is a property of the field, not of the answer: it is fixed in the IR
and never depends on an expression.

**Data types**

| `dataType` | Value representation |
|---|---|
| `text` | string |
| `integer` | 64-bit signed integer |
| `decimal` | IEEE-754 double |
| `boolean` | true / false |
| `date` | `YYYY-MM-DD` string |
| `time` | `HH:MM:SS` string |
| `datetime` | RFC 3339 string |
| `select_one` | choice value (string) |
| `select_multiple` | array of choice values, order-insensitive |
| `geopoint` | `{lat, lon, alt?, accuracy?}` |
| `geotrace` | array of geopoint |
| `geoshape` | array of geopoint, implicitly closed |
| `image` / `audio` / `video` / `file` | media reference `{id, filename, hash, size}` |
| `signature` / `drawing` | media reference |
| `barcode` | string |
| `note` | no value; display only |

### 2.2 group

```json
{
  "type": "group",
  "id": "demographics",
  "label": { "en": "Demographics" },
  "relevant": <expr>,
  "appearance": "field-list",
  "children": [ <node>, ... ]
}
```

A group does not create a data scope. Child paths are **not** nested under the group id. Groups are presentational and control relevance inheritance only.

> Rationale: nesting data under presentational groups is the single most common source of confusion in XLSForm. Renaming or moving a group must never change a variable's path.

### 2.3 repeat

```json
{
  "type": "repeat",
  "id": "members",
  "label": { "en": "Household members" },
  "relevant": <expr>,
  "countExpr": <expr>,
  "minInstances": 0,
  "maxInstances": 30,
  "children": [ <node>, ... ]
}
```

A repeat **does** create a data scope. Children are addressed as `members[i].name`.

- If `countExpr` is present the instance count is controlled by it and the user cannot add or remove instances. Growing the count creates empty instances; shrinking it discards the trailing instances and their data.
- If absent, the user controls instance count, bounded by `minInstances` / `maxInstances`. `minInstances` instances are created when the form opens.
- **Nested repeats are not supported in v0.1.** A repeat inside a repeat is a compile error. Deferred to v0.2 — the reference-resolution and aggregate rules need designing before implementation, and shipping a half-defined version would be worse than refusing it.

Instances carry **stable ids** internally. Positional addressing (`members[0]`) resolves against the current ordered list at evaluation time. Deleting an instance removes it from the order and destroys its values; it never renumbers the surviving instances in storage, so an operation referring to a surviving instance stays valid after a concurrent delete elsewhere.

### 2.4 Identifier rules

- `id` matches `^[a-z][a-z0-9_]*$`
- `id` MUST be unique across the entire form, including inside repeats
- Reserved prefixes: `_` (runtime metadata)

## 3. Choices

Inline:

```json
"choices": {
  "kind": "inline",
  "items": [
    { "value": "m", "label": { "en": "Male" } },
    { "value": "f", "label": { "en": "Female" } }
  ]
}
```

Dataset-backed:

```json
"choices": {
  "kind": "dataset",
  "dataset": "districts",
  "valueColumn": "code",
  "labelColumn": { "en": "name_en", "ar": "name_ar" },
  "filter": <expr>
}
```

Choice filters evaluate per candidate row. The row's columns are addressable as `$row.column_name`.

## 4. Expressions

Expressions are a **typed AST**, never strings. The builder produces the AST; importers compile XPath into it; runtimes evaluate it directly.

### 4.1 Node kinds

```json
{ "op": "lit", "value": 18 }
{ "op": "ref", "path": "age" }
{ "op": "gte", "args": [ <expr>, <expr> ] }
{ "op": "call", "fn": "count", "args": [ <expr> ] }
```

| Category | Operators |
|---|---|
| Literal | `lit` |
| Reference | `ref` |
| Arithmetic | `add`, `sub`, `mul`, `div`, `mod`, `neg` |
| Comparison | `eq`, `ne`, `lt`, `lte`, `gt`, `gte` |
| Logical | `and`, `or`, `not` |
| Membership | `selected`, `in` |
| Conditional | `if` (3 args) |
| Function | `call` |

`and` / `or` accept two or more arguments and evaluate left to right.

### 4.2 Reference resolution

| Path form | Meaning |
|---|---|
| `age` | Field `age`, resolved from the current scope outward |
| `members[.].name` | Field `name` in the **current** repeat instance |
| `members[0].name` | Field `name` in a specific instance (0-based) |
| `members[].name` | All instances — produces a sequence, valid only as an aggregate argument |
| `$row.code` | Current candidate row, valid only inside a choice `filter` |
| `_metadata.start_time` | Runtime metadata |

Resolution from inside a repeat searches the current instance first, then walks outward to the form root. A reference that cannot be resolved is a **compile error**, not a runtime null.

One deliberate exception: a positional reference to an instance that does not currently exist (`members[0].name` when there are no instances) evaluates to `null` rather than erroring. The instance count is runtime state, not a static property, so this cannot be checked at compile time and must not crash a form mid-interview.

### 4.3 Functions (v0.1)

| Function | Signature | Notes |
|---|---|---|
| `count` | `(sequence) → integer` | Counts non-null values |
| `sum` | `(sequence) → number` | Nulls ignored; empty sequence → 0 |
| `min` / `max` | `(sequence) → number` | Empty sequence → null |
| `count_selected` | `(select_multiple) → integer` | |
| `coalesce` | `(a, b, ...) → any` | First non-null |
| `if` | `(cond, then, else) → any` | Lazy in both branches |
| `today` | `() → date` | Device date; frozen per evaluation pass |
| `now` | `() → datetime` | Frozen per evaluation pass |
| `age_years` | `(date, date?) → integer` | Whole years; second arg defaults to `today()` |
| `date_diff_days` | `(date, date) → integer` | |
| `date_add_days` | `(date, integer) → date` | |
| `len` | `(text) → integer` | Unicode code points |
| `upper` / `lower` / `trim` | `(text) → text` | |
| `concat` | `(text, ...) → text` | Nulls treated as empty string |
| `substr` | `(text, integer, integer?) → text` | 0-based |
| `contains` / `starts_with` / `ends_with` | `(text, text) → boolean` | |
| `regex` | `(text, pattern) → boolean` | RE2 syntax only — see §4.6 |
| `round` | `(number, integer?) → number` | Half away from zero |
| `int` / `dec` / `str` | explicit casts | No implicit coercion |
| `distance` | `(geopoint, geopoint) → decimal` | Metres, haversine, WGS-84 |
| `pulldata` | `(dataset, column, keyColumn, keyValue) → any` | Dataset lookup |

### 4.4 Null semantics

**This section is the most important part of the specification.** Divergent null handling is where competing implementations disagree, and it produces silently wrong data.

1. An unanswered question has value `null`.
2. Any arithmetic operation with a `null` operand yields `null`.
3. Any comparison with a `null` operand yields `null` (**not** false).
4. `not(null)` is `null`.
5. `and`: if any operand is `false` the result is `false`, even if another is `null`. Otherwise, if any is `null` the result is `null`. Otherwise `true`.
6. `or`: if any operand is `true` the result is `true`, even if another is `null`. Otherwise, if any is `null` the result is `null`. Otherwise `true`/`false` accordingly.
7. **Coercion to boolean happens only at the boundary**, when a relevance, constraint, required or readOnly expression produces its final value:
   - `relevant`: `null` → **true** (show the question — never hide data because of missing input)
   - `constraint`: `null` → **true** (pass — do not block on unevaluatable rules)
   - `required`: `null` → **false**
   - `readOnly`: `null` → **false**
8. Division by zero yields `null`, never an error or infinity.
9. `null` is never equal to `null`. `eq(null, null)` is `null`.
10. To test emptiness use `is_null(x)` / `is_not_null(x)`, which always return a boolean.

### 4.5 Numeric rules

- `integer` is 64-bit signed. Overflow is an evaluation error, not a wrap.
- `div` on two integers produces `decimal`. Use `idiv` for integer division.
- Mixed integer/decimal arithmetic promotes to `decimal`.
- Decimal comparison uses exact IEEE-754 semantics. The builder warns on direct equality comparison of decimals.
- `round` uses half-away-from-zero, not banker's rounding.

### 4.6 Regular expressions

Only **RE2** syntax is permitted — no backreferences, no lookaround. This is the only subset that is available and performs identically on Kotlin/JVM, Kotlin/Native, JavaScript and Python without catastrophic backtracking.

## 5. Evaluation model

### 5.1 Dependency graph

At compile time, build a directed graph of field dependencies from every expression. The graph MUST be acyclic; a cycle is a compile error naming the cycle path.

### 5.2 Recalculation

On any answer change:

1. Mark the changed field dirty.
2. Walk its transitive dependents in **topological order**.
3. For each node, evaluate in this order: `relevant` → `calculate` → `required` → `constraint` → `readOnly`.
4. `today()` and `now()` are evaluated once per pass and reused, so a single pass is internally consistent.

Evaluation is deterministic: identical IR plus identical answer state yields identical output, regardless of the order in which the answers arrived.

### 5.3 Relevance and data retention

- A question that becomes non-relevant **retains** its value in storage but reports `relevant: false`.
- Non-relevant values are excluded from export and from aggregate functions.
- If the question becomes relevant again, the previous value is restored.

> Rationale: destroying data on a relevance flip loses information when an enumerator corrects a typo in an earlier answer. Retention plus exclusion is recoverable; deletion is not.

### 5.4 Repeat instance lifecycle

- Instances are addressed by stable instance ids, not positions. Deleting instance 1 of 3 does not renumber the others in storage.
- Positional access (`members[0]`) resolves against the current ordered view.
- Deleting an instance removes its values and emits a tombstone (see the sync protocol).
- A repeat field is evaluated once per instance, in instance order, before the pass advances to the next field in topological order. A field outside a repeat that aggregates over it therefore always observes fully-evaluated instances.
- Aggregate functions over `members[].field` ignore nulls: `sum` of an empty or all-null sequence is `0`, `count` counts non-null values, `min`/`max` of an empty sequence are `null`.

## 6. Validation states

Each field reports:

```json
{
  "path": "age",
  "relevant": true,
  "required": true,
  "readOnly": false,
  "value": 17,
  "valid": false,
  "errors": [
    { "kind": "constraint", "message": { "en": "Age must be between 18 and 65" } }
  ]
}
```

Error kinds: `constraint`, `required`, `type`, `evaluation`.

Soft constraints use `"severity": "warning"` on the constraint and require an override reason, recorded with the submission.

## 7. Internationalised strings

```json
{ "en": "Age of respondent", "ar": "عمر المستجيب" }
```

Missing translations fall back to `defaultLanguage`. The compiler emits a warning, not an error, for missing translations.

## 8. Metadata

Automatically captured, addressable under `_metadata`:

| Path | Type |
|---|---|
| `_metadata.start_time` | datetime |
| `_metadata.end_time` | datetime |
| `_metadata.device_id` | text |
| `_metadata.user_id` | text |
| `_metadata.form_version` | integer |
| `_metadata.app_version` | text |
| `_metadata.language` | text |
| `_metadata.duration_seconds` | integer |

## 9. Versioning

- `irVersion` follows semver. Runtimes accept the same major version and any equal or lower minor version.
- A published form `version` is immutable. Editing creates a new version.
- Every submission records the exact `formId` + `version` it was collected against, and is always re-validated against that version, never the latest.

## 10. Compile errors vs warnings

**Errors** (block publish): unresolvable reference, dependency cycle, duplicate id, invalid id format, type mismatch, unknown function, wrong arity, unknown `irVersion`, **sensitivity leak**.

A **sensitivity leak** is a field that is not `sensitive` but whose `calculate`,
`relevant`, `constraint`, `required`, `readOnly` or `default` reads a field that
is. The derived value discloses its input, so publishing it would defeat
`field_level` encryption (Encryption Envelope §5.2). The fix is to mark the
reading field sensitive too, never to unmark the source. This is checked over
the same dependency graph §5.1 builds, so it is exact rather than heuristic, and
it blocks publish in every security mode.

**Warnings** (allow publish): missing translation, decimal equality comparison, unreachable relevance (statically false), repeat with no bound, unused calculate.

## 11. Screen flow

How an interactive runtime partitions a form into screens and navigates between
them. Every runtime MUST derive the same screen sequence from the same IR and
answer state — a screen skipped on one platform and shown on another is a
conformance failure, not a UX difference.

### 11.1 Partition

The screen plan is a pure function of the IR, computed once at compile time:

- Walk `children` in document order.
- A `question` becomes its own screen. **One question per screen is the default.**
- A `group` with `appearance: "field-list"` becomes a single screen containing
  every question in its subtree, in document order. Nested plain groups inside
  it are flattened into the screen; a nested `field-list` has no additional
  effect. A field-list group containing no questions produces no screen.
- Any other `group` contributes no screen of its own; its children are walked.
- A `repeat` subtree is excluded from the screen plan entirely. Screen flow for
  repeats is deferred to v0.2 together with repeat navigation UX.

Each screen records, in order: its zero-based `index`, the ordered question ids
it contains, the id of the field-list group that produced it (if any), and the
id of its nearest enclosing group (for headers). Screen indices are stable for
a given IR; relevance never renumbers them.

### 11.2 Navigation

Navigation is over the static plan filtered by live relevance:

- A screen is **relevant** when at least one of its questions is currently
  relevant (§5). Screens add no evaluation semantics of their own.
- `next(from)` is the lowest-index relevant screen with index greater than
  `from`; `next(-1)` is therefore the first relevant screen.
- `previous(from)` is the highest-index relevant screen with index less than
  `from`.
- Both yield nothing when no such screen exists. `from` itself need not be
  relevant.
- Progress is the screen's 1-based position within the ordered list of
  currently relevant screens, out of that list's length.

## 12. Open questions for v0.2

- **Nested repeats** — reference resolution, aggregate semantics across levels, and instance lifecycle when a parent instance is deleted
- Screen flow across repeats — per-instance sub-screens vs one screen per repeat
- Whether aggregates should exclude non-relevant instances (currently they do not; only null values are ignored)
- Cross-form references for case pre-population
- Server-only expressions and where they are declared
- Encrypted-field addressing — can a constraint reference an encrypted field
- External function/plugin call surface
- Choice filter performance contract on 50k-row datasets
