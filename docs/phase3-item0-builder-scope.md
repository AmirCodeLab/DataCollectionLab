# Item 0 — the visual form builder: proposal

> **PARTIAL RECOVERY.** The original analysis was lost when the session context
> was cleared on 6 September 2026. The text below is what survived in the
> conversation where it was shared, reproduced verbatim.
>
> **Present:** §0, §0.1–§0.4, §1, §2, the §2.2 additions, "The Wasm problem",
> "What is genuinely new work", the build order, and the three closing
> questions.
>
> **Absent:** the remainder of §3 (truncated mid badge-table), and §4, §5 and
> §6 entirely. Those sections are written after the loss, in a separate commit,
> and are labelled as such.

---

> **VERIFICATION, ADDED AFTER THE FACT.** The recovered text landed unchecked,
> deliberately — verbatim first, so that nothing was quietly edited to match a
> later run. It was then verified on 6 September 2026 and **everything
> reproduced**:
>
> - §0.2's six probes reproduce exactly, line for line, including `askable`,
>   `live` and the empty `warnings`. Re-runnable:
>   `python scripts/probe_publishable_empty_containers.py`.
> - §0.1's three line references are exact: `service.py:85` is
>   `def check_publishable`, `service.py:363` is the `if import_record is not
>   None:` guard, and `importer.py:1876` is the reachability block. The four
>   checks §0.1 names are the only four: compile, form-has-no-questions,
>   forbidden RE2 patterns, sensitivity propagation. No reachability check.
> - §0.3's warning count is right — `runtime.py:349` and `:354`, two warnings,
>   and the same two on the Kotlin side. Now known defect 17.
>
> Nothing needed correcting, so nothing was corrected. The original probe
> script was lost with the analysis; the one in `scripts/` was rewritten from
> the recorded output and matches it.

---

## 0. The mistake that passes every test

Your guess is right in shape. It is not right about where the hole is, and the
actual hole is worse than the one you named, because the guard written to catch
defect 14 exists, is correct, and is on the wrong side of the boundary the
builder crosses.

### 0.1 The reachability guard never runs for the builder

§2.3 says publishing goes through the same path as import. That is honoured as
far as the endpoint: `POST /forms/versions` → `service.publish_version` →
`check_publishable`. But `check_publishable`
(`backend/app/modules/forms/service.py:85`) runs exactly four checks: compile
(§10.1/§10.2), form-has-no-questions, forbidden RE2 patterns, sensitivity
propagation.

The reachability refusal — `questions_cannot_be_asked`, the one written for
defect 14 — is not in it. It lives in
`backend/app/modules/forms/xlsform/importer.py:1876`. So does the
collectable-dataType refusal. Both reach `publish_version` only as
`import_record.diagnostics`, and that block is guarded:

```python
if import_record is not None:                    # service.py:363
    blocking = [d for d in import_record.diagnostics if d.severity == "error"]
```

The comment above it says "Omitting the import record is not a way round it. It
is a claim that this version was not imported." For the builder that claim is
true. There is no workbook, so there is no import record, so the strongest half
of the publish gate is not bypassed — it is structurally unreachable. The
builder shares the endpoint and gets a weaker gate, and nothing anywhere says
so.

This is the repository's own recurring lesson arriving through the door §2.3
held shut. §2.3 prevented a second route into `form_version`. The checks that
matter were never in the route.

### 0.2 And the guard would not catch the builder's actual failure anyway

Reachability is a static question — is this question on some screen. Emptiness
is a runtime one — will that screen ever be shown. I probed six shapes against
the Python reference:

```
empty inline roster, no add          PUBLISHES  askable=['a1','q1']  live=['q1']  warnings=[]
countExpr = 0                        PUBLISHES  askable=['a2','q2']  live=['q2']  warnings=[]
statically false relevant (group)    PUBLISHES  askable=['a3','q3']  live=['q3']  warnings=[]
statically false relevant (question) PUBLISHES  askable=['a4','q4']  live=['q4']  warnings=[]
empty field-list group               PUBLISHES  askable=['q5']       live=['q5']  warnings=[]
maxInstances 0, enumerator repeat    PUBLISHES  askable=['a6','q6']  live=['q6']  warnings=[]
```

Every one compiles, publishes clean, and is reported askable by
`askable_question_ids()` — so even if the importer's guard were moved onto the
publish path unchanged, it would pass all six. `screen_relevant` then returns
`False` for the container at runtime and the questions are never asked. That is
defect 14's symptom exactly: deploys, reaches a handset, asks nothing, nothing
on screen looks wrong.

The engine is right about all six. `_can_add` and `screen_relevant`
(`screens.py:165-200`) implement §2.3 and §11.3 correctly, and
`rows-010`/`rows-011` pin the empty-fixed-list case deliberately. The engine is
not the problem. Nothing between the author and the phone asks whether a
container can ever be non-empty.

Two of the six are shapes an XLSForm author essentially cannot write and a
builder author will write by accident on their first afternoon: an empty inline
roster (create the repeat, don't add rows yet, publish) and a statically-false
relevance (build the condition against a question you later delete or rename).
The importer never had to care. A UI makes them the default state of a
half-finished form.

### 0.3 Also: §10.3 promises a warning that does not exist

§10.3 lists five warnings. `runtime.py:349-355` emits two — missing translation,
decimal equality. "Unreachable relevance (statically false)", "repeat with no
bound" and "unused calculate" are not implemented, which is why `warnings=[]`
above. The one warning that would have flagged three of the six shapes is the
one the spec names and the engine does not raise.

### 0.4 What I propose doing about it, before any editor is built

Three changes, in this order, all below the builder:

1. **Move reachability into `check_publishable`.** It is a pure function of the
   IR (`build_screen_plan(...).askable_question_ids()` against
   `_answerable_nodes`); it is in the importer only because that is where it was
   needed first. Once there, every caller gets it — importer, builder, seed
   script, CLI — and the importer's own diagnostic becomes a nicer early report
   of a refusal the server now makes on its own.

2. **Add a liveness check to `check_publishable`**, for the statically decidable
   subset: a container holding answerable questions that provably yields no
   instance and no screen — literal-false `relevant`, `countExpr` that is a
   literal ≤ 0, `maxInstances: 0`, an inline `rowSource` with no items and
   `allowAdd: false`, a field-list group with no answerable children. Same
   message shape as `questions_cannot_be_asked` and for the same reason: these
   questions would be silently skipped in the field.

3. **Decide error vs warning, in a spec commit of its own.** My recommendation,
   and it is a recommendation rather than a reading of §10.3: a statically-empty
   container holding answerable questions is an error — it is defect 14's
   symptom and the author cannot have meant it — while a statically-false
   `relevant` on a leaf question stays the §10.3 warning, because an author
   staging work legitimately writes one. That distinction is not in §10.3 today
   and needs to be, or the check has no rule to implement.

Each needs a matched pair — Python and Kotlin — and a row in
`docs/known-breaks.md`, because this is above the vector line (it decides which
document publishes, not what one evaluates to) and §10.2's untested half already
carries that exposure.

None of this is builder work. It is the floor the builder stands on, and if it
is built after the editor it will be built against forms people have already
published.

> **Done 7 September 2026, after the editor** — the order this section
> warned against, and by one day. All three: reachability and liveness in
> `check_publishable` (`app/modules/form_engine/reachability.py`, matched by
> `Reachability.kt`), the error/warning split in §10.3 with the three repeat
> shapes added in a spec commit of its own, and the six shapes above as
> `conformance/reachability` 001–006 verbatim. Four of the six are refused,
> the leaf publishes with the §10.3 warning, the empty field-list publishes
> clean. `POST /forms/compile` returns the finding structured as `neverShown`,
> which is the tree's "never shown" badge in §3's table. Between the editor
> merging and this landing, nothing was published through it.

---

## 1. What v1 can express, and what it deliberately cannot

### Can

| Surface | Notes |
|---|---|
| Form header | `formId`, `version`, `title`, `languages`, `defaultLanguage` |
| Question types | Driven from `specs/collectable-types-v0.1.json`, never a hand-written list in the console |
| Structure | `group`, `group` + `field-list`, reorder (dnd-kit is already a dependency) |
| Per-question | `label`, `hint`, `required`, `readOnly`, `relevant`, `constraint`, `constraintMessage`, `severity`, `calculate`, `default`, `appearance`, `sensitive` |
| Choices | inline `items`; dataset-backed (`dataset`, `valueColumn`, `labelColumn`, `filter`) — both are in `choiceSources` |
| Repeats | enumerator-driven, `countExpr`, `rowSource` `kind: "inline"`, `min`/`maxInstances`, `allowAdd`/`allowDelete` |

**The type palette must be served, not copied.**
`specs/collectable-types-v0.1.json` exists precisely to stop two hand-maintained
copies drifting, and its own header names `SUBMISSION_STATUSES` as the case this
repository already paid for. The console gets `uncollectableTypes` today as a
count map on the import response and nothing else — it has no access to the
list. That is a small backend addition and it is load-bearing: the day `time`
ships, the palette must gain it without a console change.

### Cannot, deliberately

| Not in v1 | What the author is told |
|---|---|
| The 10 non-collectable dataTypes | Shown, disabled, carrying the registry's own notes string for that type |
| `rowSource` `kind: "dataset"` | Shown, disabled, carrying the engine's refusal message verbatim — see §5 |
| Nested repeats | The tree editor refuses the drop; the compile error is the backstop, not the message |
| Branching / draft-of-draft versioning | One draft per form, publish creates the next version |
| `pulldata`, `count_selected`, nested and/or in the visual editor | The code hatch — see §2 |

### The floor

The IR is JSON and the API accepts it, so the escape must be first-class and
visible, not a hidden power-user route:

- **View / download IR** on every form, always.
- **Paste / upload IR** as a way in, hitting `POST /forms/compile` first so a
  bad document is refused with §10.1's own reason.
- **XLSForm import** stays the second way in and is unchanged.

An author who needs something the builder cannot express downloads the IR, edits
it, and uploads it. The builder must then not silently rewrite what it does not
understand on reopen — which is the same rule as §2's round trip and is stated
once here for the whole document: **the builder is an editor of a document it
did not necessarily write.**

### One gap that has no home yet

There is no draft storage. `form_version` is immutable and published; there is
no `form_draft` table in `001_initial.sql` and nothing else holds unpublished
IR. The builder needs somewhere to keep a form that is not published — browser
storage loses work and cannot be handed to a colleague.

Proposal: a `form_draft` table holding IR, author, timestamp. It must be stated
plainly in the migration comment that a draft never becomes a version except
through `POST /forms/versions` — because a draft table sitting next to
`form_version` is exactly what §2.3 warns about, and the next person in a hurry
will see a shortcut.

---

## 2. The relevance and constraint editor

### The thing that makes this different from every editor that breaks

§4.1: "Expressions are a typed AST, never strings." In XLSForm and SurveyCTO the
canonical form is a string, the visual editor is a lossy parse of it, and the
round trip is where they break — because reopening means re-parsing text
somebody may have hand-formatted.

Here the canonical form is the AST. So:

> The visual editor and the code field are two renderings of one AST. Neither is
> a format, and nothing is ever converted between them.

That single decision removes the failure mode you named. Concretely:

- **Opening an expression never rewrites it.** The editor decides which
  rendering to show and shows it. If the author touches nothing, the AST that is
  saved is byte-identical to the AST that was loaded.
- **There is no "convert to visual" button.** A button that rewrites an author's
  expression into a shape the builder prefers is the whole bug.

### What the visual side covers

A single-level conjunction or disjunction (all-and or all-or, matching §4.1's
n-ary nodes) of terms of these shapes:

- `<ref> <cmp> <lit>` and `<ref> <cmp> <ref>` for `eq` `ne` `lt` `lte` `gt` `gte`
- `selected(<ref>, <lit>)` and `in`
- `is_null(<ref>)` / `is_not_null(<ref>)`
- `not(<one of the above>)`

### The round trip, precisely

Four rules, and they are the whole contract:

1. **Load never mutates.** The AST is held as the source of truth. The visual
   controls are a projection of it.
2. **A visual edit rebuilds only the term it touched.** Editing the right-hand
   value of conjunct 2 replaces conjunct 2. The other conjuncts are the same
   objects they were loaded as.
3. **Leaving the code field re-parses; leaving it unchanged does not.** If the
   text is untouched, the AST is untouched — no parse, no print, no
   normalisation.
4. **The visual editor never round-trips through text.** It emits AST directly.
   Text is only ever involved when the author is looking at text.

Rule 4 is the one that matters. `a and b and c` flattening to one n-ary node,
parenthesisation, associativity — none of it can lose anything, because the
visual path never produces or consumes a string.

### The one real cost, and it is not small

The IR has no surface syntax for expressions. §4.1 is JSON. The code field needs
a grammar, a parser and a pretty-printer, and neither exists.

> Two of the three did, it turned out: the XLSForm importer's XPath parser is
> the parser, and step 5 added the printer and the appendix around it (Form IR
> Appendix A). The recommendation below stands as written and is what shipped.

**Recommendation:** one implementation, server-side, behind an endpoint
(`POST /forms/expressions` → AST, or an error with an offset and the reason).
Reasons:

- §2.1 says no form logic in the builder. A TypeScript parser in the console is
  form logic in the builder.
- The XLSForm importer already compiles XPath to AST in Python. A second parser
  in another language is the shape this repository keeps paying for.
- It does not need to be a conformance surface. Both engines consume AST and
  neither would parse the text, so there is nothing for a vector to compare.
  That is worth stating in the spec commit, because "a new grammar" reads like a
  `functions/` obligation and is not one.

Cost: validation is on debounce/blur rather than per keystroke. Acceptable — the
console is online-only and this is authoring, not collection.

The grammar itself must be written into `specs/form-ir-v0.1.md` as a
non-normative appendix — a surface for one document, not a second definition of
it.

### One thing §4.5 already asks the builder to do

> "The builder warns on direct equality comparison of decimals."

That warning exists in the engine (`runtime.py:352`) and comes back on
`POST /forms/compile`. The builder renders it; it does not compute it. Same for
every other warning — which brings up the rule in §5.

### The reference picker

Three decisions, made before any picker is written, because each is the kind a
picker makes silently otherwise. They apply to **both** renderings — the visual
editor's reference and value controls and the code field's completion — since
a rule that held in one and not the other would make the two renderings
disagree about the same AST.

**1. A number is shown with every digit.** The code field shows a number as
Appendix A.4 renders it, and the visual editor's value control shows the same
text: `0.30000000000000004`, not `0.3`; `800.0`, not `800`. This is
deliberately *not* what `str()` shows in a label (§4.3.1) — that rendering is
for reading, this one is for saving back, and a control that showed a rounded
value and saved it would change the form's behaviour with nothing to say so.
A.4 says why at length.

**2. Sensitive fields are shown, with a badge.** The editor does not decide
what an author may write; `check_publishable` does (§10.2, the sensitivity
leak), it already works, over the dependency graph, in every security mode. So
the picker offers every `sensitive` field, in both renderings, marked at the
point of choosing — the author learns at pick time rather than at publish time,
and a field that legitimately reads a sensitive one (because it is sensitive
itself) is as easy to write as any other. The badge is the whole feature. There
is no refusal and no second warning; a duplicate of the publish check, written
in TypeScript, would be form logic in the builder (§2.1) and would drift.

**3. Everything is shown, grouped, and nothing is scoped.** §4.2 puts every
field in the form within reach of every expression — outer fields by name, an
instance's fields by position, all instances through an aggregate — so there is
no such thing as a field that is out of scope, and a picker that hid one would
be inventing a rule the engine does not have. Scoping would be ergonomics
dressed as a rule. Instead, the list is grouped by where the author is:

- **From inside a repeat:** this instance's fields first, unprefixed — `name`,
  which §4.2 resolves from the current instance outward — and the rest of the
  form after, in document order, grouped by container.
- **From outside a repeat:** an instance's field is shown as what it is,
  `members[0].name`, with the index made visually explicit — "first instance",
  not a bare `[0]`. That form is easy to type and easy to misread, and a picker
  that renders it plainly is the cheapest guard against an author reading it as
  "any member".
- **The aggregate forms belong in the picker too.** `members[].income` — "every
  instance" — is what an author outside a repeat actually wants, and it is
  offered alongside the positional form. §4.2 makes it valid only as an
  aggregate's argument; inserting it anywhere else is the compile error §4.2
  already defines, reported by compile rather than refused by the picker.

What the picker never does is resolve, narrow or reorder by what it guesses the
author means. It renders §4.2; it does not reinterpret it.

---

## 3. The screen model

### The two views, and the rule between them

The IR is a tree. The enumerator walks a screen sequence. Both belong in the
builder and they answer different questions:

- **Tree** — what the form is. Where you edit.
- **Screen plan** — what an enumerator sees. Where you check.

The rule that keeps §11's rules out of the console:

> The builder does not derive a screen plan. It asks for one and renders it.

`build_screen_plan` exists in both engines. It is not exposed over the API.
Proposal: `POST /forms/compile` gains a `screens` field on `CompileResponse` —
the ordered screens with index, kind, questionIds, repeatId, groupId, and the
instance plans. That is the same generated-contract discipline as everything
else: change the Pydantic model, regenerate, and the console gets typed screens
it could not have invented.

This matters more than it looks. §11.1's partition has six rules, three of which
surprise people (a calculate produces no screen; a field-list flattens nested
plain groups; a repeat is exactly one screen at any instance count). A console
that reimplemented them would be a third implementation of the screen plan,
unreachable by any vector, deciding what an author believes about their form.

### What each view shows

Tree, per node, badged from the plan the server returned:

| Badge | From |
|---|---|
| screen 4 | its own screen |
| screen 4, with 3 others | inside a field-list |
| computed — never asked | a calculate, §11.1 |
| roster — 1 screen, any number of rows | a repeat |
| never shown | the §0.4 liveness check |

> **[TRUNCATED HERE.]** The original continued past this table. Everything below
> this point in §3, and all of §4, §5 and §6, was lost and is rewritten
> separately.

---

> **WRITTEN AFTER THE LOSS — NOT RECOVERED.** Everything from here to the end of
> §6 was written on 6 September 2026, after the original was gone. It is not a
> reconstruction of what was there and does not claim to be: the original text
> of these sections was never seen again, so nothing below can be checked
> against it. §3's remainder, §4 and §5 continue topics the surviving text names
> and points at. **§6's topic is a choice made after the loss** — the original's
> §6 subject did not survive in any form, so this one takes the largest question
> the surviving text leaves open (§1: "One gap that has no home yet") rather
> than guessing at what was there.

### What the plan view shows

The tree shows containment. The plan shows sequence and count, which containment
does not imply and which is what an enumerator actually experiences.

Screens in order, each with its index, its kind, the questions on it, and — for
a repeat screen — the instance plan nested beneath it once. Once and not
recursively: §11.1 says an instance plan can contain no repeat screen, and it is
a compile error rather than a convention that keeps it that way, so a plan view
that renders arbitrary nesting is drawing a shape the IR cannot hold.

**Selection is shared between the views. Editing is not.** Clicking a question
in the plan selects it in the tree; edits happen in the tree. The plan is
derived, and an editable derived view is a second definition of the partition —
the thing the rule at the head of §3 already refuses, arriving as a
convenience.

**The plan view exists for the three rules that surprise people.** A calculate
produces no screen. A field-list flattens nested plain groups. A repeat is
exactly one screen whether it holds zero rows or thirty. An author who has read
none of §11.1 sees all three in the plan the first time they look, which is
worth more than documentation nobody opens.

### Staleness is shown, never computed away

The plan comes from the server. Between an edit and the next compile response
the displayed plan is out of date, and there are exactly two honest things to do
about it: show that it is stale, or fetch a new one.

**The console must never recompute a plan locally, including partially.** Not to
renumber after a delete, not to grey out a screen, not "just for the badge".
Every one of those is `build_screen_plan` reimplemented in TypeScript, reachable
by no vector, and deciding what an author believes about their form — which is
the third implementation §3 opens by refusing. The failure mode is not that the
local version is wrong on day one. It is that it is right on day one, and then
§11.1 gains a rule.

---

## 4. Preview, the trace, and test mode

Three things that get called "preview" and are not the same thing. They are
built in this order and the later two are worth little without the earlier.

| | Question it answers | Needs |
|---|---|---|
| **Preview** | What does this form look like to an enumerator? | The engine, hosted (§2.1, and the Wasm spike) |
| **The trace** | Why is this question in the state it is in? | Preview, plus an evaluation surface the engine does not expose today |
| **Test mode** | Is this form still doing what it did before I edited it? | Both of the above, plus draft storage (§6) |

### Preview

Renders the screen plan the server returned, one screen at a time, with the
engine evaluating relevance, constraints and calculates as answers are entered.
The engine, not an approximation — §2.1 is the whole reason, and the Wasm
question is which copy of the engine, never whether.

Preview is inspection. An author opens it, walks the form, and closes it. It
proves the form works now and proves nothing about the form in three weeks.

### The trace

The trace is the feature that makes the expression editor usable, and it is
worth more than the visual builder in §2.

**"Why is this hidden?" is the question authors actually have**, and §4.4 is why
it is hard to answer by looking. Null propagates. A `relevant` that is null
rather than false hides a question exactly as thoroughly, arrives from a
reference to an unanswered question three screens back, and looks identical on
screen. §4.7 widened this deliberately — a wrong-typed argument is null, never
an error — so the everyday case has no error message anywhere by design.

The trace answers it by showing the AST with each subexpression's value against
the current answers: which conjunct was false, which reference was null, and
what the whole node came to. It is the same tree §2's editor renders, annotated.

**The trace reports evaluation; it does not define it.** Both engines already
agree on every value it would display — that is what `conformance/vectors` and
the 1,395-probe function matrix are for — so the trace adds no semantics and
needs no vectors of its own. What it does need is a stated boundary: if a second
engine ever emits a trace too, the trace format must not become a second place
where evaluation is written down. It is a view of an answer, not the answer.

### Test mode

A saved set of answers, replayed against the draft after every edit, carrying
what the author expects to be true.

This is the regression half, and it is the half a builder is uniquely able to
offer. RCons change questions the week before fieldwork — that sentence opens
§2 of the pilot scope and is the reason item 0 exists at all. The risk in a late
edit is never the question being edited; it is the skip pattern four screens
later that used to work.

**A test case is not a conformance vector, and must not be stored as one.**

The shape is close enough to be tempting: a test case is an ordered list of
`set`, `addInstance` and `deleteInstance` steps with `expect` assertions, which
is exactly `conformance/README.md`'s step kinds. Put them in
`conformance/vectors` anyway and two unlike things share a directory. A vector
is normative, is owned by this repository, compares two engines, and changes
only with a spec change (rule 3). An author's test case is owned by the author,
asserts about one form, and is *supposed* to change when they change their form.
Mixing them means the vector count stops meaning what it means, rule 3 stops
being enforceable, and `generate_vectors.py` — which had to be taught not to
delete files it did not write (break 82) — acquires a new class of file it must
not touch and cannot recognise.

Test cases live with the draft (§6). The one legitimate crossing is manual and
deliberate: an author's test case that turns out to expose an engine
disagreement gets rewritten by hand as a vector, in a commit that says so.

---

## 5. Rosters

### The four sources, and what the builder offers for each

§2.3 says a repeat's rows come from four places and a repeat names one. The
builder's job is to make that choice visible, because it is the single decision
that determines everything else about the roster.

| Source | Declared by | In v1 |
|---|---|---|
| An earlier answer | `countExpr` | Yes — the §2 expression editor, integer-typed |
| The enumerator | neither field | Yes — `minInstances`, `maxInstances`, `allowAdd`, `allowDelete` |
| A list in the form | `rowSource`, `kind: "inline"` | Yes — a row table, edited in place |
| The sample | `rowSource`, `kind: "dataset"` | **Shown, disabled** |

`countExpr` and `rowSource` together are a compile error (§10.2), so this is a
choice of one and the editor should present it as one — a source selector, not
four independent fields that happen to conflict. The refusal exists because two
row sources have no arbiter; a UI that lets an author set both and then reports
a compile error has taught them nothing.

### The rule in §5

> **The builder renders the engine's diagnostics. It never composes its own.**

This is the rule §2 points at for warnings, and rosters are where breaking it
would be most tempting.

`kind: "dataset"` is refused today, and §10.2 requires the refusal to *name its
two conditions*: `_metadata.case_key`, which arrives with item 2, and a dataset
version's row order surviving delivery to a device, which is known defect 16.
The builder shows that message verbatim.

The temptation is to write a friendlier sentence into the console — "preloaded
rosters are coming soon". It is one sentence and it is wrong in three ways: it
is a second statement of when the feature arrives, it will not be updated on the
day the refusal is deleted, and it hides which of the two conditions is still
outstanding, which is the only part an author or a project manager can act on.
The engine's message is maintained because the engine's tests read it.

The same rule covers every warning — the decimal-equality one §4.5 names, the
missing-translation one, and the three §10.3 promises and no engine emits
(known defect 17). The builder displays what `POST /forms/compile` returns. When
defect 17 is closed the builder gains three warnings and no console change.

### The inline row editor

Inline rows are IR. The rows are `items` in the document, so editing them is
editing the form, and this is the one place where a spreadsheet-shaped grid is
the right control.

Two things it must show and one it must not do:

- **`bind` maps a source column into a question**, per row. A `bind` naming a
  column the source does not carry seeds `null` rather than failing (§2.3), so
  the editor should surface an unmatched column name at edit time — as a
  display, not as a refusal it invented.
- **An added instance has no source row.** Its `_rowKey` is `null` and `bind`
  does nothing for it. An author who builds a five-row inline roster with
  `allowAdd: true` needs to see that rows six onward arrive empty.
- **It must not offer to reorder rows for a dataset source.** For inline, order
  is the author's and is settled. For a dataset source it is the published row
  order, and defect 16 is that it does not survive delivery — which is half of
  why that source is refused, and not something a UI control can fix.

### What the tree refuses

Nested repeats (§2.3) and a repeat inside a `field-list` group (§10.2) are both
compile errors. The tree editor refuses the drop, and §1 already states the
principle: the compile error is the backstop, not the message. An author who has
just dragged something should be told why it will not go there, at the moment
they drag it, in the tree — not by a refusal after they press publish.

### `addLabel` and `summaryLabel`

A repeat screen renders `addLabel` — the text on the add control, per-form and
per-language — and `summaryLabel`, the expression that tells one row from
another in the list (§11.3, and §13 q6 of the pilot scope). Both are optional,
both are specified, and **neither engine implements either**.

That is shared work. Item 0 needs it because a roster editor with no way to set
either produces rosters an enumerator cannot read; item 3 needs it for the same
screen. It is scheduled once, at step 3, owned by neither item — see the build
order below and §10 of `docs/phase3-pilot-scope.md`.

---

## 6. Drafts, and the path a form takes to publish

> **The topic of this section is a choice made after the loss.** The original
> §6 did not survive in any form. This takes the gap §1 names and leaves open —
> "One gap that has no home yet" — because it is the largest unanswered
> question in the surviving text and because §2.3 makes it the highest-risk
> piece of item 0 to get wrong.

### There is nowhere to keep an unpublished form

`form_version` is immutable and published. There is no `form_draft` table in
`001_initial.sql` and nothing else in the backend holds unpublished IR —
`grep -rn form_draft backend/` returns nothing. Every form on the platform today
arrives already final, from an importer or a seed script, which is exactly the
situation item 0 exists to end.

Browser storage is not an answer. It loses work on a cleared profile, it cannot
be handed to a colleague, and a form half-authored on someone's laptop is
precisely the thing rule 12 was written about.

### The lifecycle, stated once

```
draft            mutable      IR + test cases + author + updated_at
  │
  ├─ every save → POST /forms/compile      diagnostics, screens, warnings
  │                                        (no version created, nothing stored)
  │
  └─ publish   → POST /forms/versions      check_publishable, then frozen
                                           immutable, numbered, deployable
```

**A draft never becomes a version except through `POST /forms/versions`.** This
must be written into the migration comment and not only here, because a table
sitting next to `form_version` holding the same shape of document is the
shortcut the next person in a hurry will take, and §2.3 is the whole warning:
the export work already found that a second route to the same artifact is how
two callers end up disagreeing about which version a submission belongs to
(breaks 40, 42, 61).

There is no promotion, no copy, no "publish this draft row". Publishing sends
the IR through the endpoint an import uses and gets back a version, and the
draft is not the thing that became it.

### What a draft is not

- **Not a version.** It has no version number. Numbers are minted at publish and
  a draft that is never published never consumes one.
- **Not a branch.** One draft per form (§1). Branching and draft-of-draft
  versioning are out of v1, and the reason is that they are cheap to add later
  and expensive to remove once authors rely on them.
- **Not collected data.** A draft holds a form definition and an author's test
  answers, never a respondent's. That is what makes it safe to store mutable and
  unencrypted, and it is worth stating so nobody reasons from `form_draft` to
  "drafts of submissions".

### Two things it needs that are easy to leave out

**Concurrency.** One draft per form and more than one author is last-write-wins
unless something stops it. A monotonic `updated_at` or an etag on the draft,
checked on save, is small and is the difference between two people editing a
questionnaire and one of them silently discarding the other's afternoon.

**A stated retention answer, even if the answer is "none yet".** Drafts
accumulate, they are the only mutable form storage on the platform, and an
unstated retention policy is how a table becomes permanent by accident.
`docs/known-defects.md` is the right home if the answer is that it is not
handled.

### Publish is where the gates are, and §0 is why

A draft that compiles is not a draft that may publish. `check_publishable` is
the boundary, and §0.4's two additions — reachability and liveness — belong
there rather than in the builder, for the reason §0.1 gives: the builder shares
the endpoint and, having no import record, structurally cannot reach the
strongest half of the gate that exists today.

The builder should run the same refusals early and show them while the author is
still editing. That is a preview of the server's answer, never a substitute for
it, and it is the same relationship as §3's screen plan and §5's diagnostics:
the console displays what the server decides, and decides nothing itself.

---

## Present and not in §2.2's table

`build_screen_plan` on both engines (not exposed over the API),
`specs/collectable-types-v0.1.json` (not exposed to the console), the XLSForm
importer as a second way in, `POST /forms/compile` and `POST /forms/evaluate`.

---

## The Wasm problem

§2.1: "The engine already compiles to Wasm for exactly this reason."

It does not. `shared/form-engine/build.gradle.kts` declares `jvm()`,
`iosArm64()`, `iosSimulatorArm64()` and `android` — no `wasmJs()` target
anywhere in the build, and `grep -ri wasm` over every `.kts`, `.kt`, `.toml` and
`.yml` returns five comments and zero configuration. `web-forms/` contains one
file: `.gitkeep`.

The engine is keepable Wasm-ready — dependency-free of UI and Android, which is
the expensive half and is genuinely done. But "compiles to Wasm" is an
aspiration stated as a fact, in the same way §11's two-month estimate was, and
it is holding up the one decision in §2.1 that cannot be met by an
approximation.

Two ways to honour "preview runs the same engine the handset runs":

**(a) Add `wasmJs()` and ship the Kotlin engine to the console.** Literally the
same engine, and it half-decides O-3 as a side effect — which is the reason to
put it in front of you rather than pick it. Unknown cost until someone tries it:
serialization on wasmJs, bundle size, and the conformance suites would want a
wasm test task, or the guarantee covers a build nobody runs.

**(b) Preview calls `POST /forms/evaluate`.** Exists today. But it runs the
Python reference, not the engine the handset runs, and it returns field
snapshots with no screens, no navigation and no trace — so it needs roughly as
much new API as (a) needs new build. It also quietly settles O-2 in the
direction of the reference being a production path.

My recommendation is (a), and I would spike the `wasmJs()` target for a day
before committing to any of the rest of item 0 — it is the only unknown in this
proposal, everything else is a known quantity, and if it fails the whole preview
and test-mode design changes shape. But it touches an open decision, so I am not
choosing it on my own.

---

## What is genuinely new work

The editing surface (question list, property panels, choice editor, tree,
reorder); the expression surface syntax + parser/printer; the evaluation trace;
the preview host; a `form_draft` table; and four small backend additions —
`screens` on `CompileResponse`, the collectable-types list, reachability and
liveness in `check_publishable`.

Not the form model, not compilation, not publishing. §2.2 was right about that.

---

## Order I would build in

1. `wasmJs()` spike — decide the preview host before designing around it.
   **Done**: O-3 closed for option (a), `docs/wasm-spike.md`.
2. Reachability + liveness into `check_publishable`, both engines, matched pair,
   known-breaks row. **Before any editor.** **Done 2026-09-07, one day after
   the editor** — the order this list warned against. §0.4 has the record;
   breaks 133–136.
3. `addLabel` / `summaryLabel` on both engines with vectors — shared with
   item 3. **Done 2026-09-06.**
4. `screens` on `CompileResponse`; collectable types over the API;
   `form_draft`. **Done** (PR #27).
5. Expression grammar spec + server parser/printer. **Done** (PRs #28, #29):
   Form IR Appendix A, `POST /forms/expressions`. §2's "neither exists" above
   was wrong about the parser — the importer's XPath parser was it.
6. The editor, tree, and plan view. **Done 2026-09-07** (PR #30): `/forms`
   and `/forms/{id}` in the console, plus `POST /forms` and three fields on
   `FormSummary` so a draft has a form row to belong to and a version to
   start from.
7. Preview, then the trace, then test mode. **Done 2026-09-07**, in that
   order, each verified in a browser against a real backend before the next
   started: the handset's engine compiled to Wasm (`scripts/build_engine_wasm.sh`,
   `web/src/builder/engine/facade.ts` is the contract), one session per page
   that the preview, the trace and test mode all read; `form_draft.test_cases`
   (migration 0007). Breaks 137–148.

Steps 2 and 3 are the ones most likely to be pushed behind the editor and are
the two that get more expensive for it — 2 because forms will already have been
published, 3 because item 3 will have assumed it.

---

## Three things I need from you before implementing

1. The Wasm decision (a or b, or spike first).
2. Whether a statically-empty container holding answerable questions is an error
   or a warning, since §10.3 does not currently distinguish it from a leaf's
   false relevance.
3. Confirmation that `addLabel`/`summaryLabel` engine support gets scheduled
   once rather than inside either item.
