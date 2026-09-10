# Phase 3 item 5 — supervisor monitoring

Analysis, before any code. The scope is pilot scope §7: progress against
target by enumerator and by area, submissions per day, quality flags
outstanding, devices with last sync and pending ops — within the supervisor's
scope only. This is also where device scoping lands, which migration 012
parked here deliberately.

---

## 0. The decisions, and the answer to the question in front

**The question.** *What passes every test here?* The guess in front of this
item was a count that is correct per screen and wrong in aggregate: a
dashboard summing rows the policy hides, so the total disagrees with the list
beneath it, or a "0 pending" that means "none visible to you" rather than
"none". That is right, and §2 walks six versions of it. A monitoring screen
that quietly under-reports is worse than no screen, because it is trusted —
which is the whole reason this item's decisions are about arithmetic and
wording rather than about layout.

**D1 — every number is a `COUNT` over the same table the list reads, on the
same connection, under the same principal.** Row-level security applies to an
aggregate exactly as it applies to a select, so a count of `submission` counts
precisely the rows the list would show, *by construction* — but only while
both go through the same policy path. So: no summary table, no materialised
counter, no background aggregation, no admin connection, and no second query
shape written "for counting". The guard is structural rather than a
convention: for each metric, one test asks for the aggregate and the
enumeration with the same principal and asserts they agree, for an admin, a
programme manager, two supervisors and an enumerator.

**D2 — a zero is only shown where a non-zero was possible, and never bare.**
Every figure carries whose scope it is, in words. "0 flags outstanding" on a
supervisor's screen means "none in your team", and the screen says so. Where
nothing could have produced a non-zero — `quality_flag` has no writer until
item 6 — the card is not rendered at all, because an empty table rendered as
a measurement is a false statement with a number on it.

**D3 — target is the cases assigned to you, and it is not a new field.** The
denominator is the live assignments item 2 already records; the numerator is
those cases carrying a submission the enumerator has finished. Nothing new in
the schema, nothing to keep in step with the sample, and it is the number a
supervisor already reasons about: *you have forty households, you have done
twelve*. §3.3 defines both halves precisely and says what happens to the
denominator when a sample is re-uploaded.

**D4 — the device's read scope is a policy; its write paths stay definer
functions.** `device.user_id` has carried the signed-in person since item 1
binds it at login, so the chain device → person → team exists with no new
column: the policy is the same shape `submission`'s uncased branch already
uses, `dcp_in_list('app.visible_user_ids', user_id)`. What makes this
non-trivial is the other end — registration is public and anonymous by design
(proposal §4) and happens before anyone has signed in — so a strict policy on
reads must not break enrolment. §4 separates `USING` from `WITH CHECK` and
puts the two write paths where item 1 already put the login's.

### One thing in §7 the server cannot know

**Pending ops live in the device's outbox.** The server knows
`device.last_counter`, the highest logical counter it has *accepted*, and
nothing about what is queued behind it: ops created after the last successful
push have never been mentioned to it. A dashboard that renders "0 pending"
for a handset with forty unsent interviews is exactly the failure this item
is meant to avoid, and no query can fix it because the number is not in the
database.

So the device reports it. One integer on the push body — the depth of its own
outbox at that moment — stored on `device` beside `last_sync_at`, and rendered
with its timestamp: "12 waiting, as of 09:14". Deriving it from counter gaps
was considered and rejected: the gap is invisible for exactly the ops that
never arrived, which are the ones being asked about.

---

## 1. What exists today, plainly

- **Devices are org- and project-scoped and nothing finer.**
  `dcp_policy_chain('device', 'project_id', 'project')` (008). Any principal
  with the project in scope sees every device in it, across teams.
  `device.user_id` is nullable since 008 and is **NULL until a login binds
  it** — `register_device` writes `user_id=None` explicitly, and the auth path
  sets it. `sync_cursor` chains to `device` and inherits whatever it gets.
- **`device.last_sync_at` and `last_counter` are written on push** (sync
  service), so "last sync" is already a fact the server holds.
- **`submission` carries everything the rates need**: `status` (draft,
  finalized, in_review, approved, rejected, correction_required),
  `finalized_at`, `received_at`, `created_by`, `case_id`, `origin_device_id`.
  Its policy is item 2's: the case's scope, or the creator's own, or uncased
  work whose creator is visible to a `submission.view` holder.
- **`quality_flag` exists and nothing writes it.** The table has been there
  since 001 and chains to `submission`, so it is already correctly scoped —
  and `quality_rule` has no evaluator. Item 6 is where rules run on arrival.
- **`case_record` and `assignment`** (item 2) are the denominator, with
  `dcp_case_in_scope` deciding what a principal may count.
- **The sample row behind each case is reachable**: item 2's case query joins
  the newest `dataset_record` by key, and migration 013 records which columns
  the composite key was composed from (`dataset.key_columns`).
- **Nothing aggregates anywhere.** There is no `COUNT` in any route in the
  backend today, and no console dashboard. This item writes the first ones,
  which is why the rule about where they come from is worth fixing now.

---

## 2. What would pass every test

The naive item 5 is a `/monitoring/overview` endpoint with half a dozen counts
and a page of cards. Every unit test passes: each count returns a number, each
card renders it. Here is what that ships.

**1. The total that disagrees with the list under it.** The dashboard counts
through a query written for counting; the table lists through the list query.
They differ by one join, a status filter, or the uncased branch. A supervisor
reads "42 submissions" above a list of 38 and has no way to tell which is
wrong — and the failure is worse when the count is right, because then the
list is the thing being doubted.

**2. The zero that means "none of yours".** "0 quality flags outstanding" is
correctly scoped and reads as "the project is clean". The number is right and
the sentence it forms in a supervisor's head is false.

**3. The zero that could never have been anything else.** Nothing writes
`quality_flag` until item 6. A card showing "0 outstanding" is an empty table
wearing a measurement's clothes, and it will be believed for exactly as long
as it takes somebody to act on it.

**4. The metric the server cannot know.** "Pending ops" from
`device.last_counter` reports what was accepted, not what is queued. Every
test passes — the number is a real column — and a handset with a full outbox
shows as clear.

**5. The area figure that leaks, or lies.** An area spans two teams. Computed
honestly, the area's total includes cases a supervisor may not see, and
showing it is a leak. Computed under their policy, it is their slice of the
area wearing the area's name. Both are wrong; only one is also a breach.

**6. The rate that counts the wrong day.** "Submissions per day" by
`received_at` counts the day the server got them. An enumerator offline for
three days then syncing shows as idle, idle, idle, heroic — and a supervisor
acts on it. By `finalized_at` it counts the day the work was done, which is
the question being asked.

Failures 1, 2 and 4 are the ones the brief predicted. All six are killed by
D1–D3 plus §3.4 and §3.5.

---

## 3. The model

### 3.1 One policy path, two shapes of answer

Every metric is an aggregate over the same policy-carrying table its list
reads, executed on the request's connection under the request's principal:

```
list      SELECT ... FROM submission WHERE project_id = :p ORDER BY ...
metric    SELECT count(*) FROM submission WHERE project_id = :p
```

There is nothing clever here and that is the point. RLS filters both
identically because it is the same policy on the same connection, so the only
way they can disagree is if someone writes a second WHERE clause — which is
what the agreement test in §6 exists to catch.

Ruled out explicitly, because each is the ordinary way this goes wrong:

- a `monitoring_summary` table refreshed by a job (whose principal is not the
  reader's, so its rows are somebody else's answer);
- counting in Python over a differently-filtered query;
- the admin connection, for speed;
- caching a total across requests, which is the same thing with a clock on it.

### 3.2 Whose numbers these are

Every figure is rendered with its scope in the words beside it — "your team",
"your project" — and the screen names the person's scope once at the top.
Zero is written as "none in your team", never as a bare 0 with a label that
could be read as the project's.

This is item 4's "never asked is not answered none" one layer up: **none of
yours is not none.**

### 3.3 Target, and what counts as done

**Denominator.** The cases live-assigned to the person (item 2's `assignment`
with `released_at IS NULL`), counted under the reader's policy. By area, the
same cases grouped by a column of their sample row.

**Numerator.** A case is *covered* when it carries at least one submission
whose status is `finalized`, `in_review` or `approved` — the enumerator has
finished with it. `draft` is not covered, and neither is `rejected` or
`correction_required`, because both are work that has come back.

**Why not an explicit target field.** A number typed into a settings screen is
a second source of truth about the same thing, and it goes stale the moment a
sample is re-uploaded — which item 2 makes an ordinary event, withdrawing
cases and adding others. The assignment count cannot drift from the sample
because it *is* the sample, as assigned.

**When the sample shrinks.** A withdrawn case leaves the denominator. Progress
is against the sample as it now stands, not as it was on Monday; the
alternative is a supervisor chasing households that were removed from the
study. The withdrawal is visible in item 2's case list, which is where that
question is answered.

**Uncased work has no denominator** and is counted separately, labelled as
such. Folding it into a percentage would make progress exceed the target for
reasons unrelated to the sample.

**Area.** The sample's own columns, not a new concept: `dataset.key_columns`
(migration 013) records what the composite key was built from, and the first
of them is the area by default — `settlementCode` in RCons's sample. A project
that wants another column says so later; this item does not invent a settings
table for it.

### 3.4 Per day

By `finalized_at`, the day the enumerator finished, because that is the
question "submissions per day" asks. `received_at` answers a different
question — *is the work reaching me* — and that one is answered by the device
panel's last-sync column, where it cannot be mistaken for productivity.

Both dates exist on every row, so this is a choice about which is shown, and
the screen says which.

### 3.5 Devices

| Column | Where it comes from |
|---|---|
| person | `device.user_id`, bound at login |
| last sync | `device.last_sync_at`, written on push |
| ops waiting | **reported by the device**, with the time it was reported |
| app / platform | refreshed at registration |

An unbound device — registered, nobody signed in — belongs to nobody and is
visible only org-wide. That is the honest answer: it is not in any
supervisor's team because it is not in anyone's hands yet.

Revoking a device is not in §7 and is not built here.

### 3.6 Quality flags

The query and its scope test are written in this item, because the scoping is
this item's business and item 6 should not have to design it. The **card is
not rendered** while no rule exists to raise a flag: a zero is shown only
where a non-zero was possible (D2). When item 6 lands the evaluator, the card
appears with no further work.

---

## 4. Device scoping — the schema

One migration, one policy replaced, no new column.

```sql
-- Read: the project, then the person. `visible_user_ids` is item 1's
-- computed set — the people in my granted teams (and their sub-teams) and
-- projects, plus me — which is the same set `submission`'s uncased branch
-- already trusts.
SELECT dcp_policy('device',
    'project_id IN (SELECT id FROM project) AND ('
    '   dcp_org_wide()'
    ' OR dcp_in_list(''app.visible_user_ids'', user_id))',
    -- Write: registration is public and anonymous and happens before anyone
    -- has signed in, so an unbound row must be insertable with no person on
    -- it. Binding is the login's, and the login already runs through the
    -- definer path (010) for exactly this reason.
    'project_id IN (SELECT id FROM project) AND ('
    '   dcp_org_wide()'
    ' OR user_id IS NULL'
    ' OR user_id = dcp_principal(''app.user_id''))');
```

Consequences worth stating:

- `sync_cursor` chains to `device` and narrows with it, for free.
- A supervisor sees the handsets of their own enumerators and no others.
- An unbound device is nobody's until a login binds it, and only an
  organisation-wide principal sees it. If that turns out to hide a real
  enrolment problem from the person fixing it, the answer is a route that
  reports unbound devices to a `team.manage` holder — named here, not built.
- The one thing to watch is the registration path, which has no principal with
  a user in it. §6 break 6 is that test.

The device's reported outbox depth is the only new column:
`device.pending_ops` and `device.pending_ops_at`, written from the push body.

---

## 5. Routes and screens, in outline

**Backend.** One module, `monitoring`, whose every query runs under the
request's principal:

- `GET /monitoring/overview?projectId` — the figures, each carrying its scope.
- `GET /monitoring/enumerators?projectId` — per person: assigned, covered,
  finished per day, last sync.
- `GET /monitoring/areas?projectId` — the same, grouped by the sample's area
  column.
- `GET /devices?projectId` — person, last sync, ops waiting as of.

All gated on `submission.view`, which is the permission a supervisor already
holds and the one that already means "may see work".

**Wire.** `pendingOps` on the push body (sync §4), optional, so an older
client is simply a device that has not said.

**Console.** One Monitoring page under the project, linked from the project
list. Every number links to the rows behind it — the submissions list filtered
to that enumerator, the case list filtered to that area — because the way a
person checks a total they doubt is to look at what it counted.

---

## 6. Breaks, to be run for real when the tests exist

1. **The aggregate computed from a query the list does not use.** Add a
   status filter to the count and not to the list: the agreement test fails
   for every principal at once.
2. **A count on the admin connection.** The supervisor's dashboard shows the
   project's totals while their list shows their team's.
3. **A bare zero where nothing could be non-zero.** Render the flags card with
   no evaluator present.
4. **Pending ops inferred from `last_counter`** instead of reported: a device
   with a full outbox shows as clear.
5. **Devices left on the project chain.** Supervisor B sees team A's handsets.
6. **Registration broken by the strict policy.** A fresh device cannot enrol —
   the failure a scoped read policy invites, and the reason `WITH CHECK` is
   written separately.
7. **Per day by `received_at`.** An enumerator offline for three days shows
   idle, idle, idle, heroic.
8. **An area figure computed org-wide.** A supervisor sees a total that
   includes another team's cases.

At least one of these reaches through the handset rather than the console
(4 and 6 both do), which is the rule defect 26 set.

---

## 7. Assumptions this analysis was written under — say if any is wrong

**A1.** Every metric is an aggregate over the same policy-carrying table its
list reads, on the request's connection, under the request's principal. No
summary table, no cache, no background job, no admin connection.

**A2.** Target is the live-assigned case count; covered is a case carrying a
submission in `finalized`, `in_review` or `approved`. No new target field, and
uncased work is counted separately rather than folded in.

**A3.** Area is a column of the sample row, defaulting to the first of
`dataset.key_columns`. No settings table in this item.

**A4.** "Submissions per day" is by `finalized_at`; `received_at` is the
device panel's question and is labelled as such.

**A5.** Devices are scoped by policy through `device.user_id` and
`visible_user_ids`, with `WITH CHECK` written separately so public
registration keeps working. Unbound devices are visible org-wide only.

**A6.** Pending ops are **reported by the device** on push and rendered with
the time they were reported. The server does not infer them.

**A7.** The quality-flag metric is written and scoped in this item, and its
card is not rendered until item 6 gives it a writer.

**A8.** Revoking a device, and reporting unbound devices to a `team.manage`
holder, are named here and not built.

---

## 8. What this item does not touch

- **Item 6's review workflow.** Flags are counted, never raised or resolved
  here; the review states already in `submission.status` are read, never
  written.
- **Export.** A supervisor's export is the same scope question with a
  different output, and it already goes through the same policies.
- **The engine, the sync protocol's op semantics, encryption.** Untouched, but
  for one optional integer on the push body.
