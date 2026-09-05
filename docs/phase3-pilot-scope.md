# Phase 3 — the pilot scope

**Goal:** RCons runs a small real pilot on DCP.
**Decided:** 4 September 2026
**Re-ordered:** 4 September 2026 — RCons will author their forms in the
dashboard, so the visual form builder is item 0 and the skip-to prototype comes
out of the sequence (§12).
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
waiting on. The prototype that was item 0 is kept as optional work in §12,
against the day that corpus has to move.

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
implementation of the behaviour. The engine already compiles to Wasm for exactly
this reason (`shared/form-engine` is dependency-free of UI and Android framework
code, which is what makes it possible).

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
3. **Build the roster UI on it** — the list, the add and remove affordances, and
   `addLabel` / `summaryLabel`, which §2.3 now specifies and neither engine
   parses yet. **This is what is left of item 3.**

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
- `Person Id`, `Structure Map`, and the `Custom` selection types. Understood
  later; ignored for now by agreement.
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
| 3 | Repeat screen flow | Spec (§11.3) and both engines **done 5 Sep 2026**; the roster UI is what is left. Blocks household listing |
| 4 | Separate sample/form sync | Field usability |
| 5 | Supervisor monitoring | Fieldwork needs oversight from day one |
| 6 | Review and correction | Closes the quality loop |

**What changed on 4 September 2026.** The skip-to prototype was item 0 because
it was the only unknown cost and it was cheap to resolve. It is neither of those
now: RCons's questionnaire tool can emit XLSForm once given a template, and
their existing surveys are finished, so nothing is waiting on the conversion. It
moves to §12 as optional work. The visual form builder takes its place, because
RCons authoring their own forms is the thing every other item assumes.

Item 3 was also re-costed — see §5. It was in this table as "small" while it was
understood as a widget; it is a v0.2 spec decision on repeat screen flow, then
the screen planner on both engines, then the UI.

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

## 12. Optional — the skip-to prototype

**Not scheduled. Kept because the reasoning that removed it could change.**

This was item 0. Take the 2,128 questions in the Sindh listing database, convert
their skip rules to declarative relevance, and report the percentage that
converts without manual work plus the shapes that do not.

```
q8==1 to q10
q11==2 to q12a, q10<=6 to q12b, q10<15 to endSection, q11 to q13
```

Read as: *after this question, if q11==2 go to q12a; otherwise if q10<=6 go to
q12b; otherwise if q10<15 end the section; otherwise go to q13.* A single rule
determines the relevance of every question it jumps over, not just its target.
Chains compose. Some sets — backward jumps, overlapping conditions — have no
single declarative reading.

**Why it came out of the sequence.** RCons confirmed their questionnaire → CSV
tool can emit XLSForm once we give them a template, and their existing surveys
are finished. So every form authored from now on arrives already declarative,
and the conversion problem applies only to a corpus that nobody is waiting on.

**What would bring it back.** That the old corpus has to move — a longitudinal
follow-up on a finished survey, a re-run, or a question set RCons wants to reuse
rather than re-author. If that happens this is a throwaway script over the real
corpus, still not a production importer, and the number it reports still decides
whether the migration is an afternoon or a fortnight.

**Giving RCons the XLSForm template is now the real dependency**, and it is
small. It belongs with item 0: a builder that produces Form IR and an importer
that consumes XLSForm are the two ends of the same question, which is what a
form is allowed to contain.

---

## 13. Open questions for RCons

1. ~~**Can the questionnaire → CSV tool emit XLSForm?**~~ **Answered, 4
   September 2026: yes, once we give them a template.** It was the
   highest-value question in this list and it turned out to be the one that
   re-ordered the phase — the skip-to conversion applies only to the existing
   corpus (§12), and the template is a dependency of item 0.
2. Do enumerators rely on resuming at **section** granularity, or is resuming
   within a submission enough? `section_progress` suggests the former.
3. When a sample row is updated during collection — `memberAge` beside
   `upMemberAge` — is that a correction to the sample, or a new answer? It
   decides whether the sample must be writable.
4. What does **Person Id** do? If it references a roster member, that is
   cross-repeat referencing and a real feature gap.
5. How many enumerators, questions and days in the next fieldwork? It sizes the
   pilot.
6. What does CERP not get from SurveyCTO? The most valuable competitive
   information available, and it comes from the customer rather than from us.
