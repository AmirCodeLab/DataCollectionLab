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
  "rowSource": <rowSource>,
  "minInstances": 0,
  "maxInstances": 30,
  "addLabel": { "en": "Add another household member" },
  "summaryLabel": { "en": "{0}, age {1}" },
  "summaryLabelArgs": [ <expr>, ... ],
  "children": [ <node>, ... ]
}
```

A repeat **does** create a data scope. Children are addressed as `members[i].name`.

**Where a repeat's rows come from.** Four sources. A repeat names one:

| Source | Declared by | What decides the rows |
|---|---|---|
| An earlier answer | `countExpr` | the answers |
| The enumerator | neither field | the enumerator, as they go |
| The sample | `rowSource`, `kind: "dataset"` | the sample assigned to this case |
| A list in the form | `rowSource`, `kind: "inline"` | the form author |

- If `countExpr` is present the instance count is controlled by it and the user cannot add or remove instances. Growing the count creates empty instances; shrinking it discards the trailing instances and their data.
- If neither field is present, the user controls instance count, bounded by `minInstances` / `maxInstances`. `minInstances` instances are created when the form opens.
- If `rowSource` is present the instances are created from **rows that exist before the interview does** — the sample, or a list written into the form — and the enumerator may add to them or delete from them exactly where `rowSource` permits.
- **Nested repeats are not supported in v0.1.** A repeat inside a repeat is a compile error. Deferred to v0.2 — the reference-resolution and aggregate rules need designing before implementation, and shipping a half-defined version would be worse than refusing it.

`countExpr` says **how many**. `rowSource` says **which**. A repeat carrying both
is a compile error (§10.2): they are two answers to one question and nothing
sensible arbitrates between them.

#### The row source

A fixed list written into the form — the same ten agricultural practices asked
of every household:

```json
"rowSource": {
  "kind": "inline",
  "items": [
    { "value": "zero_till", "label": { "en": "Zero tillage" } },
    { "value": "laser_lvl", "label": { "en": "Laser levelling" } }
  ],
  "bind": { "practice": "value" },
  "allowAdd": false,
  "allowDelete": false
}
```

A roster preloaded from the sample:

```json
"rowSource": {
  "kind": "dataset",
  "dataset": "hh_members",
  "labelColumn": { "en": "name_en", "ur": "name_ur" },
  "filter": { "op": "eq", "args": [
    { "op": "ref", "path": "$row.case_key" },
    { "op": "ref", "path": "_metadata.case_key" } ] },
  "bind": { "member_name": "name_en", "member_age": "age" },
  "allowAdd": true,
  "allowDelete": false
}
```

**This is §3's shape on purpose.** `kind`, `dataset`, `labelColumn`, `filter`
and `items` mean exactly what they mean for a choice list, and a dataset
`rowSource` is resolved by **§3.2 unchanged** — the same selector/residual
decomposition, the same selector ordering, the same performance contract, the
same refusal to let a client pre-narrow. A roster over the sample and a
`select_one` over the sample ask one question of one source. A second
resolution model would be two ways to read one dataset, and §3.2's rules are the
ones the vectors already reach.

Four differences, each because a row is not an option:

- There is no `valueColumn`. A row's identity is the dataset's own key (§3.1),
  taken exactly, with no trimming, folding or normalisation.
- `bind` says which of the row's columns land in which of the instance's
  questions. **An inline row binds `value` and only `value`**: a `label` is §7
  i18n and an answer is one value in no language, so binding one is a compile
  error (§10.2). The label is what the row displays, and what an export resolves
  from the IR — exactly as for a choice list, where the stored answer is the
  value and the label is looked up beside it.
- `allowAdd` and `allowDelete` say what the enumerator may do to the list. Both
  default to `false`.
- `labelColumn` is what a row of the instance list says when `summaryLabel` is
  absent, rather than what an option reads.

**Rows are resolved once.** The instances are created the first time the repeat
is relevant, and the row set is **never re-resolved**. A newer version of the
dataset arriving mid-interview adds no instance and removes none; a row deleted
from the sample does not delete the instance holding a respondent's answers.

**A `rowSource` filter MUST NOT reference an answer.** It may read `_metadata`
(§8) and constants, and nothing else; an answer reference is a compile error
(§10.2). This is what makes "resolved once" a rule rather than a race. A filter
over answers has no defensible timing: resolve it early and it selects on nulls;
resolve it late and an enumerator correcting a household id leaves the previous
household's members sitting in the roster, every control reading correctly and
nothing at all to see. Refusing it is the same decision this section already
makes about nested repeats — a half-defined version is worse than a refusal that
says so.

**Confirmed against the work, 6 September 2026, and no longer a judgement
call.** The shape this refuses does not exist in the fieldwork it was written
about: a roster's rows come from the **case the enumerator selected** from their
assigned sample, and that selection is an assignment rather than an answer. So
the filter reads `_metadata.case_key` and a typed household id was never the
alternative. `docs/phase3-pilot-scope.md` §13, question 6.

**Seeding.** For each row an instance is created, and `bind` writes the named
column's value into the named question of that instance. A seeded value is an
ordinary answer from that moment: it behaves as if it had arrived as the
question's `default` (§2.1), it is editable wherever the question is not
`readOnly`, and it is the value an export carries. Whether a correction to a
seeded value flows back to the sample is a separate question and still open —
`docs/phase3-pilot-scope.md` §13, question 3.

A `bind` naming a question that is not in this repeat's subtree is a compile
error (§10.2). A `bind` naming a column the source does not carry seeds `null`
**and the engine reports the missing column**; silently seeding null would be a
roster of blank names on a device holding the sample, with nothing in an error
state — §3.2's rule about an index that cannot answer, one level up.

**Order.** Instances are created in source order, and instances added afterwards
append, so the creation-order invariant holds unchanged. For an inline source
that order is the document order of `items`, which is in the IR and therefore
settled. For a dataset source it is the order of the rows in the published
version — **which does not survive delivery today**, and is why `kind:
"dataset"` is specified here and not yet implementable. See *What is live*
below and `docs/known-defects.md`.

**Adding and deleting.** `allowAdd` and `allowDelete` are independent, and both
default to `false`.

- `allowAdd: true` — the enumerator may add instances beyond the seeded ones,
  bounded by `maxInstances`, exactly as in an enumerator-driven repeat. **The
  two sources coexist in one roster**, and that is the ordinary case rather than
  an edge: a household's known members come from the sample, and the baby born
  since the sample was drawn does not. They are one list, in one order, entered
  the same way, answering the same instance plan.
- An added instance has no source row. Its `_rowKey` is `null` and `bind` does
  not apply to it.
- `allowDelete: true` — an instance may be deleted, bounded by `minInstances`. A
  deleted preloaded row does not return: rows are resolved once.
- Both `false` is a fixed roster. That the list cannot be edited is the point of
  it: it is what makes the answers comparable across submissions, and an
  enumerator who could delete a practice would produce a household that appears
  not to farm.

`minInstances` has **no effect** on a `rowSource` repeat; the source decides the
initial count. `maxInstances` bounds **adding only**. A source returning more
rows than `maxInstances` instantiates all of them and permits no add —
truncating would drop a sampled household member with nothing in an error state.

**The row's key.** Every instance created from a `rowSource` records the key of
the row that made it — §3.1's key, exactly — reported per instance as `_rowKey`,
and `null` for an enumerator-added instance (`_` is reserved runtime metadata,
§2.4). It is what an export joins back to the sample on, and it is what lets a
supervisor see which sampled members were never interviewed. An instance id is
internal and per submission; `_rowKey` is the identity the sample already had.

**It is not yet an expression reference.** An earlier draft of this section
wrote it as `members[.]._rowKey`, which §4.2 does not grant and no engine
resolves: the engines record and report the key, and nothing evaluates a path to
it. Making it referenceable is a §4.2 row plus resolution in both engines — a
small change, and deliberately not made yet, because what a row *displays* is
still open (`docs/phase3-pilot-scope.md` §5.1) and the answer may put the key in
a bound question instead, where an expression already reaches it. A form that
needs the key in an expression today binds it to a question: `bind` puts it in
the instance, and every §4.2 rule applies to it unchanged.

#### What is live

**`kind: "inline"` is implemented. `kind: "dataset"` is specified and refused.**
An engine MUST refuse a `rowSource` with `kind: "dataset"` as a compile error
(§10.2) until both of the following are true, and the refusal names them:

1. **`_metadata.case_key` exists** (§8). A dataset `rowSource` filter cannot
   reference an answer, so the case is the only thing it has to key on, and
   cases arrive with Phase 3 item 2 (`docs/phase3-pilot-scope.md` §4.3).
2. **A dataset version's row order survives delivery to a device.** It does not
   today: the order is held on the server and is neither carried on the wire nor
   part of a version's content address, so a roster's rows would arrive in an
   order nobody chose. `docs/known-defects.md` has the measurement.

The split is deliberate rather than a staging convenience. Inline alone covers
the fixed-list tables, which are the shape that appears most in RCons's
questionnaires, and it depends on nothing outside this document — the rows are
in the IR. Specifying both now and building one keeps the two sources one
mechanism, which is the claim §11.3 makes about how they render; building the
inline half first is what stops that claim waiting on item 2.

`addLabel` and `summaryLabel` are what a repeat screen renders (§11.3), and both
are optional. `addLabel` names the add control — "Add another household member"
is per-form and per-language, so it belongs on the node and not in a client.
`summaryLabel` is what one row of the instance list says: a §7.1 interpolated
label evaluated **in the instance's scope**, so a bare reference among its
arguments resolves to that instance (§4.2), and every §7.1 rule applies to it
unchanged — null is the empty string, values are bidi-isolated, arguments are
dependencies, and a slot with no argument is a compile error.

**What a row shows, in order.** A runtime takes the first of these that
produces a label:

1. `summaryLabel`, rendered in the instance's scope — **unless it has at least
   one argument and every argument evaluates to `null`**, in which case it
   produces nothing and the next rule applies.
2. The source row's label, for an instance created from a `rowSource`:
   `labelColumn` for a dataset row, `label` for an inline item.
3. The instance's **1-based position in the current order**.

Rule 1's exception is what an *added* instance needs, and it is the whole
reason the chain is written as a chain. An enumerator who adds a household
member has, for the moment between pressing add and typing anything, an
instance that has answered nothing: it has no source row, so rule 2 cannot
help it, and a `summaryLabel` of `"{0} — {1}"` over its empty answers renders
`" — "`. A list of rows reading `" — "` is worse than no label at all, because
two of them are indistinguishable and telling rows apart is the only thing the
list is for. A position number always distinguishes them.

**Every argument null, not an empty rendering.** The test is on the arguments
and not on the string, because the string is the author's and the arguments are
the instance's. `" — "` is what one template happens to produce from nothing;
another produces `""` and a third produces `"()"`, and a runtime that tried to
recognise emptiness would be guessing at punctuation in languages it does not
read. "This instance has answered none of the things its label is made of" is
the same question in every language and both engines can answer it identically.
A `summaryLabel` with **no** arguments is a constant, is the author's deliberate
choice, and falls through to nothing — the chain does not begin.

The label is derived, so it follows the answers: the row that showed `3` shows
`Ali` as soon as a name is entered, on the same recalculation that any other
dependent value moves on.

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

**A composite key is the parts joined with `|`, escaped.** A sample whose row
identity is several columns (RCons's `settlementCode + structureId + hhId`)
is published against a key composed from them, in the order the publisher
names the columns: each part has `\` written as `\\` and `|` written as `\|`,
and the escaped parts are joined with a single `|`. Splitting reads left to
right: a backslash takes the next character literally, an unescaped `|` is a
boundary. The escape is the rule, not the importer's choice, for the reason
the exact-match rule above is: a part is the cell's value exactly, and a value
may contain a pipe. Without the escape `("A|B")` as one column and
`("A", "B")` as two compose to the same key, silently, and an export that
splits the key back gets a different row. Doubling the pipe instead of
escaping it is not enough — `("A|", "B")` and `("A", "|B")` would both read
`A|||B` — which is why the escape character is a backslash and the backslash
escapes itself. Every part is held to the rule above: an empty or
whitespace-only part refuses the row, naming the column. The parts stay as
ordinary columns of the row; the composed key is what `_metadata.case_key`
carries and what a `rowSource` filter compares whole.

Keys that differ from one another *only* by surrounding whitespace or by case
are **reported at publish and not merged**. They are almost always a data
error — the same village entered twice — but merging them would be the platform
deciding that two rows a customer supplied are one, which is not a decision the
platform can make. The report names them; the publisher decides.

**Row order is deliberately not part of a version's identity, and §2.3 now wants
it to be.** `version_checksum` sorts by key before hashing, so that two servers
that inserted the same rows in different orders agree on the content address;
publishing is idempotent by that address, so the same rows re-uploaded in a new
order are not a new version at all. That was the right call while order was a
presentation detail of a choice list. A `rowSource` (§2.3) creates one instance
per row, and the order an enumerator reads a household in is the order the
sample lists it in — so order becomes part of what a version *is*. **This
section does not yet say that**, because saying it would not make it true: the
server holds the order and nothing carries it to a device.
`docs/known-defects.md` has the measurement and the work. The sentence belongs
here when that work lands, and not before.

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
| `_metadata.case_key` | text |

`_metadata.case_key` is the case this submission was opened against — the sample
row it came from (`docs/phase3-pilot-scope.md` §4.3) — and `null` for a
submission opened without one. It is the case behind the **enumerator's
selection from their assigned sample**, which is what RCons confirmed on 6
September 2026 the roster filter actually keys on, and so it comes from item 2's
`assignment` → `case_record` rather than from anything the form collects. A `rowSource` filter is answer-independent by
§2.3, so this is what a roster preloaded from the sample keys on. **It does not
exist yet**: cases arrive with Phase 3 item 2, which is one of the two reasons
§2.3 refuses `kind: "dataset"` for now.

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
a field-list group**, **a repeat carrying both `countExpr` and `rowSource`**, **a
`rowSource` filter that references an answer**, **a `bind` naming a question
outside its repeat**, **an inline `bind` naming `label`**, and **a `rowSource`
with `kind: "dataset"`** while §2.3's two conditions are unmet,
**a statically-unreachable container holding answerable questions**
(§10.3), and **a `note` carrying `required`**.

The four `rowSource` refusals are one reason wearing four hats: each is a form
that would run, and run differently on two engines or on two days. Two row
sources have no arbiter; an answer-dependent filter has no defensible resolution
time (§2.3); a bind reaching outside its repeat would write one row's value into
a field that is not per-row; a bind onto a label would have to pick a language,
and two engines picking one is two forms. In each case the alternative is not a
worse behaviour but an undefined one.

**`kind: "dataset"` is refused for a different reason and the message must say
so.** It is not malformed and it is not ambiguous — it is specified, and two
things it depends on do not exist (§2.3, *What is live*). A form author who
wrote a valid preloaded roster needs to read that it is not built yet, not that
their form is wrong. This refusal is expected to be deleted, and the two others
are not.

A **repeat inside a `field-list` group** is refused because the two say
contradictory things about the same questions, not because we are choosing
between two workable behaviours. `appearance: "field-list"` means *these
questions appear together on one screen*; a `repeat` means *this is a separate
screen you enter and leave* (§11.3). Both cannot be true of the same subtree, so
the refusal states what is already the case rather than picking a side. The
alternative — dropping the repeat's questions from the field-list screen — is
the silent-omission defect §11.1 exists to close, reappearing in a corner nobody
would look in.

A **`note` carrying `required`** is refused because §2.1 gives a note no value
and nothing can give it one. `required` is the only property that turns that
absence into a fault: the field is permanently blocking under §6.2, so the
submission can never be finalised, and §6.2's `firstBlockingScreen` sends the
enumerator to a screen holding a sentence and nothing to answer. The refusal is
of `required` **present at all**, not of `required` evaluating true: a
statically-false one is merely pointless, and distinguishing the two would leave
an author one edit away from a form that cannot be finished.

This is deliberately narrow. A `constraint` or a `readOnly` on a note is equally
meaningless and is **not** refused — a constraint over null coerces true
(§4.4.7) and a readOnly over null coerces false, so both are inert. Only
`required` changes what the form does, which is what earns it a rule. Nothing
else in §2.1 has no value, so nothing else is reached by this.

It is a property of the **document**, true wherever the document is read, which
is why both engines implement it and `conformance/answerability` compares them.
An author writes it by accident: the first questionnaire large enough to contain
a note carried `required` on it and published, and nothing between the workbook
and the handset said a word (`docs/known-defects.md` 31).

A **sensitivity leak** is any expression that reads a `sensitive` field from
somewhere that does not itself carry the same protection. Two shapes:

- **A field** that is not `sensitive` and whose `calculate`, `relevant`,
  `constraint`, `required`, `readOnly`, `default`, `labelArgs` or
  `constraintMessageArgs` reads a field that is. The fix is to mark the reading
  field `sensitive` too, never to unmark the source.
- **A repeat's own expressions** — `countExpr` and `summaryLabelArgs` — reading
  a sensitive field. There is nothing to mark here: a repeat is a scope, not a
  field, and carries no `sensitive` flag. The fix is to stop reading it.

`labelArgs` and `constraintMessageArgs` were always checked — an interpolation
argument is a dependency (§7.1), so it was in the graph — but this paragraph
did not say so, and a definition that omits half of what it defines is how
`summaryLabelArgs` came to sit outside the check for as long as it did. The derived value discloses its input, so publishing it would defeat
`field_level` encryption (Encryption Envelope §5.2). The fix is to mark the
reading field sensitive too, never to unmark the source. This is checked over
the same dependency graph §5.1 builds, so it is exact rather than heuristic, and
it blocks publish in every security mode.

### 10.3 Warnings

**A template slot with no argument behind it.** `{0}` in a `label`,
`constraintMessage` or `summaryLabel` with no corresponding entry in the
matching `…Args` is legal — §7.1 says a document with no arguments is
substituted not at all — and it reaches a respondent as the three characters
`{0}`. §7.1 argues that visible brace is a feature, and it is: of a *renderer*
that ignores the arguments. It is not a feature of an author who forgot them,
and nothing told them apart. So it is a warning rather than an error, because
the spec permits the document.

Reported once per node rather than once per language: an author writes the slot
once and translates around it, so three languages naming the same missing
argument is three copies of one problem. `conformance/reachability-007` pins it
on both engines.

Allow publish: missing translation, decimal equality comparison, unreachable
relevance (statically false), repeat with no bound, unused calculate.

**Statically false** means decidable without answers and without a clock: the
expression holds no `ref`, no `today()` and no `now()`, and evaluating it by
§4.7 yields `false`. An expression that reads an answer is not statically false
however plainly it fails. Deciding *that* would be a data-flow analysis, and two
engines performing one independently is two definitions of which forms publish.

#### An unreachable container holding questions is an error, not a warning

A `group` or `repeat` whose `relevant` is statically false, and whose subtree
holds at least one `question` that is not a `calculate`, is a **semantic error**
(§10.2). It blocks publish. A statically-false `relevant` on a question is a
warning, as above.

**A repeat that can never hold an instance is unreachable in the same sense**,
and the same rule applies to it. Three shapes are statically decidable, and
each is one of §2.3's four row sources with its door shut:

- `countExpr` that is static — no `ref`, no `today()`, no `now()` — and
  evaluates by §4.7 to a number that is not greater than zero;
- `maxInstances: 0`;
- an inline `rowSource` with no `items` and `allowAdd` false (or absent).

The engine is right to yield no instance for each (`_can_add`, §11.3), which
is exactly why the document must not ship: the questions inside survive
import, list in a builder's tree, and reach no screen on any path.

A container that holds **no** answerable question is not this case. An empty
`field-list` group, or a group of calculates, loses nothing by never
appearing, so it is neither an error nor a warning; a form with such a
container publishes clean. Nested unreachable containers are reported once,
by the outermost.

The refusal names the container, the reason, and the questions that would be
lost; the warning names the question. Both engines produce the same text —
`conformance/reachability` pins it — because an author reads it, and a form
one builder refuses with one sentence and another with a different one is two
rules.

The engine's finding is identical in the two cases — this node can never appear
— so what separates them is the author's intent, and on that they are not close.

**A leaf stays a warning because staging is real work.** An author writes a
question, is not ready to ask it, gives it `false()` and returns to it next
version. That is deliberate, it is visible in the single place it applies, and
refusing it would put this specification in the way of a normal way of working.

**Questions inside a container that can never appear are not that.** Nobody
writes questions in order to guarantee they are never asked. The form then
collects less than it reads as collecting: the questions are in the document,
they survive import, they list in a builder's question tree and in any review of
what the form asks — and they reach no screen on any path through any interview
(§11.1). Whoever reads the form to learn what it collects gets the wrong answer,
and the collected data cannot afterwards distinguish a question nobody answered
from a question nobody was asked.

That is a document which must not ship, which is what §10.2 is for.

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

**Four sources of rows, one screen.** §2.3 gives a repeat's rows four possible
origins: a `countExpr` over the answers, the enumerator adding them as they go,
the sample by way of a dataset `rowSource`, and a fixed list written into the
form. **They render identically.** One repeat screen listing the rows in their
current order, a way into each, and the enumerator enters a row to answer that
roster's section. The source decides where rows come from. It decides nothing
about how they look.

What it does decide is which controls the screen carries, and §2.3 has already
said so: an add control where adding is permitted, a delete control on each
instance where deleting is. A fixed list of ten agricultural practices shows ten
rows and neither control. A household roster preloaded from the sample shows the
sampled members **and an add control**, because `allowAdd` is true and the two
sources coexist in one roster: the members the sample knows about are listed,
the one born since is added on that same screen, into that same list, and both
answer the same instance plan. Nothing on the screen distinguishes them, and
nothing should — the enumerator is interviewing a household, not auditing where
its member list came from.

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

Those two conditions decide all four sources without gaining a clause, which is
the test of whether they were the right two. A fixed list has instances, so its
screen is relevant. A preloaded roster whose filter matched no row and whose
`allowAdd` is false offers neither an instance nor an add, so it is skipped —
the same outcome as a `countExpr` currently sized zero, for the same reason, and
it is why the second condition was written as *something to offer* rather than
as *any instances*. A preloaded roster that matched no rows but permits an add
is shown empty, exactly as an enumerator-driven roster at zero is shown.

An instance whose every screen is currently irrelevant is still listed. It exists
as data, it has an identity, and its delete control is the only way to be rid of
it.

**And the plan does not move.** A `rowSource` puts instances where a `countExpr`
or an enumerator would have put them, and an instance count has never been in
the screen plan. The count now arrives from the sample, which means it is
unknown at compile time in one more way than before — and the constraint at the
head of this section holds for exactly that reason rather than in spite of it.

**Inside an instance.** `next` from an instance screen is the next relevant
screen of the instance plan; from the last, it **leaves the instance**, and the
position becomes the repeat screen. `previous` from an instance screen is the
previous relevant one; from the first, it likewise leaves to the repeat screen.
Neither ever moves to another instance.

Leaving to the list rather than advancing into the next instance is what gives
the "are we finished?" decision a place to happen, and for a roster whose length
only the respondent knows, that decision is the feature. It also lets one rule
serve both count modes: a `countExpr` roster of six, an enumerator-driven roster
of six and a roster of six preloaded from the sample navigate identically, and
differ only in which controls §2.3 permits. A runtime MAY offer an explicit "next instance" control at the end of an
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

  **Extended 6 September 2026.** A roster's rows may also come from the sample
  or from a fixed list in the form — §2.3's `rowSource`, rendered by §11.3 as
  the same one screen, because the source decides where rows come from and not
  how they look. The inline half is built; the dataset half is specified and
  refused until `_metadata.case_key` exists and a dataset version's row order
  survives delivery. That narrows *cross-form references for case
  pre-population* below rather than answering it: pre-population from a
  **dataset** is specified, from another form's **submission** is not.

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

---

## Appendix A — Expression surface syntax (non-normative)

**This appendix is not normative and defines nothing about what a form means.**
§4 is the definition: an expression is a typed AST, and "expressions are a typed
AST, never XPath" is a locked decision. This appendix describes a *surface* —
what a builder's code field shows an author and reads back — for exactly one
document, so that an author who needs something the visual editor cannot express
has somewhere to type it.

**It is not a conformance surface, and that is worth saying plainly**, because
"a new grammar" reads like a `conformance/functions` obligation and is not one.
Both engines consume AST. Neither parses text, and neither ever will — the IR
that reaches a handset has no strings in it. There is nothing here for a vector
to compare between two implementations, because only one implementation exists
by construction: `app/modules/forms/expression_text.py`, server-side, behind
`POST /forms/expressions`.

What replaces a vector is a **round trip**: `parse(render(node)) == node` for
every expression node, asserted over every expression in the conformance corpus
rather than over examples chosen by hand.

### A.1 It is XLSForm's XPath, extended

The syntax is the one the importer already reads, because a second parser is a
second thing that decides what an expression means. It is extended only where
§4.3 has a function XLSForm cannot spell.

| | |
|---|---|
| Reference | `${field_name}`; a bare name **only** inside a choice filter, where it is a column of the candidate row (§3.2) |
| Literals | `12`, `1.5`, `'text'`, `"text"`, `true()`, `false()`, `null()` |
| Comparison | `=` (or `==`), `!=`, `<`, `<=`, `>`, `>=` |
| Boolean | `and`, `or`, `not(x)` |
| Arithmetic | `+`, `-`, `*`, `div`, `mod`, `idiv`, unary `-` |
| Conditional | `if(test, then, else)` |
| Membership | `selected(list, value)` |
| Functions | every §4.3 function, under its **IR name** — `dec`, `str`, `len` — and under its XPath name where XLSForm has one: `number`, `string`, `string-length` |

**Precedence, loosest first:** `or`, `and`, comparison, then `+ - div mod idiv`
together, then `*`, then unary `-`, then primaries. `div` sitting with `+` rather
than with `*` is XPath's ladder and not a mistake: `${a} + ${b} div 2` is
`(${a} + ${b}) div 2`.

### A.2 What has no surface, and says so

Two nodes are reachable in the IR and cannot be written as text. The renderer
refuses them by name rather than inventing a spelling, and a code field reports
that the expression must be edited as IR.

- **`in`** — XLSForm has no such operator, so an author cannot have typed one.
  `selected` covers the same ground for the cases a builder produces.
- **The `null` function** — `null()` is the surface for the null *literal*, and
  giving one surface two ASTs would make the round trip pick the wrong one half
  the time.

A string containing both `'` and `"` also has no surface form: the tokenizer has
no escape sequence, so there is nothing to read back.

### A.3 Errors carry an offset

A failure names the character it is about, so a code field can put a caret under
it: the trailing token, the unknown character, the opening quote or brace that
was never closed, the name of the function that does not exist or took the wrong
number of arguments, or the end of the text where it stopped too soon. `null`
only where the failure is about the whole expression rather than a point in it,
and the empty expression is the one case.

The importer does not use offsets and is right not to: it reports against a
spreadsheet cell, and `survey!H27` is the location its author is looking at. A
code field's author is looking at the expression itself, where "somewhere in
this string" is not a location.

### A.4 A number is written as exactly itself, and this is not `str()`

A number literal is rendered as the shortest digits that read back as
**exactly the same value**, and never fewer. `0.30000000000000004` is written
with all seventeen digits. `800.0` is written `800.0`, with the `.0` that makes
it a decimal rather than an integer. The digits are positional, because the
grammar has no exponent: `1e-07` is `0.0000001`, and `1e16` is
`10000000000000000.0`.

**This is not §4.3.1's `str()`, and the two must not be confused.** They are
two renderings for two purposes. `str()` is for a human reading a label: it
drops the `.0` from an integer-valued decimal so that `str(dec("800"))` is
`"800"` and can match a text column, and §7.1 interpolates with it for the same
reason. The code field is canonical text an author edits and **saves back**, and
it has one job: the value that goes out is the value that comes in. If the
editor showed `0.3` where the AST held `0.30000000000000004` and saved `0.3`,
then `${x} = 0.3` against an answer computed as `0.1 + 0.2` has gone from true
to false, and nothing said so. A rendering that is allowed to lose a digit is
not a rendering of the expression; it is a different expression that looks like
it.

**The integer/decimal spelling is kept here and is harmless to lose
elsewhere.** Both engines compare `800` and `800.0` equal under §4.7, and §4.3's
integer-typed arguments accept a whole-valued decimal, so nothing at runtime
can tell the two apart — deliberately, because an answer must not depend on how
a number was arrived at. A browser's JSON reads `800.0` and writes `800`, and
that is why the harmlessness matters: a draft that passes through the console
keeps every value and may lose that one spelling. The printer keeps it anyway.
Its job is exactness, not a judgement about what is safe to drop, and the
round-trip test compares with a type-aware equality for the same reason —
`{"value": 800.0} == {"value": 800}` is true in Python, so `==` could not see
the difference (break 119).

**A negative number has no literal of its own.** The tokenizer reads a sign as
unary `-`, so `-5` reads back as `neg` over the positive literal — which is
what the importer has always produced for `-5` in a spreadsheet cell. An IR
node `{"op": "lit", "value": -5}` therefore round-trips to
`{"op": "neg", "args": [{"op": "lit", "value": 5}]}`: the one node whose round
trip keeps the value and not the shape. §4.4 evaluates the two identically, and
a builder that produces AST directly writes a negative number the same way, so
that one number has one AST whichever rendering wrote it.

Values JSON cannot carry — infinities, NaN — have no surface form, and the
renderer says so rather than writing `inf`.

`tests/test_expression_text.py` pins each of these, and runs the rule as a
property over generated numbers — random bit patterns, both ends of the
64-bit integer range, the float mantissa boundary, the subnormals — because a
list of cases somebody thought of is what the printer had when it looked
correct. Breaks 118 and 119.

### A.5 The grammar

The parser is `app/modules/forms/xlsform/expressions.py`, recursive descent
over a small ladder, and this is that ladder written down. Where this text and
the parser disagree, the parser is what the code field does and this text is
the bug — the point of writing it is that behaviour with no spec is how the two
engines came to diverge on casts (§4.3.1, break 44), and a parser that is the
only definition of its own grammar is that shape again.

```
expression     := or
or             := and ( "or" and )*                    one n-ary `or` node
and            := comparison ( "and" comparison )*     one n-ary `and` node
comparison     := additive ( cmp additive )?           at most one; a chain is an error
cmp            := "=" | "==" | "!=" | "<" | "<=" | ">" | ">="
additive       := multiplicative ( ( "+" | "-" | "div" | "mod" | "idiv" ) multiplicative )*
multiplicative := unary ( "*" unary )*
unary          := "-" unary | primary
primary        := number | string | reference | "." | "(" expression ")" | call | name
call           := name "(" ( expression ( "," expression )* )? ")"
```

#### Tokens

- **Whitespace** between tokens is ignored and never significant. Leading and
  trailing whitespace is stripped before an offset is counted (A.3). A word
  operator needs whitespace where a name or number follows it, as in any
  grammar: `${a} andnot(${b})` is one name.
- **Reference**: `${` *path* `}`. The path is everything up to the closing
  brace, with surrounding whitespace trimmed, and the parser does not look
  inside it — §4.2 resolves it at compile time. Every §4.2 form is written as
  it is in the IR: `${members[0].name}`, `${members[].income}`,
  `${_metadata.start_time}`. The one path that is *not* written this way is a
  candidate row's column, which is a bare name inside a choice filter (below)
  and has no other spelling: `$row.code` as text is an unexpected character.
- **`.`** on its own is the current question, and only where there is one — a
  constraint, where the caller supplies the path. Anywhere else it is an
  error. It is a different token from the `.` inside `1.5`.
- **String**: opened by a straight `'` or `"`, or a curly `‘` `’` `“` `”`, and
  closed by the next character of the same kind — `'` by `'`, `"` by `"`, a
  curly single by either curly single, a curly double likewise. There is no
  escape sequence, so a string may contain any other kind of quote and cannot
  contain its own. The curly forms are read because Excel writes them (seven in
  one real form); canonical text is straight, single unless the value holds a
  single, and a value holding both straight kinds has no surface form (A.2).
- **Number**: digits with an optional fraction, or a fraction alone: `12`,
  `1.5`, `.5`. No sign — `-5` is unary minus over `5` (A.4) — no exponent, no
  separators. A `.` decides integer from decimal. Canonical text is A.4's.
- **Name**: a letter or `_`, then letters, digits, `_`, `.` or `-`. The hyphen
  is there because XPath spells functions `count-selected` and
  `string-length`, and it has a consequence: in a choice filter, `code-1` is
  the column named `code-1`, and subtraction needs the spaces. A name followed
  by `(` is a call. A bare name anywhere else is an error — XLSForm writes a
  reference as `${name}`, and a bare name is the mistake worth reporting rather
  than the reference worth inventing — except inside a choice filter, the one
  place XLSForm gives it a meaning, where it is a column of the candidate row
  and the IR spells it `$row.` *name* (§3.2).
- **Operators**: `+ - * = == != < <= > >= ( ) ,`. `=` and `==` are the same
  comparison; canonical text is `=`. Anything else — `/`, `!` alone, `{`, `$`
  outside `${` — is an unexpected character, with its offset.

Keywords and function names are **case-insensitive**: `AND`, `Div`, `ROUND(`,
`TRUE()` all read. Canonical text is lower case.

#### Precedence and associativity

Loosest first: `or`, `and`, comparison, then `+ - div mod idiv` together, then
`*`, then unary `-`, then primaries. `div` beside `+` rather than beside `*` is
XPath's ladder, which the importer implements and real forms rely on:
`${a} + ${b} div 2` is `(${a} + ${b}) div 2`, and `1 + 2 * 3 div 4` is
`(1 + (2 * 3)) div 4`.

`+ - div mod idiv` and `*` are left-associative. Comparison is **not**
associative: `${a} = ${b} = ${c}` is an error at the second `=`, not a chain,
because there is no reading of it that an author meant. `and` and `or` chains
are **one n-ary node** (§4.1), not a nest, because §4.4's null rules are
defined over the whole operand list; parentheses make a nest, and a nest is a
different expression. Unary `-` repeats: `--5` is `neg(neg(5))`.

Canonical text parenthesises only where the tree requires it, so the text an
author typed is not what they see on the next open: `((${a}))` is saved as the
reference and shown as `${a}`. That is §2's rule 3 in the builder scope —
leaving the code field re-parses, and the AST is what is saved.

#### Calls, and what the parser does not check

`not`, `selected` and `if` are operators in the IR, not functions, and the
parser checks their arity — one, two and three — because there is nothing
downstream that would. `true()`, `false()` and `null()` are the literals. Every
other name is looked up: XPath's spellings map onto §4.3's names (`number` is
`dec`, `string-length` is `len`, `count-selected` is `count_selected`), and
§4.3's own names are accepted as they are, so the printer's output reads back.
A name that is neither is an error naming the function.

The parser checks nothing else. A §4.3 function's arity — `substr(${a}, 1, 2,
3)` parses — its argument types, and whether a reference resolves are all
**compile's** to refuse (§10.2), over the whole document, where the answer
exists. The code field's parse answers "is this text an expression"; compile
answers "is it this form's expression". A builder that checked the second in
the first would be form logic in the console, which §2.1 of the scope forbids.

`idiv` has no XPath spelling and exists only in the builder's surface; the
importer keeps refusing it, as it refuses `is_null()`, because an XLSForm
author who wrote one has written something XLSForm does not have.

`tests/test_expression_text.py` holds one test per claim above — a parse and a
canonical text for each, and an offset for each refusal — beside a property
that an author's text (redundant parentheses, arbitrary whitespace, `==`, mixed
case, curly quotes) reads as the same tree the printer's text does. Breaks 120
and 121.
