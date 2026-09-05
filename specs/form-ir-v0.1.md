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
  "addLabel": { "en": "Add another household member" },
  "summaryLabel": { "en": "{0}, age {1}" },
  "summaryLabelArgs": [ <expr>, ... ],
  "children": [ <node>, ... ]
}
```

A repeat **does** create a data scope. Children are addressed as `members[i].name`.

- If `countExpr` is present the instance count is controlled by it and the user cannot add or remove instances. Growing the count creates empty instances; shrinking it discards the trailing instances and their data.
- If absent, the user controls instance count, bounded by `minInstances` / `maxInstances`. `minInstances` instances are created when the form opens.
- **Nested repeats are not supported in v0.1.** A repeat inside a repeat is a compile error. Deferred to v0.2 — the reference-resolution and aggregate rules need designing before implementation, and shipping a half-defined version would be worse than refusing it.

`addLabel` and `summaryLabel` are what a repeat screen renders (§11.3), and both
are optional. `addLabel` names the add control — "Add another household member"
is per-form and per-language, so it belongs on the node and not in a client.
`summaryLabel` is what one row of the instance list says: a §7.1 interpolated
label evaluated **in the instance's scope**, so a bare reference among its
arguments resolves to that instance (§4.2), and every §7.1 rule applies to it
unchanged — null is the empty string, values are bidi-isolated, arguments are
dependencies, and a slot with no argument is a compile error. Where
`summaryLabel` is absent a row shows its 1-based position in the current order.

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

### 3.1 Dataset row identity

Every dataset row has a **key**: the value of the column a dataset is published
against. It is what a later version names when a row is changed or deleted, and
it is what `valueColumn` selects when that column is the key.

**The key is the cell's value, exactly.** No trimming, no case folding, no
normalisation — the same rule as choice matching (§6.3), and it has to be the
same rule for a reason that is easy to miss:

> A dataset-backed `select_one` stores a value taken from `valueColumn`. §6.3
> then validates that value against the resolved choice list by exact match. If
> a dataset row's key were trimmed on import while the stored answer kept its
> whitespace, a legitimate answer would fail membership against the very row it
> came from — and the report would say the value is not in the list while the
> list visibly contains it.

So the two are one decision, not two. A key of `"moshi "` and a key of
`"moshi"` are **different rows**, as are `"Moshi"` and `"moshi"`.

A key that is empty, or contains only whitespace, is refused: a row with no
identity cannot be selected, referred to, or deleted in a later version.

Keys that differ from one another *only* by surrounding whitespace or by case
are **reported at publish and not merged**. They are almost always a data
error — the same village entered twice — but merging them would be the platform
deciding that two rows a customer supplied are one, which is not a decision the
platform can make. The report names them; the publisher decides.

### 3.2 Resolving a dataset-backed list

**An engine never materialises a dataset.** It is given a *dataset source* and
asks it for rows. A runtime backed by 38,000 villages in SQLCipher and one
backed by an in-memory list of four must answer the same questions identically;
what differs is only how the source finds the rows.

#### The filter is decomposed at compile time

`choices.filter` is split, once, when the form is compiled — not walked from
scratch per candidate row:

- **selector** — the top-level `and`-conjuncts of the form
  `$row.column = <expr>` where `<expr>` contains no `$row` reference. These are
  the terms a store can answer from an index. Every cascading select is exactly
  this shape.
- **residual** — every conjunct the selector could not absorb, kept as one
  expression and evaluated per candidate row.

Resolution is then: evaluate each selector expression against the current
answers, ask the source for rows matching those column values, evaluate the
residual over what comes back.

Decomposition rules, which every engine MUST follow identically because a
vector compares the result:

- Only a top-level `and` flattens, and it flattens fully. `or` is never
  decomposed; an `or` at the top is entirely residual.
- An `eq` qualifies when exactly one side is `{"op":"ref","path":"$row.X"}` and
  the other side contains no `$row` reference anywhere in its subtree. Either
  order.
- A column bound twice keeps its **first** binding, in document order of the
  conjuncts; the later ones go to the residual. Nothing is merged and nothing
  is declared contradictory — `$row.a = 1 and $row.a = 2` selects on 1 and then
  finds nothing, which is the correct answer.
- The selector is ordered by column name, so two engines emit it identically.
- A selector expression evaluating to `null` selects on `null`, which matches
  no row unless the column holds null. It is not an absent constraint (§4.4).

#### Membership is a lookup, not a scan (§6.3)

Validating a `select_one` against a dataset asks whether **one value** is in the
resolved list. The engine therefore asks the source for rows matching the
selector *and* the value column equal to the answer, and — when there is no
residual — that is a single indexed lookup whatever the dataset's size. It is
never "fetch the list, then search it".

#### The performance contract

> Resolution is **O(rows matching the selector)**, never O(dataset). A filter
> whose selector is empty is a full scan over the dataset, and an engine says
> so rather than hiding it.

That is the contract v0.1 left open. It is met by the shape of the interface
rather than by an optimisation, which is why it is stated here and not in a
client: the engine decides *what* the list is, a source decides only how
quickly it can find it.

#### What it costs, measured on a device against a server

Pixel 6 Pro over Wi-Fi against a server on the LAN, the UCL biomass form's own
three cascading questions, the generated village data — 26 regions, 166
districts, 37,852 villages. `scripts/measure_datasets_on_device.sh` and the
`serverUrl` mode of the debug benchmark activity reproduce it.

| | first sync | second sync (300 villages renamed) |
|---|---|---|
| Over the air, received | 7.05 MB | **0.064 MB** |
| Sent | 37 kB | 2.2 kB |
| Rows delivered | 38,044 | 300 |
| Wall clock | 28–34 s | 56 s |
| Device database | +14.9 MB | +15.1 MB (both versions held) |

**The delta does what it was built for.** 66 kB instead of 7 MB is a 109×
reduction, and it is the number that decides whether a weekly update is
practical on a field connection.

**The wall clock does not.** 56 seconds to apply a 300-row change, because the
device seeds the new version by copying 37,852 rows and 76,000 index entries
inside SQLCipher. The transfer is solved and the application of it is not.

Per keystroke, at district → village over 37,852 villages:

| | one version held | two versions held |
|---|---|---|
| First narrow | 13.8 ms | 86 ms |
| Median | **7.3 ms** | 77–88 ms |
| 95th percentile | 12.3 ms | 95–105 ms |

The left column is the contract met. The right is not, and it is **not
explained** by this session's work: a device that reached two versions by two
full syncs measured 7.9 ms, and one that reached them by applying a delta
measured 77 ms on the same data. Recorded as an open defect rather than
described, because a number nobody can account for is not a result.

Both columns are downstream of something else: a device holds two versions of a
list because **nothing retires a form deployment**, so every form version ever
deployed keeps its reference data alive on every device forever. That is
`docs/known-defects.md` 4, and it is now the largest thing standing between this
feature and a field.

#### What it costs, on the bench

Measured on a **Pixel 6 Pro**, 38,000 villages of eight columns, through
SQLCipher, driving the real engine — `scripts/measure_datasets_on_device.sh`
reproduces it:

| | in memory | indexed |
|---|---|---|
| First keystroke on the question | **1,589 ms** | **45 ms** |
| Every keystroke after (median) | 17.4 ms | 9.8 ms |
| 95th percentile | 56.4 ms | 32.3 ms |
| Resident heap | 46.3 MB | 11.6 MB |
| First sync, writing 38,000 rows | 1.1 s | 3.2 s |
| Storage | 8.4 MB | 11.3 MB |
| Second sync: 200 changed rows | 137 ms | 2.7 s |

The left column is what "read the version and filter it" costs, and it is why
this section is written the way it is. A second and a half of nothing when an
enumerator taps a question is not a slow feature; it is an unusable one, and no
amount of care elsewhere makes up for it.

The right column is the cost moved to where it can be afforded. Narrowing is now
an index lookup, and the price is paid at **write** time — three seconds on a
first sync, which happens once at enrolment, and 2.7 seconds to apply a weekly
delta, which happens inside a sync that is already waiting on a network. Both
are background; neither is in front of anybody.

**Only the columns a filter narrows on are indexed**, and a server tells a
device which those are, because the filter is in the IR and the server is what
reads it. Indexing every column instead was measured too: 8 × 38,000 = 304,000
entries, a first sync of 7.7 s, 19.6 MB of storage, and a delta of **14.4
seconds** — because a delta copies the index across to the new version. An index
is not free and the difference between indexing what is used and indexing
everything was a factor of five on the number that matters most.

**An index that does not cover a column must not answer.** A lookup on an
unindexed column returns no rows, which is indistinguishable from a filter that
matched nothing — an empty village list on a device holding every village, with
nothing in an error state. So the engine's source checks coverage first and
falls back to the scan, and says which path it took. A fallback nobody can see
is a performance contract nobody can check.

**A client MUST NOT pre-narrow the candidate set.** Handing an engine "the rows
I think are relevant" makes the client the thing that decides what the choice
list is — and which rows are candidates is a *which-artifact* decision, of
exactly the kind a conformance vector is structurally unable to see (a vector
fixes the inputs; it cannot see a caller choosing them). Two clients would
narrow differently, both would pass every vector, and the enumerator on one
would be offered villages the other hides. The source is allowed to be fast.
It is not allowed to be selective.

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
| `sqrt` | `(number) → decimal` | Negative → `null`, never NaN (§4.7) |
| `sin` / `cos` / `tan` | `(number) → decimal` | Radians |
| `atan` | `(number) → decimal` | Radians, in (-π/2, π/2) |
| `int` / `dec` / `str` | explicit casts | No implicit coercion — see §4.3.1 |
| `distance` | `(geopoint, geopoint) → decimal` | Metres, haversine, WGS-84, **rounded to millimetres** — see below |
| `pulldata` | `(dataset, column, keyColumn, keyValue) → any` | Dataset lookup — resolved through the form version's pin, §3.2 |
| `is_null` / `is_not_null` | `(any) → boolean` | Always a boolean, never null — §4.4.10 |

The trigonometric functions and `sqrt` are here because a real form needed
them. The UCL biomass survey corrects a plot radius for slope with
`round(15 div (sqrt(cos(atan(${slope} div 100)))), 2)`, which is the ordinary
way a field protocol turns a percentage gradient into a horizontal distance —
and it needs three of them at once. The roadmap had recorded only `atan`,
because the importer reports the first function it cannot translate per cell and
`atan` is the innermost: `cos` and `sqrt` were behind it the whole time and no
count could see them.

`sin` and `tan` are not attested in the corpus and are here anyway. A form
format with `cos` and no `sin` is a trap an author falls into once, and the
asymmetry would cost more than the two lines do.

**These four are accurate to within one unit in the last place, and no
further.** `sin`, `cos`, `tan` and `atan` are library calls, and both platforms
permit their libraries that much error — so two engines computing the same angle
can legitimately differ in the last bit, exactly as `distance` was found to
(break 50). A form that compares a trigonometric result must round it first, and
`conformance/vectors/trig-003` asserts to nine decimal places for that reason:
eleven orders of magnitude beyond any survey use, and comfortably inside the
guarantee. This is the only place in §4.3 where the answer is a range rather
than a value, and it is stated rather than discovered.

`sqrt` of a negative number is `null`, not NaN. §4.7 makes evaluation total and a
NaN is neither a number nor an absence — it compares false to everything
including itself, which would make a constraint pass and a relevance hide, both
silently.

`distance` is rounded to three decimal places, and that is a conformance
decision rather than a display one. The haversine is four transcendental calls
deep, and `sin`, `cos`, `asin` and `sqrt` are permitted an error of one unit in
the last place by both platforms' libraries — so two engines computing the same
formula over the same inputs legitimately differ in the last bit, and did:
325481.7667839453 against 325481.7667839454 metres. A millimetre is four orders
of magnitude below the accuracy of any GPS fix this platform will accept
(§6.1), so nothing real is lost, and the alternative is a vector that fails on
one platform's libm for reasons no author can act on.

**This table is the complete list, and it is checked by execution.** Every name
here is called on both engines by `conformance/functions`, which is derived from
this table rather than from a list somebody maintains beside it. That is not
belt-and-braces: `regex`, `substr` and `distance` sat in this table, implemented
in the Python reference and absent from the Kotlin engine, for as long as both
existed — a form using one worked on the server and threw mid-interview on a
phone — and `pulldata` was in the table and in neither. All four were *declared*
in the Kotlin signature map, which is why nothing may be checked against a
declaration. Break 49.

#### 4.3.1 The explicit casts

There is no implicit coercion anywhere in this IR (§4.5), which is precisely why
`int`, `dec` and `str` have to be defined exactly: they are the only way a form
gets from one type to another, and a dataset column is *always text* — a CSV
holds nothing else — so `int($row.population) > 1000` is the ordinary case
rather than an exotic one.

| Input | `int` | `dec` | `str` |
|---|---|---|---|
| `null` | `null` | `null` | `null` |
| integer | itself | the same value as a decimal | its digits |
| decimal | **truncated toward zero** | itself | see below |
| text | parsed, then truncated toward zero | parsed | itself |
| unparseable text | `null` | `null` | itself |
| boolean | `null` | `null` | `"true"` / `"false"` |
| geopoint, media, sequence | `null` | `null` | `null` |

Text is parsed after **trimming surrounding whitespace only**; nothing else about
it is normalised, and a thousands separator or a currency symbol makes it
unparseable rather than being stripped. `int("800.7")` is `800`: it parses as a
number and then truncates, exactly as `int(800.7)` does, because a cast that
accepted `800.7` from one source and refused it from another would make the
result depend on where the value came from.

**Unparseable text is `null`, never an error.** A cast is an expression inside a
`relevant` or a `constraint`, evaluated on every keystroke over whatever the
respondent has typed so far — `int("8")` on the way to `int("800")` is fine, and
`int("8a")` must not stop the form. Null then propagates by §4.4 and the
boundary rules decide what it means, which is the behaviour every other partial
value in this IR already has.

`str` renders a decimal without a trailing `.0` when it is integer-valued, so
`str(dec("800"))` is `"800"` and can be compared against a text column.

> Both engines got this wrong, in opposite directions, until
> `conformance/vectors/cast-*` existed: the Kotlin engine returned `null` for
> `int("800")` — silently emptying any filter over a dataset column — and the
> Python reference raised `ValueError` on `int("8a")`, which reached the API as
> a 500. Neither had a vector, because until dataset columns existed nothing in
> the corpus ever passed text to a cast. Break 44.

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

### 4.7 Type mismatch, and the totality of evaluation

§4.4 says what happens when a value is missing. This says what happens when a
value is *present and of the wrong type* — which the specification did not say
at all until dataset columns made it an everyday case, and which both engines
had therefore been answering differently for their whole existence.

> **An argument that is not of the type its signature (§4.3) declares is
> `null`, and a function or operator with such an argument yields `null`. It is
> never an evaluation error.**
>
> **Evaluating an expression raises for exactly one reason: integer overflow
> (§4.5).** Everything else — a text where a number belongs, a sequence where
> text belongs, a boolean in arithmetic — is `null` and propagates by §4.4.

#### Why null and not an error

An expression is not evaluated once when a form is written. It is evaluated on
every keystroke, on a handset, in the middle of an interview, over whatever the
respondent has said so far. There is no channel in that situation for a type
error: nothing on the screen can explain it, the enumerator cannot act on it,
and the only thing an exception can do is stop the form.

`null` already has a defined meaning in exactly that situation, and the
boundary rules in §4.4.7 already say what it does for the person holding the
device — `relevant` shows the question, `constraint` passes. Those are the
right answers for "this rule could not be worked out", and they are the same
answers whether the reason was a missing value or a nonsensical one.

**This is not an argument for silence.** A form comparing a text field to a
number is a form with a bug in it, and the place to report that is the publish
gate, where an author is reading a report — not the device, where nobody is.
That check does not exist yet; §12 records it. Reporting a type error at
evaluation time reports it to the one audience that cannot use it.

#### What follows from the signatures

Every case below is the rule above applied to §4.3's table, listed because
"derivable" and "agreed by two engines" are different claims:

| Expression | Result | Because |
|---|---|---|
| `len(["a","b"])` | `null` | `len` takes text; `count` is the one for sequences |
| `upper(800)` | `null` | takes text |
| `substr(800, 0)` | `null` | takes text |
| `contains(true, "a")` | `null` | takes text |
| `round("800.7")` | `null` | takes a number — `round(dec("800.7"))` is the way |
| `round(1.5, "2")` | `null` | the digits argument takes an integer |
| `sum(["a", 3])` | `3` | non-numbers are ignored, exactly as nulls are |
| `min(["a","b"])` | `null` | takes a sequence of numbers; no numbers, no minimum |
| `date_diff_days("8a", today())` | `null` | takes dates |
| `date_add_days(today(), "3")` | `null` | takes an integer |
| `"800" + 1` | `null` | `add` is arithmetic; `+` never concatenates |
| `true + true` | `null` | a boolean is not a number (§4.3.1) |
| `-("800")` | `null` | `neg` is arithmetic |
| `not("yes")` | `null` | takes a boolean |
| `"800" < 100` | `null` | a comparison across types has no ordering |
| `"800" == 800` | `false` | **not** null — see below |
| `if("yes", a, b)` | `null` | the condition takes a boolean |
| `distance("a", b)` | `null` | takes geopoints |

`concat` is the one function that renders rather than refuses: it takes text and
its job is to build some, so each argument is rendered as `str` renders it
(§4.3.1) and a `null` contributes the empty string. `concat("n=", 3)` is
`"n=3"`.

#### Equality is the exception, and deliberately

`eq` and `ne` are **total across types**: two non-null values of different types
are simply not equal, so `eq` is `false` and `ne` is `true`. They are not
`null`.

This is the one place where "no implicit coercion" (§4.5) produces an *answer*
rather than an absence, and it has to: `"800" == 800` is a question with a
correct answer under a no-coercion rule, and that answer is no. Ordering
comparisons are different — there is no ordering *between* types to appeal to,
so `<` genuinely cannot say.

The rule reaches further than it looks. A dataset cell is always text (§3.2),
so a filter written `$row.population = ${count}` against an integer answer
matches nothing at all — correctly, and silently. `str(${count})` is what makes
it work, which is why §4.3.1 defines `str` over numbers so precisely.

> Found by running every §4.3 function and operator against every value shape
> on both engines and diffing: **762 of 1,395 probes disagreed.** Not one had a
> vector, because until a dataset column existed nothing in the corpus could put
> text where a number belonged. Most were one engine raising while the other
> returned `null`; the worst were both returning a value and the values
> differing. `conformance/functions` is that matrix, with the expectations this
> section defines. Break 46.

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
- `firstBlockingScreen` is a **position** (§11.2), not a bare index: the earliest
  place a runtime can send the enumerator to see a blocking field, and nothing
  when there is none. For a field outside a repeat it is that field's screen. For
  a field inside one it is the full triple — the repeat screen, that instance,
  and the instance screen holding the field — because landing somebody on the
  roster and leaving them to work out which of thirty members is at fault is a
  refusal that does not lead anywhere.
- "Earliest" is **screen order**: lowest top-level screen index; then, within a
  repeat screen, earliest instance in instance order; then lowest instance screen
  index.
- **That is not `blockingFields[0]`'s screen**, and the two are not
  interchangeable. `blockingFields` is field-state order — every field outside a
  repeat, then each repeat instance's — so a blocking field on screen 9 can come
  first in that list while a blocking field on repeat screen 3 is the earliest
  place to go. Both orders are defined; they answer different questions.
- It is always a relevant position: a blocking field is relevant, and a screen is
  relevant while any of its questions is.
- `firstBlockingScreen` can still be nothing while `canFinalize` is false, and
  the case is no longer repeats. **A `calculate` produces no screen** (§11.1),
  and a calculate carrying a failing hard `constraint` is relevant and blocking,
  so nothing in the plan holds it. A runtime MUST still refuse, and SHOULD name
  the field and show its message. This is a live dead end rather than a
  hypothetical one — `docs/known-defects.md` 15 — and closing it is a decision
  about where to send somebody for a field nobody can answer, not a repair to
  this sentence.

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

### 7.1 Interpolation

A `label` or `constraintMessage` may carry **positional slots** filled from
expressions, so a form can say what it computed:

```json
{
  "type": "question", "id": "note3", "dataType": "note",
  "label": {
    "en": "The corrected full plot radius is {0} m, the inner {1} m.",
    "sw": "Radius ya kupima ya plot kubwa ni {0} m, ndogo {1} m."
  },
  "labelArgs": [
    { "op": "ref", "path": "slope_radius" },
    { "op": "ref", "path": "slope_radius_inner" }
  ]
}
```

`constraintMessage` takes `constraintMessageArgs` the same way.

**`label` does not change type.** It is `{lang: string}` as it always was; the
slots are `{0}`, `{1}`, … in the string, `{{` is a literal `{`, and a document
with no `…Args` is substituted not at all. That keeps every existing renderer
compiling, and it keeps the failure mode of a renderer that ignores the args
*visible* — a label reading `{0}` is obviously broken, where a label quietly
missing its number is not.

Slots are shared across languages: argument *n* is the same expression in every
translation, so a translator may reorder them freely. `{5}` with three arguments
is a compile error (§10.2), not an empty string.

This is **not** an optional capability. Unlike a widget for a dataType, filling
a slot needs no affordance a client might lack — anything that can render a
string can do it — so a client that does not is simply wrong, and there is
nothing for a registry to gate.

Choice labels are excluded. A `choices.items[].label` is plain text with no
slots and no arguments: an option list whose wording changes as answers change
is confusing to read, and the corpus has exactly one form that does it. The
XLSForm importer keeps reporting `output_in_label` there.

#### What is interpolated

Any expression valid in the field's scope, except `$row` — a label has no
candidate row, and one is a compile error. Values render exactly as `str()`
renders them (§4.3.1), so an integer-valued decimal is `800` and not `800.0`.

#### Null is the empty string

The same rule `concat` already has (§4.3), and for the same reason: this is
text built from parts that may be missing. So a label reads `"Radius is  m"`
until its input is answered.

The IR does **not** substitute a placeholder. Whether the gap should read `—`
or `...` or nothing is a translation decision, and an author who wants one
writes `coalesce(${slope_radius}, "—")` — which is what `coalesce` is for, and
is the reason arguments are expressions rather than bare references.

#### Every value is isolated (bidi)

> An engine MUST wrap each non-empty interpolated value in
> **U+2068 FIRST STRONG ISOLATE** and **U+2069 POP DIRECTIONAL ISOLATE**.

Not a rendering hint and not the client's business — the engine emits the
codepoints, both engines emit the same string, and
`conformance/vectors/label-004` asserts them by number so that removing them
fails rather than merely looking different.

The reason is the reason RTL is a rule in this project rather than a
preference. A run of Latin digits inside Arabic text is directionally neutral at
its edges, so the Unicode bidirectional algorithm resolves it against the
surrounding paragraph and can drag it out of position: `الشعاع 15 م` renders
with the number in the wrong place, and a two-number string reorders outright.
That is exactly the bug that produced `25 / 5` for a page indicator reading
`5 / 25`. An isolate makes the inserted run opaque to the paragraph's
resolution, which is the only fix that works for *every* value rather than the
ones somebody tested.

An empty value is not wrapped: an isolate exists to protect a run of text and
there is no run.

#### Arguments are dependencies

`labelArgs` and `constraintMessageArgs` participate in the dependency graph
(§5.1) exactly as `relevant` and `calculate` do. A label that reads `${tag}`
depends on `tag`, and a runtime that did not record that would leave `tag
number 41` on screen after the answer became 42 — correct on every static
check and wrong the moment anybody types.

It follows that a reference to a name nothing answers is a **compile error**
(§4.2), where today it is a label that silently reads `${plot_id}` to a
respondent.

#### Sensitivity: refused, and this is precaution

A label interpolating a `sensitive` field is refused at publish by the same
propagation rule as a calculation (encryption envelope §5.2). It comes free —
the arguments are in `depends_on`, and that is what the check reads.

**Being exact about why: this is not a live disclosure.** A rendered label is
never stored, never synced and never encrypted; it exists on a screen for as
long as the question is on it, and the value it shows is one the enumerator can
already see in the field it came from. The refusal is precaution.

The condition that would change it, written down so the next person meets a
decision rather than an oddity: **any feature that logs, exports or caches a
rendered label** — a crash report carrying the visible screen, an export that
includes question text, a client that persists rendered strings for offline
display. Any of those turns this from precaution into a leak, and at that point
the refusal is load-bearing and must not be relaxed. Until then it is cheap,
and a refusal that costs nothing is not worth removing for tidiness.

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
mismatch, unknown function, wrong arity, **sensitivity leak**, **a repeat inside
a field-list group**.

A **repeat inside a `field-list` group** is refused because the two say
contradictory things about the same questions, not because we are choosing
between two workable behaviours. `appearance: "field-list"` means *these
questions appear together on one screen*; a `repeat` means *this is a separate
screen you enter and leave* (§11.3). Both cannot be true of the same subtree, so
the refusal states what is already the case rather than picking a side. The
alternative — dropping the repeat's questions from the field-list screen — is
the silent-omission defect §11.1 exists to close, reappearing in a corner nobody
would look in.

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
- **A `question` carrying a `calculate` produces no screen and appears on none.**
  It is computed, never asked: its own screen would be blank, and counting it
  would make §11.2's progress overstate the work left on every form that
  carries one.
- A `group` with `appearance: "field-list"` becomes a single screen containing
  every question in its subtree **that is not a `calculate`**, in document
  order. Nested plain groups inside it are flattened into the screen; a nested
  `field-list` has no additional effect. A field-list group containing no
  questions — or only calculates — produces no screen.
- Any other `group` contributes no screen of its own; its children are walked.
- A `repeat` becomes **exactly one screen** — its **repeat screen** — carrying no
  questions of its own. Its children are partitioned separately, by these same
  rules, into the repeat's **instance plan**, which is rendered once per instance
  (§11.3). A repeat contributes one screen whether it holds zero instances or
  thirty.
- A `repeat` inside a `field-list` group is a **compile error** (§10.2). The two
  say contradictory things about the same questions: a field-list group means
  they appear together on one screen, a repeat means they are a separate screen
  you enter and leave.

**Why a repeat is one screen and not one per instance.** The first sentence of
this section is the load-bearing one, and instances are what would break it. An
instance count is not in the IR — under `countExpr` it is a function of the
answers, and without one the enumerator decides, so for a household roster
nobody knows the number until the interview is over. Instances as screens would
make the plan a function of answer state, and every index after the repeat would
move under the enumerator's hand each time they added a member. One screen per
repeat is what keeps the plan pure and the indices stable; §11.3 says so again,
where somebody changing it will be reading.

Each screen records, in order: its zero-based `index`; its `kind`, which is
`questions` or `repeat`; the ordered question ids it contains, empty for a repeat
screen; the id of the repeat that produced it, only for a repeat screen; the id
of the field-list group that produced it (if any); and the id of its nearest
enclosing group (for headers). Screen indices are stable for a given IR;
relevance never renumbers them, and neither does adding or deleting an instance.

**The instance plan.** A repeat's instance plan is built from the repeat's
`children` by the rules above. Its screens are indexed from zero *within the
instance*, and they carry question **ids**, not paths — a runtime binds them to
`repeatId[instanceId].questionId` when it renders one instance. Because a repeat
inside a repeat is a compile error (§2.3), an instance plan can contain no repeat
screen: the nesting is exactly two levels deep, and it is that compile error and
not a convention which keeps it there.

### 11.2 Navigation

Navigation is over the static plan filtered by live relevance.

A **position** is either a top-level screen index, or — while the enumerator is
inside a repeat instance — the triple (repeat screen index, **instance id**,
instance screen index). Every rule below is a function of the plan, the answer
state and a position, and yields a position. No runtime keeps a cursor the others
cannot reproduce, which is the same reason §6.2 gives for deciding finalisation
here rather than in each UI.

- A screen is **relevant** when at least one of its questions is currently
  relevant (§5). Screens add no evaluation semantics of their own. A repeat
  screen has no questions, so §11.3 decides it instead.
- `next(from)` is the lowest-index relevant screen with index greater than
  `from`; `next(-1)` is therefore the first relevant screen.
- `previous(from)` is the highest-index relevant screen with index less than
  `from`.
- Both yield nothing when no such screen exists. `from` itself need not be
  relevant.
- `enterInstance(repeat, instance)` is the only way into an instance: the
  position becomes that instance's first relevant instance screen, or the repeat
  screen if it has none. **`next` never enters an instance** — it lands on the
  repeat screen and stops there, so `next` moves exactly one screen every time it
  is called and `previous` stays its inverse.
- Progress is the screen's 1-based position within the ordered list of
  currently relevant screens, out of that list's length. A repeat screen counts
  **once**, and **progress MUST NOT count instances**.

  A twelve-screen form whose fourth screen is a household roster reads `4 of 12`
  on that roster; it still reads `4 of 12` when the household turns out to have
  six members, and again when a seventh is added. A denominator that moves while
  the enumerator works is worse than no denominator — it is a promise about
  remaining work that the form then withdraws — and for an enumerator-driven
  roster the number cannot be known in advance by anybody, the respondent
  included.

  While inside an instance the form-level pair does not move at all: the
  enumerator has not left the repeat screen. An instance carries its own two
  pairs, and §11.3 specifies them.
- Neither consults validity. Navigation is never gated on whether the answers on
  a screen are present or correct — see §6.2, which also defines the gate that
  *is* enforced, on finalisation.

### 11.3 Repeats

**One screen, and why it has to stay one.** §11.1's first sentence is
load-bearing for everything here: the screen plan is a pure function of the IR,
computed once at compile time. An instance count is not in the IR, so **an
instance count MUST NOT enter the screen plan.** A repeat contributes exactly one
screen whether it holds zero instances or thirty; adding or deleting an instance
changes no index, changes the plan not at all, and is invisible to the function
that builds it. Everything per-instance comes from the instance plan, which is
itself a pure function of the IR.

That is the constraint to check a change against rather than a consequence of
one. Every rule below is downstream of it.

**The repeat screen** shows the repeat's instances in their current order, a way
into each, an add control where §2.3 permits adding, and a delete control on each
instance where §2.3 permits deleting. It asks nothing itself. §2.3 decides what
is permitted; this section says only where it surfaces.

**Relevance.** A repeat screen has no questions of its own, so §11.2's rule
cannot decide it. A repeat screen is relevant when **both** hold:

1. the repeat's own `relevant` is true (§5, with null coerced to true as
   everywhere), **and**
2. it has something to offer — at least one instance, **or** an instance the
   enumerator may add.

Both halves of the second condition carry weight, and they pull in opposite
directions. A `countExpr` repeat currently sized zero offers no instance and no
add: it is skipped, exactly as a screen holding only a calculate is skipped
(§11.1) and for the same reason — otherwise it is a blank screen inflating the
pair in §11.2. An enumerator-driven repeat with no instances yet **MUST NOT** be
skipped: its empty screen is the only door to the first instance, and skipping it
would be §11.1's own defect one level in.

An instance whose every screen is currently irrelevant is still listed. It exists
as data, it has an identity, and its delete control is the only way to be rid of
it.

**Inside an instance.** `next` from an instance screen is the next relevant
screen of the instance plan; from the last, it **leaves the instance**, and the
position becomes the repeat screen. `previous` from an instance screen is the
previous relevant one; from the first, it likewise leaves to the repeat screen.
Neither ever moves to another instance.

Leaving to the list rather than advancing into the next instance is what gives
the "are we finished?" decision a place to happen, and for a roster whose length
only the respondent knows, that decision is the feature. It also lets one rule
serve both count modes: a `countExpr` roster of six and an enumerator-driven
roster of six navigate identically, and differ only in which controls §2.3
permits. A runtime MAY offer an explicit "next instance" control at the end of an
instance — that is `enterInstance` on the following one, the same operation as
choosing it from the list, and not a second meaning for `next`.

**Progress inside an instance is specified here, not left to clients.** An
instance reports two pairs, and an engine computes both:

- **within the instance** — the 1-based position of the current instance screen
  among the instance's currently relevant instance screens, out of that count. As
  in §11.2 the position is 0 while the current screen is not itself relevant.
- **across instances** — the 1-based position of the open instance in the
  repeat's current order, out of the current instance count.

They are specified rather than left to each client for the reason §6.2 gives
about navigation and finalisation: two runtimes that each decide what "3 of 5"
counts will decide differently, the difference will read as a UX detail, and no
conformance vector reaches a client. The engine emits both pairs and the vectors
assert them.

The second pair moves as instances are added, and that is correct. It is the
roster's own count, it changed because the enumerator added a member, and it is
not a claim about how much of the form is left. §11.2's form-level pair is the
one that must not move, and it does not: inside an instance the enumerator has
not left the repeat screen.

**Adding.** `addInstance` (§2.3) is invoked from the repeat screen. On success
the new instance becomes the open one and the position becomes its first relevant
instance screen — or the repeat screen, if it has none. The top-level position
does not change, the plan does not change, and no index is renumbered. A refused
add — the `maxInstances` ceiling, or a `countExpr`-controlled repeat — leaves the
position exactly where it was.

**Deleting.** After a successful `deleteInstance` (§2.3): if the deleted instance
is the one the position is inside, the position becomes the repeat screen.
Otherwise the position is **unchanged**, including its instance screen index.

That follows from a position holding an instance **id** and never an ordinal.
§2.3 already guarantees a delete never renumbers the survivors in storage; a
position holding a list index would move the enumerator into a different person's
answers on somebody else's delete, with every control on the screen still reading
correctly and nothing at all to see. An id cannot do that — it either still
exists or it does not.

A refused delete — the `minInstances` floor, or a `countExpr`-controlled repeat —
leaves the position exactly where it was.

**An instance that ceases to exist.** One rule, whatever the cause: if the
position's instance is no longer in the repeat's order, the position becomes the
repeat screen. That covers a delete, and it covers a `countExpr` shrink
discarding trailing instances (§2.3), which can happen while the enumerator is
inside one of them.

**Zero instances.** A relevant repeat with no instances shows its repeat screen,
empty, with its add control. That is neither a dead end nor a blank screen with
nothing to do: it is the only door to the first instance, and `minInstances: 0`
is a legal roster.

## 12. Open questions for v0.2

- **Nested repeats** — reference resolution, aggregate semantics across levels, and instance lifecycle when a parent instance is deleted
- **The enumerator-driven roster, and screen flow across repeats — answered in
  §11.3, 5 September 2026.** Both entries stood here for the same reason: §11.1
  excluded a repeat from the screen plan, so the engine's instance semantics were
  complete and unreachable, and a form with a roster asked none of its questions
  on any client (`docs/known-defects.md` 14).

  A repeat is one screen holding the instance list; an instance is entered and
  left; the plan stays a pure function of the IR and no instance count enters it.
  The add control's missing label is `addLabel` and the list row's is
  `summaryLabel`, both §2.3. What remains open below is nesting, and nothing
  else about repeats.

- Whether aggregates should exclude non-relevant instances (currently they do not; only null values are ignored)
- Cross-form references for case pre-population
- Server-only expressions and where they are declared
- Encrypted-field addressing — can a constraint reference an encrypted field
- External function/plugin call surface
- **A static type check at publish time.** §4.7 makes evaluation total, which
  is right for a device and moves the reporting of a genuine type error to the
  one place somebody is reading: the publish gate. Nothing checks it there yet,
  so `${text_field} + 1` publishes and evaluates to null forever
- Whether a residual predicate should be expressible as a store-side operation
  (`in`, prefix match) rather than only as equality — §3.2 extracts equality and
  nothing else, so `$row.population > 1000` is a full scan by construction
