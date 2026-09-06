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
2. Reachability + liveness into `check_publishable`, both engines, matched pair,
   known-breaks row. **Before any editor.**
3. `addLabel` / `summaryLabel` on both engines with vectors — shared with
   item 3.
4. `screens` on `CompileResponse`; collectable types over the API;
   `form_draft`.
5. Expression grammar spec + server parser/printer.
6. The editor, tree, and plan view.
7. Preview, then the trace, then test mode.

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
