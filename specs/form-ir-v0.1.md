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
| `irVersion` | string | IR schema version. A runtime MUST refuse a version it does not implement — §9, §10.1 |
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
  "severity": "error" | "warning",
  "calculate": <expr>,
  "default": <expr>,
  "readOnly": <expr|bool>,
  "sensitive": false,
  "appearance": "string",
  "choices": <choices>
}
```

All of `required`, `relevant`, `constraint`, `calculate`, `default`, `readOnly` are optional.

`severity` qualifies this question's `constraint` and defaults to `error`; a
`warning` is a soft constraint, which does not block finalisation (§6.1, §6.2).
It sits on the question rather than on the constraint because a constraint is an
expression node (§4.1) and has nowhere to carry it.

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

Error kinds: `constraint`, `required`, `type`, `choice`, `evaluation`.

A field is `valid` when it reports no errors. A field that is not relevant is
always `valid` and reports no errors: relevance is decided first, and a question
that was never asked cannot have been answered wrongly. Its value is still
retained (§5.3).

### 6.1 Severity

`severity` is declared on the **question** (§2.1) and qualifies that question's
`constraint` error only. It is `error` unless the question says
`"severity": "warning"`. `required`, `type`, `choice` and `evaluation` errors are
always `error`.

A soft constraint — `"severity": "warning"` — makes the field invalid and is
shown to the enumerator like any other error, but it does not block finalisation
(§6.2). It is meant to be overridden with a reason recorded against the
submission; that recording is **not specified in v0.1** and no engine implements
it, so today a soft constraint is advisory and nothing about the override is
stored.

### 6.2 Navigation and finalisation

Two questions every interactive runtime has to answer: may the enumerator leave
a screen whose answers are wrong or missing, and may the submission be
finalised. Both are decided here, not by each platform's UI. A runtime that
answers them from its own UI layer will answer them differently from the next
runtime, and the difference will look like a UX detail until two devices
disagree about which submissions could be sent.

**Navigation is never gated on validity.** `next` and `previous` (§11.2) are a
function of the screen plan and live relevance alone. A runtime MUST NOT refuse
to leave a screen, disable its forward control, or skip a screen because a
question on it is unanswered or its answer is invalid.

The reason is the interview, not the data model. A respondent may refuse to give
their age, may not know their household's income, may end the interview halfway;
an enumerator who cannot move past the question invents an answer instead, and
an invented answer is worse than a gap because nothing downstream can see it.
The gap is visible — it is exactly what the blocking list below reports to the
supervisor.

**Finalisation is gated.** A submission MAY be finalised only when it has no
blocking fields.

- A field is **blocking** when it is relevant and carries at least one error of
  severity `error` (§6.1).
- A field that is not relevant never blocks, whatever value it retains.
- `blockingFields` is the ordered list of blocking paths: fields outside a
  repeat in document order, then the fields of each repeat instance in instance
  order. That is the order an engine holds its field states in, so every engine
  reports the same list in the same order.
- `canFinalize` is true exactly when `blockingFields` is empty.
- `firstBlockingScreen` is the lowest-index screen (§11.1) containing a blocking
  field, and nothing when there is none. It is always a relevant screen: a
  blocking field is relevant, and a screen is relevant while any of its
  questions is.
- A blocking field inside a repeat has no screen at all, because §11.1 excludes
  repeats from the plan. It still blocks finalisation, and `firstBlockingScreen`
  can therefore be nothing while `canFinalize` is false. Repeat navigation is a
  v0.2 question (§12); until it is answered a runtime MUST still refuse, and
  SHOULD name the field it cannot navigate to.

`canFinalize` and whole-instance validity are different questions: a form whose
only fault is a soft constraint is invalid and still finalisable.

A runtime that refuses to finalise SHOULD say how many fields are blocking, show
each one's error, and navigate to `firstBlockingScreen`. A refusal that does not
lead anywhere is a dead end an enumerator cannot get out of in the field.

### 6.3 Choice membership

The value of a `select_one` must be one of its question's choices. Every value
of a `select_multiple` must be. A value that is not produces **one** `choice`
error on the field — one error, not one per offending value, because the field
is what is invalid.

**Matching is exact.** Byte-for-byte on the choice `value`, with no trimming, no
case folding and no Unicode normalisation. `"Male"` does not match `"male"` and
`"fever "` does not match `"fever"`.

That is a decision rather than a consequence of how strings happen to compare,
and it is made this way because the alternative is worse in a specific way: a
device that accepted `"Male"` for `"male"` would **store** `"Male"`, and every
later comparison — a `selected()` call, a choice filter, an export column, a
cross-form reference — would have to make the same allowance or disagree with
it. One lenient boundary produces a value the rest of the system treats as
different. Where leniency is wanted it belongs at import, where a CSV's
whitespace can be cleaned once and reported, not at every comparison forever.

**An unanswered question is not a membership failure.** `null` produces no
`choice` error; a required unanswered question produces `required` as it always
did. An empty `select_multiple` is unanswered, not "a list containing nothing
valid" (§4.4).

**A submission is validated against the form version it was collected under**
(§9). An answer that was in v1's list and was removed in v2 stays valid for a
submission collected under v1. Engines do not choose a version — they are given
one — so what an engine must get right is that v1 accepts the value and v2
rejects it. Choosing correctly between them is the caller's, and is tested above
the engine.

### 6.4 Where membership is enforced

Membership is not enforced in the same places as the rest of §6, and the
difference is a property of the encryption mode rather than of the form.

| | `standard` | `field_level` | `project_e2e` |
|---|---|---|---|
| Client, before the op is written | yes | yes | yes |
| Server, on push | yes | non-sensitive fields only | **no** |
| Console, after decryption | n/a | sensitive fields | yes |

The client always validates: it holds the compiled form and the plaintext, and
this is where an enumerator is told. The server validates whatever it can read.
In `project_e2e` it can read nothing — it stores `value_ciphertext` and holds no
private key (Encryption Envelope §7), so it cannot check membership and does not
pretend to.

**What a `project_e2e` project therefore gets is a client that validates and a
server that cannot.** A hand-crafted push carrying a value outside the choice
list will be stored. This is inherent to end-to-end encryption — the property
that the server cannot read the data is the same property that stops it checking
the data — and it is stated here rather than left to be discovered, because it
is a real difference between the modes and a customer choosing `project_e2e` is
choosing it.

The remaining check belongs in the console, at the point where a key holder
decrypts a submission and can see the values. That is **not implemented**; it is
recorded in `docs/known-defects.md` so the gap is visible rather than assumed
closed by this section.

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

- `irVersion` follows semver. A runtime accepts the same major version and any equal or lower minor version.
- A runtime **MUST refuse** a document whose `irVersion` names a major version it does not implement, and MUST refuse it as a document error (§10.1) rather than compiling what it can. This is not advisory. A v0.1 runtime handed a v1.0 document does not know which of the fields it recognises still mean what they used to, so a partial read produces a form that looks correct and evaluates by the wrong rules — the one failure this specification exists to prevent. Refusing is also the only way the message reaches anyone: an enumerator whose device is a version behind must be told to update, and silence tells them nothing.
- A runtime MUST likewise refuse a **higher minor** version of a major version it implements, for the same reason: v0.2 may define an expression node or a node kind that v0.1 would silently ignore. Equal or lower minor versions are accepted.
- A published form `version` is immutable. Editing creates a new version.
- Every submission records the exact `formId` + `version` it was collected against, and is always re-validated against that version, never the latest.

## 10. Compile errors vs warnings

Refusal happens in two stages, and the distinction is not cosmetic — it is the
difference between "this is not a Form IR document" and "this is a Form IR
document that must not ship".

### 10.1 Document errors

Checked **first**, before any semantic check, over the raw document. A document
that fails here is not a Form IR document at all, so nothing later in this
specification applies to it: there are no fields to resolve references between
and no graph to look for cycles in.

A runtime MUST refuse such a document and MUST report which of these it is, and
where:

| Reason | Condition |
|---|---|
| `not_an_object` | the document, or a node inside `children`, is not a JSON object |
| `missing_field` | a required field is absent |
| `wrong_type` | a required field is present with the wrong JSON type |
| `unknown_node_type` | a node's `type` is not `question`, `group` or `repeat` |
| `unknown_ir_version` | `irVersion` names a version this runtime does not implement (§9) |

**Required fields.** Document: `irVersion` (string), `formId` (string),
`version` (integer). Node: `type` (string) and `id` (string); a `question` also
requires `dataType` (string). Everything else in §1 and §2 is optional and
defaults as described there — `children` absent means a form with no nodes,
which compiles, and is not the same as `children` present holding a string.

`version` must be an integer and not a string spelling one. A runtime MUST NOT
coerce: `"1"` and `1` would give two different published versions the same
number, and a submission records the version it was collected against.

> Rationale for making this a specified stage rather than an implementation
> detail. A statically typed runtime gets this gate free from its deserialiser
> and a dynamically typed one gets nothing, so leaving it unstated does not
> produce two implementations that differ in their error message — it produces
> one that refuses the document and one that crashes partway through
> compilation, with a stack trace where the reason should be. That is a
> conformance failure the vectors could not even express, because every vector
> in `conformance/vectors` assumes a form that compiled.

### 10.2 Semantic errors

Checked over a document that passed §10.1. These block publish:

unresolvable reference, dependency cycle, duplicate id, invalid id format, type
mismatch, unknown function, wrong arity, **sensitivity leak**.

A **sensitivity leak** is a field that is not `sensitive` but whose `calculate`,
`relevant`, `constraint`, `required`, `readOnly` or `default` reads a field that
is. The derived value discloses its input, so publishing it would defeat
`field_level` encryption (Encryption Envelope §5.2). The fix is to mark the
reading field sensitive too, never to unmark the source. This is checked over
the same dependency graph §5.1 builds, so it is exact rather than heuristic, and
it blocks publish in every security mode.

### 10.3 Warnings

Allow publish: missing translation, decimal equality comparison, unreachable
relevance (statically false), repeat with no bound, unused calculate.

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
- Neither consults validity. Navigation is never gated on whether the answers on
  a screen are present or correct — see §6.2, which also defines the gate that
  *is* enforced, on finalisation.

## 12. Open questions for v0.2

- **Nested repeats** — reference resolution, aggregate semantics across levels, and instance lifecycle when a parent instance is deleted
- Screen flow across repeats — per-instance sub-screens vs one screen per repeat
- Whether aggregates should exclude non-relevant instances (currently they do not; only null values are ignored)
- Cross-form references for case pre-population
- Server-only expressions and where they are declared
- Encrypted-field addressing — can a constraint reference an encrypted field
- External function/plugin call surface
- Choice filter performance contract on 50k-row datasets
