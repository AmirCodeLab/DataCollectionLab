# Item 2 — sample assignment and supervisor isolation: the analysis, before the schema

**Status:** analysis, 9 September 2026, approved the same day with A1–A7
(A4 with the escaping rule). The schema is migration 012. It answers
the three questions asked before any route is written, and the one asked
before those: what would pass every test. The decisions it rests on are pilot
scope §4 (`docs/phase3-pilot-scope.md`), the Form IR's `_metadata.case_key`
(§8, and §2.3's refusal of `kind: "dataset"` until it exists), ERD §5 and §7,
and what item 1 settled: scope is a policy on the connection's principal, and
the principal carries the person's authority. Read those first; this does not
restate them.

The order is item 1's, which worked: this document, then the schema and its
policies with their breaks, then the routes, then the screens, then a browser
run and a handset run.

## 0. The three decisions, and the answer to the question in front

1. **Where reassignment lands: nowhere.** Nothing moves. A submission, its
   ops, its visits and a device's draft all stay attached to the case they
   were opened against, and none of them carries a scope. The *assignment* is
   the only row that names a holder, and every policy that decides who sees
   the case's work resolves through the case's live assignment. Reassigning a
   case is releasing one assignment and writing another, in one statement;
   the view moves because the one row it was derived from moved. The previous
   team loses the case and everything collected on it; the new team gains all
   of it, history included; the enumerator who collected a submission keeps
   seeing that submission, because a person always sees work they created.
   Ops in flight are accepted after the move, for the same reason. §4.

2. **Assignment is a policy**, for the reason team scope is: a filter can be
   forgotten in one query, and the first place it would be forgotten is the
   export. The second axis is real and it is what the policy reads: a case is
   *held by a person* (the enumerator's boundary: assigned to me, and nothing
   else) or *held by a team someone assigns within* (the supervisor's
   boundary: my team's cases, because I hold `sample.assign`). Both are one
   expression, `dcp_case_in_scope(case_id)`, and every table under a case
   reads it. §3.2, §5.

3. **A draft is never deleted by an assignment change.** The handset learns
   that a case is no longer assigned to it from the assignments it pulls, and
   what it does is mark the draft, keep it, and let the enumerator finish and
   push it — the server accepts the ops, because they created the submission.
   The only thing the device refuses is *starting* a new submission on a case
   it no longer holds, and the server refuses the same with a policy. Losing
   the draft is the default outcome, and it is closed by two rules: the device
   has no code path that deletes a draft on an assignment, and the server has
   no code path that refuses an op on scope. §4.3, §6.3.

**What would pass every test: the two boundaries drifting apart.** Today
`submission`'s policy reads `created_by`. A case policy that reads assignment
beside it would be two rules for one thing, and reassignment is where they
diverge: the case goes to B, the submission stays with whoever's enumerator
made it, and supervisor A goes on seeing a submission on a case that is B's —
or, if the submission policy were "fixed" to follow the case alone, the
enumerator loses sight of what they collected and cannot push the rest of it.
Every screen test passes either way, because a screen shows a case or a
submission, never the relation. So the rule is: **a submission's visibility is
its case's**, through one function, with `created_by` mattering only for a
submission that has no case and for the person who made it. §2 has the
argument; break 1 in §8 is the test.

## 1. What exists today, plainly

- `case_record` (project, entity, `case_key` unique per project, status,
  priority, location, due_at, closed_at), `assignment` (case → user or team,
  assigned_by, assigned_at, released_at), `visit` (case, sequence,
  form_version) — created by 001, keyed by 008, **unused**: no route writes
  them, no policy beyond the project chain reads them, and `submission.case_id`
  and `visit_id` are never set (ERD §5; pilot scope §4.3).
- `tombstone` already admits `subject_type = 'case'` (ERD §7). The handset
  receives tombstones on every pull as raw JSON and ignores them
  (`WirePullResponse.tombstones: List<JsonElement>`, never read).
- A sample is a dataset version: immutable, content-addressed, one
  `record_key` per row (`dataset_record`), an `ordinal` that does not reach a
  device (defect 16). RCons's sample is 1,129 rows keyed on
  `settlementCode + structureId + hhId`, and their `section_progress` is
  keyed on that plus a section — a case plus a visit plus a status
  (`docs/rcons-current-system.md` §6).
- The handset's submission is `(form_id, form_version, status)`. There is no
  case on the device, no `_metadata.case_key` in the engine's context (the
  engine reads `ctx.metadata` and both engines refuse `kind: "dataset"`
  naming it), and a draft starts from a form, not from a case
  (`SubmissionListViewModel.startSubmission`).
- The pull protocol reserves `scope=assignments` and ignores it (sync §5).
- Item 1's principal: `scope_kind`, `visible_user_ids` (people in my granted
  teams and projects, plus me), `permissions`, `project_ids`, `team_ids`.
  `submission`'s policy: `created_by = ANY(visible_user_ids) OR org-wide`.
  `case_record` and `assignment` carry the project chain: **any project member
  sees every case**, which is the gap this item closes.
- Settled elsewhere and load-bearing here: *the roster filter reads the case
  the enumerator selected from their assigned sample, and a case is chosen
  once and does not change under the enumerator's hand* (pilot scope §13
  question 6). Reassignment does not contradict that: it changes who holds
  the case, not which case a submission was opened against.

## 2. What would pass every test

Three shapes, each of which every screen test passes.

**Two rules for one relation.** A case policy on assignment and a submission
policy on `created_by`. Reassign a case: the case is B's, the submission is
still A's enumerator's, A's export still carries it. Or reverse the second
rule to follow the case: the enumerator who collected the submission can no
longer see it, and the next op they push is refused by WITH CHECK on a row
they cannot see — the draft they are holding becomes unpushable, which is
the silent loss of §0's third decision, arrived at from the server side.

**A filter in the service.** `list_cases(session, supervisor)` joins
`assignment` and filters; `export_form` does not, because nobody thought of
the export as a case screen. Item 1 answered this shape already and the
answer stands: the scope is where a query cannot skip it.

**The device deciding scope.** The handset deletes drafts for cases that
stopped arriving in its assignment pull, on the reasoning that "not assigned"
means "not mine". Every device test passes (the drafts are gone, as designed),
and an enumerator who was mid-interview when a supervisor moved the case
loses the interview. This is the shape §0's third decision forbids, and it is
forbidden structurally: the device's assignment sync has no delete path
for drafts, and the server accepts the push.

The rule that survives all three: **one function decides whether a case is
in the asker's scope, and everything under a case — submissions, ops, visits,
media, quality flags, reviews — is in scope exactly when its case is.** A
submission with no case (opened without a sample, which the pilot allows and
item 0's runs did) is in scope by `created_by`, as now. A person always sees
what they created.

## 3. The model

### 3.1 A case is a sample row, held at two levels

```
dataset_version  (the uploaded sample, immutable, content-addressed)
    │ one case per record_key, made at upload, kept across re-uploads
case_record      case_key = record_key; dataset_key names which sample
    │
assignment       (case, team)   ← the programme manager splits the sample
assignment       (case, user)   ← the supervisor splits their share
    │
submission       case_id set when opened from a case; _metadata.case_key = case_key
visit            one per collection event against the case (ERD §5)
```

- **A case is made from a sample row, once.** Uploading a sample publishes a
  dataset version as today; the same call creates one `case_record` per row
  whose `case_key` is the row's `record_key`, in the row's project. A
  re-upload is a new dataset version: rows with a key the project already
  has keep their case (and its assignments and submissions); new keys make
  new cases; keys that disappeared **close** their case (`closed_at`,
  `status = 'withdrawn'`) and write a `case` tombstone — never delete it, for
  the same reason a person is never deleted (§3.4 of the pilot scope): the
  work collected against it stays explicable. `case_record` gains
  `dataset_key` so a project can hold more than one sample and a case knows
  which it came from; its current row data is the newest version's record
  with its key, read through a view, never copied.
- **Composite keys are composed at upload** (pilot scope §4.4, decided
  here): the upload names the key columns in order (`keyColumns:
  ["settlementCode", "structureId", "hhId"]`), the importer joins them with
  `|` into `record_key` **under Form IR §3.1's escaping rule** — `\` written
  `\\`, `|` written `\|`, split left to right — and the parts stay as
  ordinary columns. The escape is in the spec, not the importer, for the
  reason §3.1's exact-match rule is: a part is the cell's value exactly and
  may contain a pipe, and without the escape `("A|B")` and `("A", "B")`
  collide into one key silently. Composition over widening the schema because
  a case key is an identity the enumerator never types and the roster filter
  compares whole (`$row.case_key = _metadata.case_key`); a three-column
  identity would be three comparisons in every place one is enough. The
  columns are recorded on the dataset (`key_columns` beside the existing
  `key_column`), so an export can split the key back.
- **Two assignment levels, one table.** The programme manager assigns cases
  to a team (`team_id`); the supervisor assigns their team's cases to a person
  (`user_id`). Both are rows in `assignment`, distinguished by which column is
  set, and the CHECK that one of them is set already exists. Two partial
  unique indexes make the levels exclusive per case: at most one live team
  assignment and at most one live person assignment per case. A person
  assignment is valid only under a live team assignment to a team the person
  is in — a policy, §5.
- **Release is a timestamp, never a delete.** `released_at` closes an
  assignment; the row stays, because "who held this case when this was
  collected" is the audit trail item 6 will read. Reassignment releases and
  writes in one SQL function (§4.1).

### 3.2 The second axis

Team scope has one question: is this person in my scope? A case has two:

| Who | Sees a case when | Reads on the principal |
|---|---|---|
| An enumerator | it is assigned to **them** | `app.user_id` |
| A supervisor | it is assigned to their team, or to a person in their team | `app.team_ids`, `app.visible_user_ids`, and `sample.assign` |
| A programme manager | it is in their project, assigned or not | `app.project_ids` |
| An administrator | always | `scope_kind = 'organization'` |

The distinguishing fact between the first two rows is not the scope kind —
both are team-scoped grants — it is the permission. A supervisor sees the
team's cases *because they assign within the team*; an enumerator holds no
permission and sees only what is assigned to them. That is §3.5 of the pilot
scope applied one more time: visibility of other people's work is a
permission, and an enumerator has none. It also corrects item 1's principal
for enumerators: `visible_user_ids` currently includes a team-scoped person's
teammates whether or not they hold `submission.view`, so an enumerator's pull
today carries their teammates' ops. With this item, `dcp_principal_for` puts
teammates in `visible_user_ids` only for a person holding `submission.view`;
an enumerator's visible set is themself. Their pull shrinks to their own
work, which is also what a large reference list on a village connection wants
(item 4).

Unassigned cases — uploaded, not yet split — are visible to the programme
manager and the administrator and to nobody else, with no rule needed:
nobody holds them.

## 4. Where reassignment lands

### 4.1 On the server: the view moves, the rows do not

`dcp_assign_case(case_id, team_id, user_id)` is one SQL function with
**invoker** rights — the caller's policies apply to every statement in it —
and it is the only writer of `assignment`:

```
release every live assignment on the case at the level being written
  (a team assignment also releases the live person assignment: the person was
   in the old team, and a person assignment is valid only under a live team
   assignment to a team they are in — §5's policy would refuse it anyway,
   this just makes the row honest)
insert the new assignment, assigned_by = app.user_id
```

Everything under the case is untouched: `submission.case_id` still names it,
every op still names its submission, every visit its case. What changes is
the answer `dcp_case_in_scope(case_id)` gives each principal, and every
policy under a case asks that function. Supervisor A's list, A's export, A's
monitoring (item 5) and A's review queue (item 6) all lose the case and its
work in the same transaction; B's gain it. There is no second place to
forget.

**History stays with the case, not with the previous holder.** A's team
collected visit 1; after the move, A does not see visit 1. This is a
decision, and it could go the other way (an assignment that overlapped a
submission's `started_at` keeps read access); it does not, because a
time-based scope rule is where the first bug of this kind will hide (device
wall clocks, a released_at written a minute after the last op), and because
the requirement is isolation: §4.2 says A must not see B's sample or B's
submissions, and once the case is B's, its submissions are B's. A's progress
against target (item 5) drops by one case and one submission, which is true.
**Assumption A1, §9.**

**The person who collected a submission keeps seeing it.** `created_by =
app.user_id` is an OR branch of the submission policy, whatever the case's
holder. The enumerator can finish what they started, and the record of what
they did does not vanish from under them. Their supervisor, who sees through
the case, does not keep it; the new team's supervisor sees it through the
case. This is the one asymmetry in the model and it is the one the third
decision needs.

### 4.2 Ops in flight

An op arrives for a submission on a case that moved since the device last
synced. The op is accepted: WITH CHECK on `submission_op` admits an op on a
submission its actor created, and the actor is the session's person (item 1's
attribution). The op is filed, folded, and visible to the case's new holder.
The push response carries nothing special — an accepted op is an accepted op
— and the device learns about the move from its next assignments pull.

An op that would **open** a submission on a case: `submission`'s WITH CHECK
requires a live assignment of that case to the actor. A device that starts an
interview on a case it no longer holds gets that submission's first op
rejected with `not_assigned`, which is the one scope refusal in the push
path, and it applies to new work only. The device refuses the same before it
starts (§6.3), so a person sees this only if they raced the supervisor.

### 4.3 On the handset: the draft is marked, kept, finishable

The device holds a `case` table (§6.2) whose rows are the assignments it
pulled; each pull of `scope=assignments` is a complete statement of the
device's live assignments, like the form manifest (sync §5.1), and that is
how a release is noticed — by absence, the way a withdrawn form version is.
Applying the statement:

- a case that arrived and was not there: inserted, `assigned = 1`;
- a case that was there and did not arrive: `assigned = 0`, `released_seen_at`
  set. **The row stays.** Every draft opened against it stays. The
  submission list shows it under "No longer assigned to you", with the
  sentence: *this case was moved by your supervisor; you can finish and send
  what you started, but not start another visit on it.*
- a case tombstone (`subject_type = 'case'`, the sample row withdrawn): the
  same, with a different sentence.

Nothing in `applyAssignments` deletes a submission, and a test says so
(§8, break 4). The one thing the device refuses is the "Start" action on a
case with `assigned = 0`.

## 5. The policies

The shape of 008 and 010: one helper, one function for the rule, every
table under a case reading it. `dcp_case_in_scope` is SECURITY DEFINER for
the same reason 010's auth-path functions are: a case's policy reading
`assignment`, whose policy reads `case_record`, is a policy recursion
PostgreSQL refuses; the function reads the assignment rows for the case
directly, scoped by the principal's own settings, and is the one rule.

```sql
-- The rule. Read by every policy under a case.
CREATE FUNCTION dcp_case_in_scope(case_id text) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public
    RETURN dcp_org_wide()
        OR EXISTS (SELECT 1 FROM case_record c
                   WHERE c.id = case_id AND dcp_in_list('app.project_ids', c.project_id))
        OR EXISTS (SELECT 1 FROM assignment a
                   WHERE a.case_id = case_id AND a.released_at IS NULL
                     AND (a.user_id = dcp_principal('app.user_id')
                          OR (dcp_has('sample.assign')
                              AND (dcp_in_list('app.team_ids', a.team_id)
                                   OR dcp_in_list('app.visible_user_ids', a.user_id)))));

-- Cases: seen in scope; made by the sample upload (sample.upload, in the
-- project); closed, never deleted.
SELECT dcp_policy('case_record',
    'dcp_case_in_scope(id)',
    'dcp_has(''sample.upload'') AND (dcp_org_wide() OR dcp_in_list(''app.project_ids'', project_id))');
SELECT dcp_restrict('case_record', 'never_deleted', 'DELETE', 'false');

-- Assignments: seen with the case; written within the assigner's scope, at
-- the level their scope allows: a team, to a team in my project; a person,
-- to a person I may see, under a live team assignment to a team they are in.
SELECT dcp_policy('assignment',
    'dcp_case_in_scope(case_id)',
    'dcp_has(''sample.assign'') AND dcp_case_in_scope(case_id) AND ('
    '   (team_id IS NOT NULL AND user_id IS NULL'
    '      AND (dcp_org_wide() OR team_id IN (SELECT t.id FROM team t WHERE dcp_in_list(''app.project_ids'', t.project_id))))'
    ' OR (user_id IS NOT NULL AND team_id IS NULL'
    '      AND (dcp_org_wide() OR dcp_in_list(''app.visible_user_ids'', user_id))'
    '      AND dcp_person_under_live_team(case_id, user_id)))');
CREATE UNIQUE INDEX assignment_live_team_idx ON assignment (case_id)
    WHERE released_at IS NULL AND team_id IS NOT NULL;
CREATE UNIQUE INDEX assignment_live_person_idx ON assignment (case_id)
    WHERE released_at IS NULL AND user_id IS NOT NULL;

-- Submissions: the case's scope when there is a case; the creator's own,
-- always; the team's uncased work for someone who may see it. Opening one
-- against a case needs that case assigned to me.
SELECT dcp_policy('submission',
    'project_id IN (SELECT id FROM project) AND ('
    '   dcp_org_wide()'
    ' OR created_by = dcp_principal(''app.user_id'')'
    ' OR (case_id IS NOT NULL AND dcp_case_in_scope(case_id))'
    ' OR (case_id IS NULL AND dcp_has(''submission.view'')'
    '     AND dcp_in_list(''app.visible_user_ids'', created_by)))',
    'project_id IN (SELECT id FROM project) AND ('
    '   dcp_org_wide()'
    ' OR (created_by = dcp_principal(''app.user_id'')'
    '     AND (case_id IS NULL OR dcp_case_assigned_to_me(case_id))))');
-- submission_op, submission_state, media, quality_flag, review: unchanged —
-- they chain through submission, which now carries the case's scope.
-- visit: dcp_case_in_scope(case_id). device: seen by the project's managers
-- and the bound person's supervisors; an unbound device is nobody's yet.
```

`dcp_case_assigned_to_me` and `dcp_person_under_live_team` are the two
smaller definer functions the policies above name; both read `assignment`
and `project_member` for one case, scoped by the principal. `dcp_assign_case`
(§4.1) is invoker-rights and goes through the assignment policy like any
other writer; the service calls it and maps the policy's refusal to 403
`outside_your_authority`, item 1's shape.

**The principal changes in one place**: `dcp_principal_for` puts teammates in
`visible_user_ids` only for a person holding `submission.view` (§3.2). Nothing
else on the principal changes; the case policies read what is already there.

## 6. Sync and the handset

### 6.1 `scope=assignments`

Implemented as sync §5 reserved it: on the first page of a pull that asks for
it, the device's live assignments as a **complete statement** — every case
assigned to the device's person, with the case's key, status, priority,
due_at, the sample row it came from (the newest version's record data, so a
roster can be preloaded and a settlement name shown), and the dataset key and
version it belongs to. Complete rather than a delta for the reason the form
manifest is (sync §5.1): a release is an absence, and no stream of additions
can say "you no longer hold this". Paged when the person holds more than a
page; the page says it is complete when it ends.

Item 4 (separate sync for sample and form) is what makes this an explicit
action with its own progress rather than part of one Sync button. Nothing
here prevents that split; `scope` already separates the three.

### 6.2 The device's `case` table

```sql
CREATE TABLE case_record (
    case_id TEXT NOT NULL PRIMARY KEY,
    case_key TEXT NOT NULL,
    dataset_key TEXT NOT NULL,
    data TEXT NOT NULL,            -- the sample row, JSON
    status TEXT NOT NULL,          -- open | closed | withdrawn, as the server says
    assigned INTEGER NOT NULL,     -- 1 while the last statement carried it
    released_seen_at TEXT,         -- when the device noticed it was gone
    first_seen_at TEXT NOT NULL
);
ALTER TABLE submission ADD COLUMN case_id TEXT REFERENCES case_record (case_id);
```

A draft opened from a case carries `case_id`; the engine's context gets
`_metadata.case_key` from it, which is the first of the two conditions Form IR
§2.3 names for `kind: "dataset"` (the other is defect 16, which this item does
not touch: cases are listed by key and priority, and only a roster needs a
row order). The submission's first op carries `caseId` on the wire so the
server sets `submission.case_id` when it creates the row, the way it sets
`created_by`.

### 6.3 What the device refuses, and what it never does

- It refuses to **start** a submission on a case whose `assigned = 0` or whose
  status is not `open`, with the sentence in §4.3. The server refuses the same
  (§4.2), so a device that is wrong about its assignments is refused by the
  policy and not by its own bookkeeping.
- It **never deletes a submission** in `applyAssignments` or on a case
  tombstone, and never blocks a push on assignment. A draft on a released
  case is marked and listed; finishing it pushes; the ops are accepted.
- It never shows another person's cases, because it never receives them: the
  statement is the person's, and the person's pull of ops is their own work
  (§3.2).

## 7. Routes and screens, in outline

Routes, each declaring its access, each write a statement in a savepoint:
`POST /projects/{id}/samples` (upload = publish a dataset version + make
cases; `sample.upload`), `GET /cases?projectId=` (in scope; any of
`sample.assign`, `sample.upload`, `submission.view`), `POST /cases/{id}/assign`
(`sample.assign`; body names a team or a person; the function decides the
rest), `POST /cases/bulk-assign` (the split: a list of case ids to one team or
person — the programme manager's and the supervisor's everyday action).
`GET /sync/pull?scope=assignments` as §6.1. The existing export reads
submissions and inherits the scope with no change, which is the point.

Screens: the console's Sample page — upload, the split by team for a PM, the
split by person for a supervisor, each seeing only what they hold; a case
list with its holder and its progress. The handset's "Assigned to me" list,
start from a case, and the "No longer assigned to you" section.

## 8. Breaks, to be run for real when the tests exist

1. **The two boundaries drifting.** Reassign a case with a finalised
   submission from team A to team B. As A's supervisor: the case, the
   submission, and the export's rows for it are all gone. As B's: all three
   are there. As A's enumerator who collected it: the submission is still
   visible, the case is not. One function answers all of them.
2. **An op in flight after a move.** The old enumerator pushes another op on
   that submission: accepted, attributed to them, visible to B.
3. **New work on a case I do not hold.** The same enumerator's device opens a
   new submission on the moved case: the first op is rejected `not_assigned`
   by the policy; the device would have refused it first.
4. **A draft on an unassigned case.** Release the assignment; the device pulls
   assignments; the draft is still in the database, listed under "no longer
   assigned", and pushes. A test asserts `applyAssignments` cannot delete a
   submission by construction — the query does not exist.
5. **Who sees which cases.** The PM sees the whole sample; supervisor A sees
   team A's, unassigned cases invisible to them; supervisor B likewise; each
   enumerator only their own; an enumerator's pull carries no teammate's ops.
6. **A filter, not a policy.** Drop the case branch from `submission`'s policy
   and keep the case list correct: the export is wrong and the export test
   says so.
7. **Re-upload of the sample.** Same keys keep their cases and assignments;
   a withdrawn key closes its case and tombstones it; the device marks the
   draft and keeps it.
8. **The composite key.** Upload with `keyColumns` of three; the case key is
   `a|b|c`; the export splits it back; a row whose key columns are blank is
   refused at upload, naming the row.

## 9. Assumptions the analysis was written under — say if any is wrong

- **A1.** History follows the case: the previous team loses sight of visits
  collected while they held it (§4.1). The alternative is an overlap rule on
  timestamps, argued against there.
- **A2.** An enumerator sees only their own work — their assigned cases and
  the submissions they made — and their pull is only that. Approved, and the
  half of it that was a live leak is defect 26, fixed on PR #46 ahead of this
  item.
- **A3.** A case is assigned to at most one team and at most one person at a
  time. Two enumerators on one household is two visits on one case held by
  one of them, or the case moved between them; it is not two live holders.
- **A4.** The composite key is composed at upload with `|` under Form IR
  §3.1's escaping rule (backslash escapes; approved with the escape added 9
  September 2026), and recorded so it can be split (§3.1). The parts remain
  columns.
- **A5.** A sample's writable columns (`upMemberAge` and the rest,
  `docs/rcons-current-system.md` §6) are answers, not sample edits: the import
  leaves them out of the dataset and the form collects them. Nothing in this
  item makes the sample writable.
- **A6.** Unassigned cases are visible to programme managers and
  administrators only. A supervisor cannot see the pool the PM has not split.
- **A7.** This item does not fix defect 16 (row order). It delivers
  `_metadata.case_key`, the other half of what a sample-preloaded roster
  waits on.
