# Phase 3 — the pilot scope

**Goal:** RCons runs a small real pilot on DCP.
**Decided:** 4 September 2026
**Re-ordered:** 4 September 2026 — RCons will author their forms in the
dashboard, so the visual form builder is item 0 and the skip-to prototype comes
out of the sequence; **closed as not needed 6 September 2026 (§12)**.
**Status:** scope and order agreed.
**Timeline:** deliberately none. See §11.

Phase 2 part one ended with the collection chain working end to end: a form
authored elsewhere, imported, deployed, delivered to a handset that had never
held it, collected offline, synced encrypted, exported in four formats.

That chain is necessary and not sufficient. A survey firm cannot run fieldwork
on it, because the platform knows a device but not a person, and has no way to
say which enumerator works on which households.

Phase 3 closes that gap.

---

## 1. What decided this scope

RCons is the first customer. Their current system was examined in detail
(`docs/rcons-current-system.md`). Two findings drive everything here:

**The commercial case is measured, not asserted.** Their largest survey carries
102 hand-written Kotlin section screens — 48,769 lines — written per survey and
discarded at the end of it. The questionnaire itself is already data in their
database. What is rewritten every time is rendering and navigation. On DCP that
number is zero.

**The one real incompatibility is skip-to versus relevance.** RCons expresses
navigation as ordered conditional jumps; DCP, like XLSForm and SurveyCTO, uses
declarative relevance. They are not mechanically interchangeable.

**That incompatibility stopped setting the order on 4 September 2026.** RCons
confirmed their questionnaire tool can emit XLSForm once we give them a
template, and their existing surveys are finished. So new forms arrive already
declarative and the conversion problem applies only to a corpus nobody is
waiting on. The prototype that was item 0 is **closed in §12** — the old
corpus carries its skip logic as prose, so there was never a corpus for it to
convert.

**What replaced it follows from the same conversation.** RCons will build their
forms in the dashboard themselves rather than handing us questionnaires to
import. That makes the visual form builder the thing nothing else starts
without, and it was not in this document at all.

---

## 2. Item 0 — the visual form builder

**Nothing in this phase starts without it.** RCons will author their forms in
the dashboard themselves. Until they can, every form on the platform arrives
through an importer or a seed script, which means we are in the loop for every
change to every questionnaire — and a survey firm changes questions the week
before fieldwork, not the month before.

### 2.1 Three decisions, stated here rather than left to whoever builds it

**The builder produces Form IR and nothing else.** No form logic lives in the
builder. It is an editor for a document, and the document is the same
`specs/form-ir-v0.1.md` an XLSForm import produces. A builder that carries any
evaluation of its own creates a second definition of what a form means, and the
one that ships to the handset is then not the one the author was looking at.

**Preview runs the same engine the handset runs.** Not a preview renderer, not
an approximation — the engine. A form cannot behave one way in preview and
another in the field, and the only way to guarantee that is to have one
implementation of the behaviour.

**The engine does not compile to Wasm today.** An earlier version of this
paragraph said it already did, "for exactly this reason". That was false: no
Gradle file in this repository declares a `wasmJs` target, and
`shared/form-engine` has one test source set, `jvmTest`. What is true is the
property the false sentence was reaching for — the module is dependency-free of
UI and Android framework code, which is what would make a browser build
possible. Nothing has shown that it works.

The distinction matters because this was load-bearing for a decision. Preview
in the browser is the only unknown in item 0; everything else is a UI over
machinery that exists (§2.2). A sentence asserting the unknown was already
solved would have removed the one thing worth checking first, which is why item
0 opens with a Wasm spike rather than an editor. If the spike fails, preview
and test mode change shape, and it is cheaper to learn that in a day than after
an editor has been built on top of it.

A passing spike is also not the same as a supported target. A `wasmJs` target
that no CI job executes is a guarantee covering a build nobody runs — the
pattern this repository has now recorded several times — so the spike's cost
includes a test task and a vector run on that target, or it does not count as
done. `conformance/README.md` claimed four platforms on the same false basis
and now says JVM; known defect 18 holds what is missing.

**The relevance and constraint editor is visual with a code escape hatch, and
both are required.** RCons's own rules settle this. `q1>5 && q1<20` and
`q11!=1` are what most of their conditions look like and a dropdown builder
handles them comfortably — field, operator, value, joined by and/or. But their
corpus also contains `count-selected()` and nested and/or, which a dropdown
builder cannot express without becoming a programming language with a mouse.
Visual for the common case, a code field for the rest, and the code field
validates against the same expression grammar the engine parses (§4 of the IR).
Neither alone is enough: visual-only strands the hard forms, code-only means
every author writes expressions by hand.

### 2.2 What already exists, so this is not overestimated

The builder is a UI over machinery that is already built and already tested:

| Already there | Where |
|---|---|
| The IR itself, versioned and normative | `specs/form-ir-v0.1.md` |
| Compile, with document-shape refusal (§10.1) | both engines, 22 `malformed` vectors |
| The publish path, with the sensitivity check | `check_publishable`, `conformance/sensitivity` |
| A route that accepts IR and publishes a version | `POST /api/v1/forms/versions`, with `deployTo` |
| Version freeze, deployment per environment, retention | Form IR §9, sync §5.1 |
| The engine the preview needs | `shared/form-engine`, 85 vectors on two engines |
| The console it lives in | `web/`, React 19 + Vite, generated wire types |

What is missing is the editing surface: a question list, a property panel per
question type, the choice-list editor, the relevance/constraint editor above,
and preview. Not the form model, not compilation, not publishing.

### 2.3 Publishing goes through the import path, not beside it

**The builder gets no route of its own into `form_version`.** It produces IR and
hands it to the same endpoint an import uses — the same compile, the same
sensitivity check at publish time, the same version freeze and dataset pinning.

This is the decision most likely to be quietly undone by whoever is in a hurry,
and the reason it must not be is in this repository's own history: the export
work found that a second way to reach the same artifact is how two callers end
up disagreeing about which version a submission belongs to (breaks 40, 42, 61).
A builder that writes `form_version` directly would be a second definition of
"published" — one that has never been through the sensitivity gate, and one the
conformance vectors cannot see, because a vector compares engines and this is a
caller. `docs/project-conventions.md`, "Where the conformance architecture stops
protecting you", is about exactly this shape of mistake.

---

## 3. Item 1 — login and permissions

Everything else in this phase depends on it. Today DCP identifies a device, not
a person.

### 3.1 The model

**A user belongs to the organization, not to a project.** Credentials are
created once. Project membership is separate and comes and goes.

```
platform_user          credentials, created once
    │
org_membership         member of this organization, with a role
    │
project_member         member of this project, with a role and a team
    │                  (a user may be in several projects)
    │
app                    the enumerator switches workspace between them
```

### 3.2 Who can create whom

| Role | Can create | Approval |
|---|---|---|
| Admin | Anyone | None needed |
| Programme manager | Supervisors, enumerators | None needed |
| Supervisor | Enumerators only, in their own team | **Required** — from a PM or an Admin |

Two rules hold throughout:

- Nobody creates a role above their own.
- Nobody creates outside their own scope. An enumerator created by a supervisor
  lands in that supervisor's team automatically.

A user who already exists in the organization is **selected**, not created. No
approval is involved in adding an existing member to a project.

### 3.3 The pending state

A supervisor's new enumerator is `pending_approval`. In that state:

| | |
|---|---|
| Can be added to a team | Yes |
| Can be assigned sample | Yes |
| Can log in | **No** |
| Can collect | No |

The supervisor's preparation is never blocked, and no unapproved person's data
enters the system. When approval lands, the enumerator logs in and their work is
already waiting.

### 3.4 Permanent and temporary

- **Permanent** — a standing member of the organization.
- **Temporary** — brought in for a project; project membership ends when the
  project closes, and the organization membership becomes `deactivated`.

**Deactivated is not deleted.** The record stays: who collected what, and when.
Reactivation is a status change on the same user, never a second account —
otherwise the same person exists twice and their history splits.

### 3.5 Permissions, not roles

A role is a set of permissions plus a scope. It is not a hard-coded branch.

```
Permission    user.create, user.approve, sample.upload, sample.assign,
              form.publish, submission.review, export.download, …

Role      =   a set of permissions + a scope

Scope         organization | project | team
```

Two consequences:

- The approval flow in §3.2 falls out of the model rather than being coded:
  a supervisor holds `user.create` and not `user.approve`.
- "A supervisor sees only their own team" is a **scope**, not a permission.
  That is what delivers the isolation §4 requires.

**Every console screen checks a permission, never a role.** Otherwise the first
custom role breaks the UI.

### 3.6 Schema changes

Against `backend/migrations/schema/001_initial.sql`:

| Table | Change |
|---|---|
| `platform_user` | Add `pending_approval` to the status check |
| `platform_org_membership` | Add `status` (active / pending_approval / deactivated), `membership_kind` (permanent / temporary), `created_by`, `approved_by`, `approved_at` |
| `platform_org_membership` | `org_role` widens beyond owner/admin/member, or moves to a role table |
| `team` | Currently project-scoped with a `parent_team_id`. Confirm a supervisor's team is a `team` row and that scope resolves through it |
| `project_member` | Add `status`, `added_by`. `user_id` is not a foreign key today — it should be |
| new: `role` | Custom roles: name, scope, organization |
| new: `role_permission` | The permission set for a role |
| new: `user_role` | Which role a user holds, in which scope |

Note `project_member.user_id` and `device.user_id` are plain text columns with
no foreign key. That was tolerable while there was no user model. It is not now.

---

## 4. Item 2 — sample assignment and supervisor isolation

### 4.1 The flow

```
Programme manager   uploads the sample          → dataset version
                    splits it across supervisors
Supervisor          splits their share across their enumerators
Enumerator          sees only what is assigned to them
```

### 4.2 Isolation is the requirement

*A supervisor's sample does not reach another supervisor.* This is not only
assignment — it is visibility. Supervisor A must not see B's sample, B's
enumerators, B's submissions, B's progress, or B's rows in an export.

This is why §3.5 makes scope part of the role rather than a filter applied in
the UI. A filter can be forgotten in one query. A scope cannot.

### 4.3 Cases

`case_record` and `assignment` exist in the schema and are unused. A sample row
becomes a case; assignment points it at a user or a team. RCons already works
this way — their `section_progress` is keyed on
`settlementCode + structureId + hhId + sectionName`, which is a case plus a
visit plus a status.

### 4.4 Composite keys

RCons's sample identity is several columns together — `settlementCode`,
`structureId`, `hhId`. `dataset_record` carries a single `record_key` with
`UNIQUE (dataset_version_id, record_key)`.

Decide deliberately: compose the key on import (`settlement|structure|hh`), or
widen the schema. Composition is simpler and is probably right, but the choice
must be recorded — §3.1 of the Form IR made exact key matching a stated
decision, and this is the same question one level up.

---

## 5. Item 3 — repeat screen flow, and the roster it unblocks

RCons's roster is DCP's `repeat`. Three ways of deciding the count:

| How | DCP today |
|---|---|
| From an earlier answer — "how many live here?" | `countExpr` — works |
| From the sample — a column giving the number | `countExpr` over a dataset value — works |
| **The enumerator decides as they go** | Engine: works. **Nothing can show it** |

The third is the common case for a household member roster: keep adding until
the respondent says stop.

**Corrected again, 6 September 2026 — the table above is about the count, and
two of the four sources do not give one.** Reading real RCons questionnaires
found rows that exist before the interview does: a household's known members
come **preloaded from the sample**, and their agricultural module repeats the
same four questions over a **fixed list of ten practices** written into the
questionnaire. Neither is a count from anywhere; both are a list of rows. Form
IR §2.3 now calls that a `rowSource` and §11.3 renders all four sources as the
same one screen — the source decides where rows come from, not how they look.
Preloaded rows and enumerator-added rows **coexist in one roster**, which is the
ordinary case: the sample knows the members it knew, and the baby born since is
added to the same list.

The fixed-list half is buildable now. The sample half is not — it needs
`_metadata.case_key`, which is item 2's cases, and it needs a dataset version's
row order to survive reaching a device, which it does not
(`docs/known-defects.md` 16). §2.3 specifies both and refuses the second until
those land.

**Corrected 4 September 2026.** This section first said the third way was
"Missing" and that what was missing was the user-driven add. That was wrong, and
reading the code moved the gap rather than closing it.

**The engine already does it.** `addInstance` and `deleteInstance` are on the
runtime in both engines; `minInstances` instances are created when the form
opens; `maxInstances` bounds the add; and an add on a `countExpr`-controlled
repeat is refused with a message rather than silently ignored. Vectors
`repeat-001`…`repeat-008` hold both engines to the instance semantics. None of
that has to be built.

**What is missing is a screen to put a roster on.** Form IR §11.1: *"A repeat
subtree is excluded from the screen plan entirely. Screen flow for repeats is
deferred to v0.2 together with repeat navigation UX."* The collection screen
renders `screen.questionIds`, and by construction that never contains a repeat
child — so there is no control to press because there is no screen for it to be
on. The engine's roster capability is unreachable from a handset, and it is the
screen plan and not the widget that makes it so.

Item 3 was therefore three things, and **the first two are done — 5 September
2026.**

1. ~~**Specify repeat screen flow.**~~ **Form IR §11.3.** A repeat is one screen
   holding the instance list; its children are partitioned by the same §11.1
   rules into an instance plan rendered once per instance; an instance is
   entered and left, and `next` from its last screen returns to the list rather
   than advancing to the next instance, because that is where "have we got
   everybody?" belongs. **No instance count enters the screen plan**, so the
   pair a household of six reads is the one it read at five — a moving
   denominator is a promise about remaining work that the form then withdraws,
   and for an enumerator-driven roster nobody can know the number in advance.
   A position holds an instance **id** and never an ordinal, so somebody else's
   delete cannot slide the enumerator into a different member's answers.
2. ~~Implement that plan on both engines, with vectors.~~ `screens-012`…
   `screens-025`, both engines, and breaks 82–89 are the evidence they catch it.
   Defect 14 is closed.
3. ~~`addLabel` / `summaryLabel` on both engines, with vectors.~~ Done
   6 September 2026 — `repeat-013`…`repeat-015` and `sensitivity-006`/`007`,
   both engines, breaks 99–104. §2.3's label chain, and known defect 19 closed
   in the same commit.
4. **Build the roster UI on it** — the list, and the add and remove
   affordances. **This is what is left of item 3**, and it is the only part of
   it that is UI.

**Where RCons's shape decided it.** `section_progress` is keyed
`(settlementCode, structureId, hhId, sectionName)`: a 95-section instrument they
have run for years shows nobody a position across the whole questionnaire,
because at that size no global denominator stays true. `femaleRoasterDone` and
`maleRoasterDone` are completion flags — a roster is a unit of work that is
*done*, with a boundary. And their roster is a section, which is one place you
go and come back from. All three said the same thing: one screen with a list on
it, and an instance you enter and leave.

**Smaller than "Missing" implied, and larger than a button** — which is why the
item is named for the screen flow and not for the roster.

---

### 5.1 What an enumerator reads to tell one row from another

Their questionnaire's first roster question is `PID`, marked *already filled*.
So a roster row's identity is **visible to the enumerator**, not internal
bookkeeping — which is worth checking against what we built, because our
`_rowKey` is internal and an instance id is `i1`, `i2`.

**Decided: a row does not need a displayed identifier separate from
`summaryLabel`.** A second string beside it would be two ways to label one row,
and the first thing anyone would ask is which of them wins. `summaryLabel` is
the row's displayed identity, and what a row shows is a question about its
*content*, not about how many label slots the IR has.

**For a sampled row, that already covers it, with nothing new.** "Already
filled" is not a widget — it is a bound, read-only question:

```json
{ "type": "question", "id": "pid", "dataType": "text",
  "label": { "en": "PID" }, "readOnly": true }
```

with `"bind": { "pid": "member_id" }` on the `rowSource`. The sample's key lands
in `pid`, the enumerator sees it filled and cannot change it, and it appears as
the first question of the member's screen exactly as it does in their
questionnaire. The list row then reads `summaryLabel` — a §7.1 interpolated
label evaluated in the instance's scope, so `pid` among its arguments resolves
to that instance and the row reads `4471 — Fatima`. Both halves are specified;
`summaryLabel` landed on both engines on 6 September 2026, so this half is
built; what is left of the list above is the UI.

**Two things it does not cover, and only the second is a gap in the design.**

1. **An added member has no PID.** `bind` does not apply to an instance the
   enumerator added — `rows-006` asserts exactly that — so `pid` is null, §7.1
   renders null as the empty string, and the row reads `— Ali` while every
   sampled row above it reads `4471 — Fatima`. In their system that identifier
   is *generated* for a new member. Whether it must be here is the question, and
   it is theirs to answer rather than ours to assume.
2. **Nothing can generate one.** There is no `index()` or `position()` in §4.3,
   so no expression yields "this instance's place in the roster" and a form
   author cannot write `coalesce(pid, concat("N", index()))`. A generated
   identifier is not a design we rejected; it is not currently expressible by
   any means. That is a one-function change to §4.3 — and a function on the
   surface is a conformance matter (`functions/`, every value shape, both
   engines), not a client detail.

   **Question 7 was answered on 6 September 2026 and did not reach this.**
   RCons said a row's label is a specific column of the sample, which is
   `labelColumn` and which an added row does not have either. So the sampled
   case is fully specified and the added case is exactly as open as it was —
   the question that would close it is what an *added* member's row should
   read, and that has not been asked yet.

**Why the answer mattered beyond the label — and no longer does.** This
section used to say that if `Person Id` meant "pick a member from the roster",
whatever the enumerator reads on that list would be the **referent** of 73
questions, and a member with no identifier would be one nobody can pick. That
was the larger half of the stake, and §13 question 4 removed it on 6 September
2026: `Person Id` is a prefilled question, not a picker, so an added member
without an identifier strands nothing.

What is left is the smaller and still real half. An added row reads an empty
label beside sampled rows that read `4471 — Fatima`, which is a legibility
problem on the screen rather than a referential one in the data.

**What not to do meanwhile:** invent a serial in a client. Two clients would
generate different ones, both would pass every vector, and the enumerator on one
would read a number the other does not show — the exact shape §3.2 refuses when
it forbids a client to pre-narrow a choice list, and the reason screen flow and
progress are specified in the engine rather than left to each UI.

---

## 6. Item 4 — separate sync for sample and form

RCons's app has separate tabs: enumerators update the sample and the
questionnaire independently, on instruction. DCP pulls everything on one sync.

Their model is better in the field. A 37,000-row sample over a village
connection is a different proposition from a small form update, and the person
holding the handset should decide which they are doing.

Scope: separate pull scopes, separate progress, separate "last updated", and an
explicit action per scope rather than one Sync button.

---

## 7. Item 5 — supervisor monitoring

Within their scope only:

- progress against target, by enumerator and by area
- submissions per day
- quality flags outstanding
- devices: last sync, pending ops

This is the screen a supervisor lives in during fieldwork.

---

## 8. Item 6 — review and correction

- automated quality rules run on arrival (`plausible_ranges.json` in RCons's
  app is exactly this — 34 KB of range checks, already externalised)
- flagged submissions go to a queue; clean ones do not, by project policy
- approve, reject, or request correction with a reason
- a rejection returns to the enumerator's device as work

The full-review-of-everything model is what makes SurveyCTO slow. Reviewing what
is flagged is the differentiator, and it should be a project setting.

---

## 9. Not in this phase

Named so their absence is a decision:

- Desktop data entry. Two known defects block it (dates, media widgets). RCons
  collects on paper and keys the forms in afterwards, and desktop entry is what
  they want for it — this is the next phase, and the defect rows say so
  (`docs/known-defects.md` 1 and 2).
- `Structure Map` and the `Custom` selection types. Understood later; ignored
  for now by agreement. **`Person Id` left this list on 6 September 2026** — it
  is not a type and there is nothing to defer: a prefilled question, expressed
  by `bind` or by `calculate` / `default` (§13 question 4).
- Entity relationships and longitudinal linking. RCons generates the next
  survey's sample by exporting from this one, so the platform does not need to
  carry the link.
- Nested repeats (IR v0.2). One form in a 22-form corpus.
- Workflow engine beyond review. SLAs and escalation are V1.5.
- Text audits, audio audits, speed limits. RFP features, not pilot features.

---

## 10. Order

| # | Item | Why here |
|---|---|---|
| 0 | **Visual form builder** | RCons authors forms themselves; nothing starts without it |
| 1 | Login and permissions | Everything below depends on it |
| 2 | Sample assignment and supervisor isolation | The daily work of a survey firm |
| 3 | Repeat screen flow | Spec (§11.3) and the screen planner on both engines **done 5 Sep 2026**; the roster UI and the shared work below are what is left. Blocks household listing |
| 4 | Separate sample/form sync | Field usability |
| 5 | Supervisor monitoring | Fieldwork needs oversight from day one |
| 6 | Review and correction | Closes the quality loop |

**What changed on 4 September 2026.** The skip-to prototype was item 0 because
it was the only unknown cost and it was cheap to resolve. It is neither of those
now: RCons's questionnaire tool can emit XLSForm once given a template, and
their existing surveys are finished, so nothing is waiting on the conversion. It
moved to §12 as optional work, and §12 closed it on 6 September: the skip logic
is Urdu prose and a person converts it on entry. The visual form builder takes
its place, because
RCons authoring their own forms is the thing every other item assumes.

Item 3 was also re-costed — see §5. It was in this table as "small" while it was
understood as a widget; it is a v0.2 spec decision on repeat screen flow, then
the screen planner on both engines, then the UI.

### Shared work, owned by neither item

**`addLabel` and `summaryLabel` on both engines, with vectors. Scheduled once,
before either item that needs it.**

~~§2.3 and §11.3 specify both and neither engine implements either.~~ **Done
6 September 2026**, on both engines, with `repeat-013`…`repeat-015`,
`sensitivity-006`/`007` and breaks 99–104. It was scheduled here because two
items needed it and neither owned it:

- **Item 0** cannot offer a roster editor without them. A repeat whose add
  control has no text and whose rows cannot be told apart is a roster an
  enumerator cannot read, so a builder that omits them ships forms that are
  worse than the ones the importer produces.
- **Item 3** needs them for the same screen. They are already on its remaining
  list (§5, and `docs/project-conventions.md`, current phase, item 3).

**No specification decision is owed before it.** Step 3 was briefly at risk of
gaining one: `summaryLabel` interpolates question values onto the repeat screen
(§7.1), and if a roster row's name were `sensitive` that would display it.
RCons answered on 6 September 2026 that it is not — the enumerator is meant to
read the name — so no specification decision blocks the start of it.

**The one thing step 3 had to close rather than inherit — and did.**
`check_sensitivity_propagation` walked *fields*, and `summaryLabelArgs` sits on a
**repeat**, which is not one. A question's label is already covered — both
engines collect `labelArgs` and `constraintMessageArgs` into a field's
dependencies, and `label-005` pins that edge — so this is a structural gap
rather than an oversight in the same place. It costs nothing today because
nothing parses `summaryLabel`; it becomes a live leak on the first day
something does. Known defect 19, closed in step 3's own commit rather than after it, because
the window between a release that parses `summaryLabel` and one that checks it
is a leak behind a clean publish.

It is written here, and in `docs/phase3-item0-builder-scope.md` §5, so that
neither item plans around it separately. **The failure this prevents is not
that it gets forgotten — it is that it gets done twice**, or done once inside
whichever item reaches it first and then re-litigated by the other, which is
how a shared engine change acquires an owner who was not choosing to be one.

It sits at step 3 of item 0's build order, after the reachability and liveness
work and before any editor, because it is engine work with vectors and both
engines must land it together. The row above says "the screen planner on both
engines" for the same reason: §11.3 is not finished on either engine until
this lands, and the earlier wording — "both engines done" — was the kind of
sentence that gets planned against.

---

## 11. There is no timeline, and that is deliberate

**The pilot happens when the platform is ready, not on a date.** No item here
carries an estimate and the phase carries no target month.

This is worth stating because the absence will otherwise look like an oversight
and somebody will fill it in. An earlier version of this document said items 1–6
were "roughly two months". That number was written before item 3 was understood
(§5) and before item 0 existed at all, and it survived both corrections by
looking like a fact. A date set now would be built on the same kind of guess,
and the cost of missing it is a customer's fieldwork season.

What replaces it: the items are ordered, each says what it blocks, and the
sequence is the plan. When RCons needs a date they get one from the item that is
actually in progress, not from this document.

---

## 12. Not needed — the skip-to prototype

**Closed 6 September 2026. Not deferred, and not optional work kept in reserve.
Not needed.**

This was item 0, then optional work held against the day RCons's old corpus had
to move. Reading their actual questionnaires closed it: **there is nothing for a
converter to consume, because a person has already done the conversion.**

RCons's questionnaire carries its skip logic as Urdu prose in a codes column. It
is an instruction to whoever enters the question, not a machine-readable rule.
Somebody reads that column and enters the question in the dashboard with its
relevance condition already worked out. The conversion happens in the head of
the person typing the form in, and it happens **before any tool sees it**. A
skip-to → relevance compiler would be handed prose.

The rule it was to convert looked like this, and this is the shape that is not
in the database in this form:

```
q11==2 to q12a, q10<=6 to q12b, q10<15 to endSection, q11 to q13
```

**This is not the reason §10 gave, and the difference matters.** §10 removed
this item because nothing was *waiting* on it — the tool can emit XLSForm, and
their existing surveys are finished. That was true, and it left the item
standing as work somebody might one day schedule. The real reason is that the
number it was to report was never measurable: "the percentage that converts
without manual work" is a statistic over a machine-readable corpus, and the
corpus is Urdu sentences. An item kept for a number nobody can compute is worse
than a closed one, because it looks like a decision that has been deferred.

**Where the work actually went.** Item 0's relevance editor is carrying it. The
migration path is a person reading skip prose and building a condition in the
builder, which means that editor has to be good for exactly that person — a
second, independent argument for §2.1's decision that it is visual **with** a
code escape hatch. The conversion is a UI requirement, not a compiler.

**What would bring it back.** That RCons's questionnaire tool starts holding
skip logic as structured data rather than prose. Nothing suggests it will, and
if it did, the XLSForm template (§13 question 1) is the cheaper target: a tool
that can emit structured skip logic can emit `relevant`.

---

## 13. Open questions for RCons

1. ~~**Can the questionnaire → CSV tool emit XLSForm?**~~ **Answered, 4
   September 2026: yes, once we give them a template.** It was the
   highest-value question in this list and it turned out to be the one that
   re-ordered the phase — the skip-to conversion applies only to the existing
   corpus, and §12 then closed even that. The template is a dependency of item 0.
2. Do enumerators rely on resuming at **section** granularity, or is resuming
   within a submission enough? `section_progress` suggests the former.
3. When a sample row is updated during collection — `memberAge` beside
   `upMemberAge` — is that a correction to the sample, or a new answer? It
   decides whether the sample must be writable.
4. ~~**What does Person Id do?**~~ **Answered, 6 September 2026: it is not a
   question type.** It is a *prefilled* question, filled either from the sample
   or from an answer in another section or group. Both already express in the
   IR — from the sample is `rowSource`'s `bind`; from another answer is
   `calculate` or `default`.

   **It needs no new surface.** The worry in this question was cross-repeat
   referencing, 73 questions each picking a member out of a roster, and that is
   not what these are. Nothing is added to §4.3, nothing to §2, and nothing to
   the builder's palette beyond what it already has.
   `docs/rcons-current-system.md` §5 listed it as a type with no DCP
   equivalent; that is corrected.

   It also dissolves the pairing this list drew with question 7. If `Person Id`
   does not pick a member, an added member having no identifier cannot strand
   73 questions. That half of question 7's stake is gone — the other half is
   not, and is recorded there.
5. How many enumerators, questions and days in the next fieldwork? It sizes the
   pilot.
6. ~~**Does any survey have an enumerator type a household id and the roster
   fill from it?**~~ **Answered, 6 September 2026: no, and the shape does not
   exist in their workflow.** The roster filter comes from the **case the
   enumerator selected**. A supervisor assigns the sample, the enumerator picks
   from their assigned list, and that selection *is* the case — so the filter
   reads an assignment, never a typed answer.

   That closes it in the strongest way available: Form IR §2.3's refusal of an
   answer-referencing `rowSource` filter now rests on **how the work is
   actually done**, not on a judgement about which resolution timing is least
   bad. There is no re-resolution design to schedule, before the pilot or
   after, because nothing needs re-resolving — a case is chosen once and does
   not change under the enumerator's hand.

   It also settles what `_metadata.case_key` has to carry (§8): the case behind
   the enumerator's selection, which is item 2's `assignment` → `case_record`
   and not a value the form collects.
7. ~~**What does an enumerator read to tell one roster row from another — a
   PID, a serial, or the name?**~~ **Answered, 6 September 2026: a specific
   column of the sample.** That is `labelColumn`, which Form IR §2.3's
   `rowSource` already carries, and the precedence is already written down —
   `labelColumn` is what a row of the instance list says *when `summaryLabel`
   is absent*. The mechanism is specified, §5.1's decision that a row needs no
   second displayed identifier stands, and nothing is added to the IR.

   **One half of §5.1 stays open and this answer does not reach it.** An
   instance the enumerator *added* has no sample row, so it has no
   `labelColumn` value and no `bind`-seeded `pid` either (`rows-006`). Beside
   sampled rows reading `4471 — Fatima` it reads as an empty label, and §4.3
   still has no `index()` or `position()` with which an author could generate
   one. What an added member's row should read is theirs to answer, and asking
   it did not answer it — see §5.1.

   A second consequence worth stating: `labelColumn` lives on a **dataset**
   `rowSource`, which §2.3 refuses until `_metadata.case_key` (item 2) and
   known defect 16 both clear. Until then a preloaded roster's row label comes
   the other way, through `summaryLabel` over `bind`-seeded questions (§5.1),
   which is step 3's work.
8. What does CERP not get from SurveyCTO? The most valuable competitive
   information available, and it comes from the customer rather than from us.
9. ~~**Is the name on a roster row a sensitive field?**~~ **Answered,
   6 September 2026: no — the enumerator is meant to read it.** Asked because
   `summaryLabel` interpolates question values onto the repeat screen (§7.1),
   so a name marked `sensitive` would be rendered there.

   **It settles a schedule rather than a design.** Step 3 stays what it looks
   like today — implement `addLabel` and `summaryLabel` on both engines with
   vectors (§10) — and no sensitivity rule has to be settled in the
   specification before it can ship.

   It does not settle the general case, and what that case actually is turned
   out to be narrower than it first looked. §10.2's prose defines the leak over
   `calculate`, `relevant`, `constraint`, `required`, `readOnly` and `default`
   and does not mention labels — but both engines already collect `labelArgs`
   and `constraintMessageArgs` into a field's dependencies, so a **question**
   label interpolating a sensitive field is refused at publish today and
   `label-005` pins the edge. What is genuinely outside the check is
   `summaryLabelArgs`, because it sits on a **repeat** and the check walks
   fields. It is latent — nothing parses `summaryLabel` yet — and it becomes
   real the day step 3 lands. Known defect 19.
