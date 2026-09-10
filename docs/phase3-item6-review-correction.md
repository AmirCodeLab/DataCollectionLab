# Phase 3 item 6 — review and correction

Analysis, before any code. The scope is pilot scope §8: automated quality rules
run on arrival; flagged submissions go to a queue and clean ones do not, by
project policy; approve, reject or request correction with a reason; and a
rejection returns to the enumerator's device as work. It is also what finally
gives item 5's quality-flag card a writer.

---

## 0. The decisions, and the answer to the question in front

**The question.** *What passes every test here?* The guess in front of this
item was that a correction round-trips as a **new** submission rather than the
same one, so the export carries both and an analyst counts a household twice.

That guess names the right pressure, and it is worth saying exactly where the
pressure comes from: the handset has no re-open path, its local status
vocabulary is two words long (`draft`, `finalized`), and a finalized submission
is read-only on every mutating path in the collection view model. Given a
ticket that says "send it back to the enumerator", the cheapest implementation
in this codebase is to create a second submission on the same case and let the
first one lie there. Every unit test passes. The export then has two rows for
one household, and the only thing distinguishing them is a timestamp.

**But the schema already refused that, in 001, and nobody has used the
refusal.** `submission_op.op_kind` has admitted `reopen` since the first
migration; `fold_ops` folds it to `draft` on the server and
`SubmissionStore.appendOp` writes the same status on the handset; and the push
path carries this comment, which is the decision already made and never
exercised:

```python
# A submission in a terminal review state accepts no further ops. finalized is
# NOT terminal: corrections after finalisation are how the review loop works.
_CLOSED_STATUSES = {"approved", "rejected"}
```

So the answer to the guess is: **a correction is the same submission, and the
machinery for that is already built and dead.** Nothing in the repository emits
a `reopen` op, and nothing writes `in_review`, `approved`, `rejected` or
`correction_required` — those four statuses exist in a CHECK constraint, a
Pydantic literal, two read filters and item 5's `COVERED_STATUSES`, and have
never been written by anything.

**The failure that would actually ship is one step further on, and it is worse
than a double count because it is silent.** Here is the whole of it, in the
code as it stands:

```python
# Ops only move a submission between draft and finalized; review states
# (in_review, approved, ...) belong to the review workflow, not to sync.
if folded.status is not None and submission.status in ("draft", "finalized"):
    submission.status = folded.status
```

A submission that has left `draft`/`finalized` can never come back. The moment
a reviewer writes `correction_required`, that guard stops matching, and it
never matches again. The enumerator's device is not in `_CLOSED_STATUSES`, so
its ops are **accepted**; the fold runs; `submission_state.data` updates with
the corrected answers; and the status stays `correction_required` for ever.
The corrected household never re-enters the review queue, never becomes
`approved`, and — because `COVERED_STATUSES` is `finalized`/`in_review`/
`approved` — never counts as covered on the supervisor's dashboard again. The
supervisor sees an enumerator who owes a household they have already redone,
the reviewer sees nothing waiting, and the data is correct in the database the
whole time. Nothing errors. Item 5's lesson, one item on: correct per row,
wrong in aggregate.

The decisions below exist to kill that, and the double count, and four others
in §2.

**D1 — a correction is the same submission. Identity survives everything.**
One household visit is one `submission.id` for its whole life, however many
review rounds it goes through. The op log is append-only and per submission, a
correction appends to it, and the audit trail the review depends on is that log
plus the `review` rows beside it. Nothing creates a second submission for the
same work, and the export therefore has nothing to deduplicate — which is the
only way to be sure it does not deduplicate wrongly. §3.1.

**D2 — one status, two authors, one reconciler.** `submission.status` has two
kinds of writer: the device, through the fold (`finalize`, `reopen`), and the
reviewer, through a decision. They are not two columns and not two state
machines. There is exactly one function that decides what a status may become,
it takes the current status and the event, and both writers go through it. The
guard quoted above becomes that function's `draft`/`finalized` row rather than
an `if` at a call site — because an `if` at a call site is how the freeze got
there. §3.2.

**D3 — a rule that could not run is not a pass.** The server cannot read a
`field_level` or `project_e2e` submission: the console decrypts in the
browser with a key the server has never held. `Fold` already records exactly
which paths are ciphertext, in `unreadable`. So a rule whose expression
references an unreadable path is reported as **not evaluated**, never as clean,
and a submission whose rules could not run is not called "no flags". This is
item 5's A7 in its general form — a zero that could never have been anything
else — and it is the one that decides whether the flags card can be trusted at
all. §3.3.

**D4 — the queue is derived, not a table.** "Flagged submissions go to a queue"
is a filtered list of submissions, computed under the same policy path as every
other list, exactly as item 5's numbers are. No queue table, no worker, no
copy of a submission's state that can drift from the submission. `workflow_*`
exists in the schema and stays empty: SLAs and escalation are V1.5 by §9, and
the moment a queue is a table somebody has to keep it in step. §3.4.

**D5 — a quality rule is an IR expression, evaluated by the engine that is
already here.** `quality_rule.definition` is `jsonb`; the IR expression
language is JSON; the evaluator exists in Python and Kotlin and is held to 116
conformance vectors. RCons's `plausible_ranges.json` is 34 KB of range checks,
which is `gte`/`lte`/`and` and nothing exotic. Inventing a second expression
language here would put two evaluators in one product, which is the drift the
whole architecture is arranged to prevent. §3.3.

**D6 — the device learns by op, not by a status field on the wire.** A device
finds out that work has come back the same way it finds out anything else:
ops arrive in the pull. That keeps one source of truth for what happened to a
submission, and it means the handset's local status is computed by the same
fold rule the server uses instead of by a second field that can disagree with
the log beside it. §3.5, and it is the part of this item with the most
handset work in it.

---

## 1. What exists today, plainly

**Written and working.**

- `submission_op` is append-only, per submission, ordered by
  `(counter, device_id)`, with `finalize` and `reopen` among its six kinds.
- `fold_ops` is one shared implementation, used by sync and by export. It
  folds `finalize` to `finalized` and `reopen` to `draft`, and records
  `unreadable` paths separately from absent ones.
- `_CLOSED_STATUSES = {"approved", "rejected"}` refuses ops on a closed
  submission with a named reason, `submission_closed`.
- The console's submission detail already shows the folded state and the op log
  it came from, and decrypts in the browser when it has a key.
- `submission.review` is a real permission on the principal, understood by
  `access()`.

**Declared and dead.**

- `quality_rule`, `quality_flag` and `review` exist since 001 with ORM models
  and **no service, no routes, no writer**. Item 5 renders no flags card for
  exactly this reason.
- `workflow_definition` / `workflow_instance` / `workflow_transition`: same,
  and they stay that way in this item.
- `submission_snapshot`: declared, migrated, never written or read.
- Four of the six submission statuses have never been written.
- `reopen` has no emitter anywhere — not in the console, not on the handset.
- `_CLOSED_STATUSES` is therefore unreachable, and `submission_closed` is a
  refusal that cannot currently happen.

**Not there at all.**

- Any evaluation of a rule against a submission, on either side.
- Any way for a reviewer to record a decision.
- Any way for a device to learn that a decision was made.
- `SubmissionStatus` on the handset knows two words. `applyPullBatch` never
  touches local status, so even a `reopen` op arriving in a pull today would
  leave the handset's own status wrong.

**Two things the spec left open that this item has to answer.**

- Sync protocol §11: *"Whether `finalize` should be a hard barrier or a soft
  state."* D2 answers it: soft, with the transitions enumerated.
- Sync protocol §6: two devices editing the same field after finalisation
  *"surface in a supervisor merge UI. They are never silently resolved."*
  `_fold_submission` resolves them silently, last writer wins. This item does
  not build a merge UI, and §8 says so rather than leaving the spec's sentence
  looking implemented.

---

## 2. What would pass every test

The naive item 6 is a `POST /submissions/{id}/review` that writes a row and sets
a status, a rules runner in the push path, and a queue page. Every unit test
passes. Here is what that ships.

**1. The frozen submission.** The one in §0. A reviewer asks for a correction,
the enumerator redoes the household, the ops are accepted, and the status never
moves again. No error, no exception, no failing test — the submission simply
leaves the queue and the coverage figure for ever. This is the default
behaviour of the code as written today, so it ships unless something is done
about it deliberately.

**2. The second submission.** The correction is returned as new work, which is
the cheapest thing to build because the handset already knows how to start
work. The export writes two rows for one household. Nothing is corrupt; the
count is just wrong, and it is wrong in the direction nobody checks, because
"more data than expected" reads as a good sign.

**3. The clean bill nobody could have given.** Rules run on arrival. For an
encrypted project the server reads ciphertext, every rule evaluates to null,
null is not a violation, and the submission is reported with no flags. The
reviewer sees a queue that is empty because nothing could be checked, and the
supervisor's flags card reads 0. This is a false statement with a number on it,
and it is worse than item 5's version because a human has now approved on the
strength of it.

**4. The rule that changed after the fact.** A rule is edited, or disabled, and
the flags it raised last week stay on submissions that were reviewed under it —
or are recomputed, and a submission a supervisor approved yesterday is flagged
today with no record of why it changed. Either behaviour is defensible; having
neither written down is not, and a `quality_flag` row that does not say which
version of which rule produced it cannot tell the two apart afterwards.

**5. The review that outran the work.** A reviewer approves a submission while
the enumerator's handset holds three unsynced ops for it. They arrive after the
approval, `_CLOSED_STATUSES` refuses them, and the enumerator sees ops rejected
with a reason that mentions a review they were never told about. The rejection
is correct. What is missing is that the device was never told the work was
closed, so it kept collecting into it.

**6. The queue that is one person's opinion.** The queue is scoped by
`submission.view`, and a supervisor sees their team's flagged work — but the
seed grants `submission.review` to Admin and Programme Manager and **not** to
Supervisor. So either the queue is visible to people who cannot act on it, or
it is invisible to the people who do the acting in RCons's actual workflow.
Whichever it is, it is a decision, and the seed currently encodes one nobody
made deliberately.

**7. The reason that never reached anybody.** "Request correction with a
reason" writes the reason to `review.comment`, and the handset has no field to
show it. The enumerator gets work back with no idea what was wrong, does the
same thing again, and the round trip repeats. The reason is the entire point of
the feature; a reason stored where the person who must act on it cannot read it
is not stored.

Failure 2 is the one the brief predicted. Failure 1 is the same family and is
what the code does today. D1–D6 kill all seven.

---

## 3. The model

### 3.1 Identity: one submission, one log

A submission is its op log. The log is append-only, keyed to one
`submission.id`, and ordered by `(counter, device_id)` — never by wall clock,
never by arrival. A correction appends to that log. It does not start another
one.

That is not a preference; it is the only version that survives contact with the
export. **The export has no `case_id` and no `case_key` column.** Its metadata
columns are `submission_id`, `form_id`, `form_version`, `submission_status`,
`device_id`, `created_by`, `started_at`, `finalized_at`, `received_at`, and
that is the complete list. A case key reaches a form only as
`_metadata.case_key` for expressions, so it lands in a file only if an author
wrote a field to hold it.

So if a correction were a second submission, the two rows for one household
would be distinguished **only by `submission_id`**, and there would be nothing
in the file an analyst could group on to notice. Not a hard dedupe problem — no
dedupe problem, because the information needed to see the duplicate is not in
the output at all. And it would not show up on the way there either: item 5's
coverage counts a case as covered if *any* submission on it has a covered
status (`count(*) FILTER (WHERE EXISTS ...)`), so two submissions on one case
count once on the dashboard and twice in the export. The failure is invisible
in the place somebody would look for it.

One submission for the life of the work, therefore, and the export needs no new
column to be right. Whether it should *gain* a case column is a separate
question and §8 leaves it open rather than smuggling it in here.

**What identity survives.** `submission.id`, `case_id`, `form_version_id`,
`created_by`, `origin_device_id`, `started_at` and the whole op log survive
every review round unchanged. `status`, `finalized_at`, the folded state and
the set of open flags are the things that move. A correction is a change of
answers and status, not a change of subject.

### 3.2 The status machine, and who may move what

Today `submission.status` is written in two places and constrained by an `if`
at the call site:

```python
if folded.status is not None and submission.status in ("draft", "finalized"):
```

That line is correct about its intent — sync must not overwrite a review state
— and wrong as a mechanism, because it expresses "which states sync may leave"
and silently also decides "which states anything may leave". A review state is
a one-way door, and nothing says so anywhere.

**The decision: one function, `next_status(current, event) -> str | Refusal`,
and both writers go through it.** Two events come from the device's fold
(`finalize`, `reopen`) and four from a reviewer (`approve`, `reject`,
`request_correction`, `comment`). The table it encodes, proposed:

| from | `finalize` | `reopen` | `approve` | `reject` | `request_correction` |
|---|---|---|---|---|---|
| `draft` | `finalized` | `draft` | refuse | refuse | refuse |
| `finalized` | `finalized` | `draft` | `approved` | `rejected` | `correction_required` |
| `in_review` | `finalized` | `draft` | `approved` | `rejected` | `correction_required` |
| `correction_required` | **`finalized`** | `draft` | `approved` | `rejected` | `correction_required` |
| `rejected` | refuse | refuse | refuse | refuse | refuse |
| `approved` | refuse | refuse | refuse | refuse | refuse |

The bold cell is the fix for failure 1: a `finalize` op on a submission in
`correction_required` returns it to `finalized`, which puts it back in the
queue and back into item 5's coverage. Everything else is what the code already
does, written down where it can be tested.

`in_review` is included because the column already admits it, but this item does
**not** introduce a claim/lock step: nothing writes `in_review` unless §5's
screens turn out to need it, and if nothing writes it the row costs nothing.
`approved` and `rejected` stay terminal, which is what `_CLOSED_STATUSES`
already says — and, once anything can write them, `submission_closed` stops
being a refusal that can never happen.

A refusal is named, not silent: a reviewer acting on a submission somebody else
has already closed gets a reason, in the shape item 2 and item 4 use for theirs.

### 3.3 Rules: the language, when they run, and what "could not run" means

**The language is the IR expression language.** `quality_rule.definition` is
`jsonb`; IR expressions are JSON; `evaluate(expr, EvalContext)` exists in
Python and in Kotlin and is held to the same 116 conformance vectors. Its
`EvalContext.values` is a `Mapping[str, Any]` — which is precisely the shape of
a fold's `data`. RCons's `plausible_ranges.json` is 34 KB of range checks, and
a range check is `and(gte(ref, lit), lte(ref, lit))`. There is no second
language to design and no second evaluator to keep in step, which is the whole
argument.

**When they run: on arrival, in the push transaction, against the fold that
push has just computed.** The fold already happens there, once per touched
submission. Evaluating rules beside it means a flag can never describe a state
the submission was never in. No worker, no queue, no eventual consistency — the
same reasoning as item 5's D1.

**What a rule that cannot run must say.** For a `field_level` or `project_e2e`
project the server holds ciphertext and no key: the console decrypts in the
browser, and `Fold.unreadable` already names every path whose current value the
server cannot read. So:

- A rule whose expression references a path in `unreadable` is **not
  evaluated**. It does not pass and it does not fail.
- A submission is described as "no flags" only when every enabled rule for it
  actually ran. Otherwise it is "N rules could not be checked", and that is
  what the queue and the console show.
- Item 5's flags card follows the same rule it already follows: a count that
  could not be a measurement is not rendered as one. `flagsOutstanding` stays
  `null` for a project where nothing could be evaluated, rather than becoming a
  reassuring `0`.

This is the single most consequential decision in the item, because a reviewer
approving on the strength of an empty flag list is the failure that turns a
quality feature into a quality risk.

**Whether rules should also run on the handset at finalisation** — which is the
only place an encrypted project's answers are readable — is named here and
**not built in this item**. It is the right long-term answer and it is a second
evaluator's worth of work at the wrong moment: the engine is there, but the
rule set has to reach the device, the flags have to come back as something, and
that is its own sync design. §8.

**Which rule raised which flag, and when.** `quality_flag` carries `rule_id`
with `ON DELETE SET NULL`, which loses the answer exactly when it matters. A
flag records the rule's identity *and* its definition at the moment it was
raised, so a rule edited or disabled later cannot rewrite the history of a
review that was made under it (failure 4). Re-evaluation on a later push
resolves flags that no longer hold and raises new ones; it never edits an
existing row.

### 3.4 The queue

A filtered list of submissions, computed under the request's principal through
the same policy path every other list uses. No queue table, no worker, no
projection to keep in step. `workflow_definition` / `workflow_instance` /
`workflow_transition` stay empty: SLAs and escalation are V1.5 by scope §9, and
a queue that is a table is a second answer to a question the submission table
already answers.

"Clean ones do not go to the queue, by project policy" is one project setting
with two values — review everything, or review only what is flagged — and it
changes the filter, not the shape. It has to be a setting rather than a
constant because reviewing everything is what makes SurveyCTO slow and is
exactly the thing RCons is buying their way out of, but a pilot will want to
watch the rules for a week before trusting them.

### 3.5 Returning work to the device

The pull sends **ops and tombstones, and nothing else** — no submission row, no
status, no `case_id`. So there is exactly one way a decision can reach a
handset, and it is the one D6 names: as ops in the stream the device already
consumes.

A rejection or a correction request therefore emits a `reopen` op on the
submission, and the enumerator's next sync brings it down like any other op.
The device folds it, the submission becomes a draft again, and the collection
screen stops refusing to edit it. The reason travels beside it — see below.

**Three things are broken on the handset for this and have to be fixed in this
item.**

1. `applyPullBatch` never touches local status. A pulled `finalize` or `reopen`
   leaves the device's own `submission.status` as it was, so today a device
   would receive a reopen and show the submission as still finalized. Local
   status has to be folded from the log the same way the server folds it, not
   written imperatively only for locally-recorded ops.
2. `insertSubmissionIfAbsent` writes `case_id NULL`, so a submission arriving
   from the server has no case on the device and cannot be shown under the case
   it belongs to. Returned work is exactly the case where that matters.
3. The list has two sections, "Assigned to me" and "No longer assigned to you —
   drafts kept". Work sent back is neither. It needs to be visible as work
   without pretending to be a new assignment.

**Whose op is it?** `submission_op.device_id` is `NOT NULL` and
`UNIQUE (device_id, counter)` is global per device. A reviewer has no device, so
a review-authored op needs either a synthetic device row per person — a lie in
the device panel item 5 just built — or the op must be authored by something
that legitimately has one.

The proposal is the third option: **the reviewer's decision is not an op.** It
is a `review` row plus a status transition through §3.2, and the server emits
the `reopen` op on the submission's own `origin_device_id`, with `actor_id` set
to the reviewer, at a counter the server allocates for that device. That keeps
`device_id` honest — it is the device the work lives on — and puts the person
in `actor_id`, which is what `actor_id` is for. The counter allocation is the
one genuinely delicate part, because a device that is offline is also
allocating counters, and §4 has to say how they cannot collide.

**And the reason has to arrive with it.** "Request correction with a reason" is
the whole feature; a reason that stops at `review.comment` on the server is not
delivered. The reason travels to the device and is shown on the submission
before the enumerator opens it (failure 7).

### 3.6 What item 5 starts showing

Nothing in item 5 changes shape. Its `flags_outstanding()` returns `None` when
no rule exists and a count otherwise, and the card appears the moment a project
has one — which is the behaviour A7 was written for. The only addition is D3's:
`null` also when nothing could be evaluated, so an encrypted project does not
get a reassuring zero.

Coverage repairs itself once §3.2's bold cell exists: `rejected` and
`correction_required` are already outside `COVERED_STATUSES` with the comment
"have come back and are work again", so a case uncovers when work is sent back
and covers again when it returns finalised.

---

## 4. Schema, in outline

Migration 016, and it is small — most of this item is behaviour over tables
that have existed since 001.

- `quality_flag` gains what it needs to be honest about provenance: the rule's
  definition as evaluated, and a run identity so "not evaluated" is a fact
  rather than an absence. Exact columns with the schema.
- A per-project review policy setting: review everything, or review only
  flagged. One column on `project`, not a settings table.
- Row-level security on `quality_rule`, `quality_flag` and `review`. All three
  are unpoliced today because nothing writes them; a flag chains to its
  submission and inherits item 2's scope, a rule chains to its project. This is
  the same shape as every other policy and is the part that must not be
  improvised.
- `review.reviewer_id` is `text` with no foreign key. Whether that becomes a
  real reference is decided with the migration.

**No new table.** If this item ends up adding one, that is the signal to stop
and re-read §3.4.

---

## 5. Routes and screens, in outline

- `POST /submissions/{id}/review` — one decision, gated on `submission.review`,
  refusing by name. The only writer of review states.
- `GET /submissions` gains the queue's filters (flagged, status, mine to
  review) on the list route that already exists, rather than a second list.
- `GET/POST/PATCH /quality/rules` — a project's rules, gated on
  `project.manage`, with a validate-before-save that compiles the expression
  through the same compiler the form builder uses.
- Console: the review queue as a filter on the submissions screen; the decision
  controls and reason on the submission screen, beside the flags; the rules
  screen. Every flag says which rule raised it and, where it could not run,
  says so in those words.
- Handset: returned work visible as work, the reason shown before it is opened,
  and a finalized submission that has been reopened editable again.

---

## 6. Breaks, to be run for real when the tests exist

1. Remove §3.2's `correction_required → finalized` transition. The corrected
   submission never returns to the queue and never re-covers its case — the
   failure this item exists to prevent, and the one the code does today.
2. Make a correction create a new submission. The export writes two rows for
   one household with nothing to join them on.
3. Report a rule that could not be evaluated as passed. An encrypted project's
   queue is empty and its flags card reads zero.
4. Let a reviewer's decision write `submission.status` directly instead of
   through `next_status`. A submission moves out of `approved`.
5. Drop the reason from what reaches the device. The enumerator gets work back
   with no statement of what was wrong.
6. Keep `applyPullBatch` from folding status. A reopened submission stays
   read-only on the device that has to correct it.
7. Resolve a flag on re-evaluation by editing the row instead of resolving it.
   The history of a review made under the old rule is rewritten.

---

## 7. Assumptions this analysis was written under — say if any is wrong

**A1.** A correction is the **same** submission: same id, same case, same op
log, appended to. Nothing creates a second submission for the same work, and
the export needs no new column to be right about it.

**A2.** `submission.status` is one column with one transition function, and
both the fold and the reviewer go through it. `approved` and `rejected` are
terminal; `correction_required` returns to `finalized` on the next `finalize`.

**A3.** Quality rules are IR expressions evaluated by the existing engine, in
the push transaction, against the fold that push just computed. No new
expression language, no worker, no eventual consistency.

**A4.** A rule that could not be evaluated — because the server cannot read the
value — is reported as *not evaluated*, never as passed, and a submission is
"clean" only when every enabled rule actually ran. Item 5's card stays `null`
rather than `0` for such a project.

**A5.** The queue is a filtered list under the existing policy path, not a
table. `workflow_*` stays empty in this item.

**A6.** A decision reaches the device as a `reopen` op in the ordinary pull,
authored on the submission's own `origin_device_id` with the reviewer in
`actor_id` — not as a new wire field, and not by inventing a device for the
reviewer. The counter allocation is a schema problem §4 must solve explicitly.

**A7.** The reason travels with the work and is shown on the handset before the
submission is opened.

**A8.** Rules do **not** run on the handset in this item, so an end-to-end
encrypted project gets review and correction but not automated flagging. Named,
not built.

**A9.** `submission.review` currently belongs to Admin and Programme Manager
and not to Supervisor. RCons's reviewers are supervisors. **This analysis
assumes the seed is wrong and Supervisor gains `submission.review`** — say if
the pilot means it the other way, because it changes who the queue is for.

---

## 8. What this item does not touch

- **The merge UI.** Sync protocol §6 says conflicting edits after finalisation
  "surface in a supervisor merge UI" and "are never silently resolved". The
  fold resolves them silently, last writer wins, and will continue to. Named
  here so the spec's sentence is not read as implemented.
- **Snapshots.** `submission_snapshot` stays unwritten; the fold still replays
  the whole log.
- **A case column in the export.** Arguable, and a change to a file format
  people already parse. Separate.
- **`workflow_*`, SLAs, escalation.** V1.5 by scope §9.
- **The engine, the IR, encryption.** Untouched. This item consumes the
  expression evaluator; it does not extend it.
