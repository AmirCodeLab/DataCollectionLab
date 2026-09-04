# Phase 3 — the pilot scope

**Goal:** RCons runs a small real pilot on DCP.
**Decided:** 4 September 2026
**Status:** scope, agreed. Sequencing inside it is open.

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
declarative relevance. They are not mechanically interchangeable. This is the
only item in Phase 3 whose cost is unknown, and it is cheap to find out — so it
goes first.

---

## 2. Item 0 — the skip-to prototype

**Before anything else is scheduled.**

Take the 2,128 questions in the Sindh listing database and convert their skip
rules to declarative relevance. Count what converts cleanly and read the
residue.

```
q8==1 to q10
q11==2 to q12a, q10<=6 to q12b, q10<15 to endSection, q11 to q13
```

Read as: *after this question, if q11==2 go to q12a; otherwise if q10<=6 go to
q12b; otherwise if q10<15 end the section; otherwise go to q13.*

A single rule determines the relevance of every question it jumps over, not
just its target. Chains compose. Some sets — backward jumps, overlapping
conditions — have no single declarative reading.

**Deliverable:** a number. The percentage that converts without manual work,
and a list of the shapes that do not.

That number decides whether importing an RCons questionnaire is an afternoon or
a fortnight, and therefore whether the pilot is one month away or three.

**Do not build the production importer yet.** A throwaway script over the real
corpus answers the question; the Migration Center integration follows once the
answer is known.

---

## 3. Item 1 — identity and permissions

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

## 5. Item 3 — the roster gap

RCons's roster is DCP's `repeat`. Three ways of deciding the count:

| How | DCP today |
|---|---|
| From an earlier answer — "how many live here?" | `countExpr` — works |
| From the sample — a column giving the number | `countExpr` over a dataset value — works |
| **The enumerator decides as they go** | **Missing** |

The third is the common case for a household member roster: keep adding until
the respondent says stop. `minInstances` and `maxInstances` exist; what is
missing is the user-driven add.

Small, and blocking — a household listing cannot be collected without it.

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
  is not doing paper entry yet, but wants it — this is the next phase.
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
| 0 | Skip-to prototype | The only unknown cost. Cheap to resolve |
| 1 | Identity and permissions | Everything below depends on it |
| 2 | Sample assignment and isolation | The daily work of a survey firm |
| 3 | User-driven roster | Small, and blocks household listing |
| 4 | Separate sample/form sync | Field usability |
| 5 | Supervisor monitoring | Fieldwork needs oversight from day one |
| 6 | Review and correction | Closes the quality loop |

Items 1–6 are roughly two months. Item 0 could change that, in either
direction, which is why it is first.

---

## 11. Open questions for RCons

1. **Can the questionnaire → CSV tool emit XLSForm?** If yes, the skip-to
   problem applies only to the existing corpus, not to everything written from
   now on. This is the highest-value question in the list.
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
