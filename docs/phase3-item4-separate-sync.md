# Phase 3 item 4 — separate sync for sample and form

Analysis, before any code. The scope is pilot scope §6: RCons's app has
separate tabs, enumerators update each on instruction, and the person holding
the handset should decide which they are doing.

---

## 0. The decisions, and the answer to the question in front

**The question.** *What passes every test here?* The guess in front of this
item was the scopes drifting: a device with this week's form and last month's
reference data, every screen correct, and a case that cannot be worked because
its rows are not there. That is the right failure to be afraid of, and §2 walks
five versions of it. Three of them are killed by the decisions below; two are
killed by rules that already exist and that this item must not undo.

**D1 — statement and fetch are different things, and only the fetch is a
choice.** The protocol already made this split for exactly this reason (sync
§5.1: "a 52-question form is tens of kilobytes and a manifest is a few hundred
bytes"). A manifest is a complete statement of what the device *should* hold;
the document, or the rows, are what it costs to hold it. So every sync carries
both manifests, always, and no sync fetches rows unless a person asked for
them. The device is therefore never wrong about what it is missing — only
about whether it has it yet, which is a different and visible thing.

**D2 — a partial state is representable, and the pin is the representation.**
There is no device-wide "in sync" flag and there must not be one. A form
version is *ready* when every dataset version it pins is held and complete;
that is a local query over `form_version_dataset` and `dataset_version.complete`
and it exists today (`DatasetStore.missingFor`). The dataset side already
records "known but not held" — `applyManifest` writes a placeholder row with
`complete = 0` and the manifest's `row_count`. **The forms side cannot**:
`form_version.ir_json` is `NOT NULL`, so a version the server deploys and this
device has not downloaded has nowhere to live. That single asymmetry is the
whole schema change in this item (§5.1), and it is what makes an explicit
"update forms" action possible at all: without it, the only way to learn that
a form update exists is to download it.

**D3 — the device refuses nothing new to start, and one new thing to finish.**
A form whose pinned reference data is missing still starts: an interview that
never reaches the question costs nothing, and refusing a whole questionnaire
over one list is the shape item 2 §0 forbids. But a submission **cannot be
finalised while any dataset version its form version pins is missing or
incomplete**, and the refusal names the dataset and offers the action that
fetches it. Nothing is lost by this: the draft is kept, its ops push and the
answers reach the server; only the claim "this interview is complete" is
withheld, because the device could not ask all of its questions. It is item 2's
rule one layer down — item 2 refuses to *start* work on a case you do not hold,
item 4 refuses to *finish* work whose questions the device could not put — and
it is the same shape as `not_assigned`: a named reason the client can act on,
never a silent blank.

### The number in the brief is wrong, and the correction sharpens the item

The scope document, `docs/project-conventions.md` and item 2's analysis all say
"a 37,000-row sample". The repository's own measurements say otherwise:

| Artefact | Size | Source |
|---|---|---|
| RCons's sample | **1,129 rows** | `docs/rcons-current-system.md` §2, §6 |
| The UCL village list (reference data) | **38,000 rows, 11.3 MB** | `docs/phase2-record.md`, break 52 |
| First sync of that list, Pixel 6 Pro | 3.2 s | break 52, measured |
| Weekly delta of that list | 2.7 s | break 52, measured |
| A form document | tens of KB | sync §5.1 |
| An assignments statement | a few hundred cases with their rows inline | item 2 §6.1 |

So the expensive artefact in this pilot is **reference data**, not the sample,
and it is expensive in two specific situations rather than always: enrolment,
and a version the device holds no delta base for. The routine weekly case is
seconds. The *reason* in the brief is right and is the design driver — the
person on the handset chooses — but the split that matters on DCP's artefacts
is not "sample versus form". It is:

- **work** (the outbox, peers' ops, media, and the assignments statement) — must
  never be deferred, because deferring it risks data or a wasted walk;
- **forms** (documents for deployed versions not held) — tens of kilobytes;
- **reference data** (rows or deltas for pinned versions not held) — the one
  that can cost megabytes, and the one that can be a delta or a full transfer.

Naming which of those two it will be, *before the person taps*, is worth more
than any timestamp on the screen — and the device can already tell
(`DatasetStore.deltaBaseFor`).

---

## 1. What exists today, plainly

- **One button.** `SubmissionListScreen`'s sync bar has a single Sync, and
  `SyncClient.syncOnce()` does all of it in one pass: register if needed,
  refresh crypto, drain the outbox, pull op pages (asking for `forms`,
  `datasets` and `assignments` on the first page), refresh forms, refresh
  datasets, upload media. Forms and datasets failures are non-fatal and
  reported separately (`SyncResult.formError`, `datasetError`).
- **`refreshDatasets` applies the manifest and fetches every page in the same
  breath.** There is no way to learn what a sync would cost without paying it,
  and no way to take `villages` today and `health_facilities` tomorrow.
- **The manifests are already complete statements**, and applying them already
  prunes: `FormStore.applyManifest` marks everything undeployed and re-marks
  what the manifest lists; `DatasetStore.applyManifest` replaces the pins per
  form version and writes placeholders. Both are one transaction.
- **Datasets already represent partial and incomplete.** `complete = 0` until
  every page arrives, `next_cursor` to resume, `row_count` from the manifest so
  a partial transfer is detectable as one, and rows are readable **only**
  through the form version that pins them, and only when complete
  (`rowsForFormVersion`, break 30's rule).
- **Forms do not.** `ir_json` is `NOT NULL`; `applyManifest` can only
  `markDeployed` a version it already holds or upsert one with a document.
  `heldFormVersionChecksums` returns every row's checksum, so any placeholder
  added naively would immediately read as "held" and never be fetched.
- **The collection screen already names missing lists.** `CollectionState`
  carries `missingReferenceData` from `FormCatalog.missingDatasetsForSubmission`,
  computed once at load, per form version. Nothing acts on it beyond the text.
- **One status row for the whole device.** `sync_status` holds `pull_cursor`,
  `last_sync_at`, `last_error`.
- **The pull's `limit` is `ge=1`.** A manifest-only pull is not expressible
  today. `next_cursor` is already `batch[-1] if batch else cursor`, so an empty
  batch echoes the cursor and does not move it.
- **`scope` already separates the three** and the server implements all three
  as of item 2.

---

## 2. What would pass every test

The naive item 4 is three buttons, three endpoints, three timestamps. Every
unit test passes: each action calls its scope, each timestamp advances. Here is
what that ships.

**1. The empty roster.** Forms updated at the office this morning: v3, which
pins `villages` v8. Reference data last fetched a month ago: v7. The device
holds v7's rows; `rowsForFormVersion` correctly refuses to serve them for a
version the form does not pin, so the select is empty and the roster has no
rows. The interview runs. If the question is optional, or the roster is a
`rowSource` repeat, the submission finalises and files a household with no
members. Every screen was correct and the data is wrong. **This is the failure
the brief predicted, and D3 is what kills it.**

**2. The timestamp that lies.** "Reference data: updated 3 minutes ago", after
a fetch that stopped at 12,400 of 38,000 rows. The person reads *current*. The
truth is in `complete = 0` and no timestamp shows it. A per-scope timestamp is
in the brief's scope and it is the *second* failure on its own — so the status
must be a statement about content, with time second (D5, §3.3).

**3. The cursor that moves for a scope nobody asked for.** If "update forms"
issues an ordinary pull, it drains the op stream as a side effect: harmless if
the ops are applied, and defect 21 exactly if the cursor is persisted without
them — "a stale cursor pulls nothing and says synced". A manifest-only pull
must return no ops and leave the cursor where it was.

**4. The choice that loses work.** Decompose Sync into three equal actions and
the person can defer the one that sends their morning's interviews, because it
is presented as the same kind of choice as deferring a 38,000-row list. It is
not: one costs bytes, the other risks the data. The actions are not peers and
the screen must not draw them as peers.

**5. Assignments becoming an update somebody defers.** Item 2's release is an
absence from a complete statement. A device that defers assignments keeps
believing it holds a case that was reassigned an hour ago and walks to the
household. The push refuses `not_assigned` so nothing is lost — but the wasted
trip would be caused entirely by a choice this item invented. Assignments ride
with work (D4).

Two more that are already refused, and this item's job is not to undo them:
serving a partial dataset version, and serving rows for a version the form does
not pin. Per-dataset fetching makes partiality routine, so both get a break
row at the new boundary (§8).

---

## 3. The model

### 3.1 The split the protocol already made

```
manifest  →  cheap, complete, always: what this device SHOULD hold
document  →  tens of KB, per version, a choice
rows      →  KB to MB, per dataset version, resumable, a choice
```

Both manifests ride every sync. Applying them is free and has consequences
worth having for nothing: a withdrawn form version is marked undeployed the
moment the device next talks to the server, and a moved pin is recorded
whether or not the rows behind it have been fetched. The device is therefore
always able to answer "what am I missing, and what will it cost" — offline,
from local state, between syncs.

This also fixes a message that is wrong today. "No forms on this device yet.
Tap Sync to get the forms your project has deployed" is what an enumerator
sees whether the server deploys nothing or deploys three forms this device has
not downloaded. With placeholders those are different sentences.

### 3.2 Four scopes, three actions

| Scope | Rides with | Cost | Deferrable |
|---|---|---|---|
| `work` — outbox, peers' ops, media | the primary action | ops are small; media is staged and resumable | no |
| `assignments` — the complete statement | the primary action | a few hundred cases, rows inline | no (§2 failure 5) |
| `forms` — manifest always; documents on request | manifest with work; documents with the forms action | tens of KB per version | the download, yes |
| `datasets` — manifest always; rows on request | manifest with work; rows with the reference-data action | KB (delta) to MB (full) | the fetch, yes |

Three actions on the handset:

1. **Send and receive work** — the primary. Push, pull ops, apply the
   assignments statement, apply both manifests, upload media. Never presented
   as optional.
2. **Update forms** — fetch documents for deployed versions not held. One
   action for all of them: a form document is tens of kilobytes and per-form
   granularity would be a choice with nothing at stake.
3. **Update reference data** — per dataset, resumable, each row saying what it
   is and what it will cost: `villages v8 — 38,000 rows, update from v7` or
   `villages v8 — 38,000 rows, full download`.

Why assignments ride with work rather than with reference data, given that a
case *is* a sample row: because the statement carries the row inline (item 2
§6.1), it is small, and it decides the day's route. Which brings the rule that
protects it.

**The assignments statement stays self-sufficient.** It carries each case's
key, status, priority, due date **and its sample row**. So a case is listable
and openable whether or not the reference-data scope has ever run, and the
drift in the brief — "an assignment referencing a case the sample sync has not
delivered" — is structurally impossible for the case list. This item is
precisely the change that invites undoing it ("the sample sync delivers rows
now, so why duplicate them in the statement?"), and it must not be undone. The
statement also stays complete, for item 2's release behaviour.

What *does* depend on the reference-data scope is a roster or a choice list
that reads a dataset version — item 3's `rowSource: dataset` and every
`select_one_from_file`. That is one layer below the case, and it is where D3
bites.

### 3.3 What a scope's status must say

The brief asks for separate progress and a separate "last updated" per scope.
Both, with a correction: **a scope's status is a statement about content, and
the time is secondary.**

```
Work            All sent. Received up to 10:42.
Assignments     3 cases assigned to you. Checked 10:42.
Forms           Household Survey v3 — waiting to download (2 versions).
Reference data  villages v8 — 12,400 of 38,000 rows. Resume.
                health_facilities v2 — 412 of 412 rows.
```

A timestamp answers "when did I ask". Only the content answers "what do I
have", and every failure in §2 lives in the gap between those two sentences.
Time stays on the line because a person deciding whether to spend bytes wants
to know how stale the answer is.

---

## 4. When the scopes disagree

### 4.1 Is a partial state representable?

Yes, and after §5.1 it is representable *symmetrically*:

| State | Recorded as |
|---|---|
| version deployed, document held | `form_version` row with `ir_json`, `deployed = 1` |
| version deployed, document not held | `form_version` row with `ir_json IS NULL`, `deployed = 1` |
| version withdrawn, document held (a draft needs it) | `ir_json`, `deployed = 0` |
| dataset version pinned, rows complete | `dataset_version.complete = 1` |
| dataset version pinned, rows partial | `complete = 0`, `next_cursor`, rows held < `row_count` |
| dataset version pinned, nothing fetched | `complete = 0`, no rows |

`form_version_dataset` joins them: for any form version, the set of dataset
versions it pins and whether each is complete. Every question this item asks
is answerable from those three tables, offline, with no new flag and no
inference from timestamps.

### 4.2 What the device does: starts, does not finish

- **Starting is allowed.** A form is startable when its document is held and it
  is deployed — unchanged, except that a placeholder row must not make an
  undownloaded version look startable (`ir_json IS NOT NULL` on
  `startableFormVersions`).
- **Collecting is allowed**, and a dataset-backed question whose pinned version
  is unserved renders as a named absence rather than an empty list — the text
  `CollectionState.missingReferenceData` already carries, now with the action
  beside it.
- **Finalising is refused** while any dataset version the submission's form
  version pins is missing or incomplete. The reason names the datasets and the
  action.

Refusing at the **form version's pins** rather than per relevant question is a
decision, and the alternative was considered: block only when a *relevant*
question draws from a missing list, so an interview that never reaches the
optional health-facility question can still be finalised. Rejected, because it
makes the hole per-respondent and invisible — a dataset where some submissions
asked a question and some did not, for reasons unrelated to the respondent,
looks exactly like non-response. The pin-level rule makes the hole
per-device and loud, and it costs nothing that matters: drafts are kept, ops
push, answers arrive. Only the claim of completeness waits.

It also stays out of the engine. Which questions a form has is a form
semantic; what this device holds is not, and no conformance vector can see it
(`docs/project-conventions.md`). So the gate sits above the engine's verdict —
`canFinalize = navigator.canFinalize && pinnedDataIsComplete` — in shared core
where every platform gets it, with its own test, and the engine's
`finalizationBlockers` are untouched.

### 4.3 The moment after a form update

The only moment a person is still deciding what to spend bytes on is the moment
after the form update lands. So the forms action reports the gap it just
created, immediately and by name:

> Household Survey updated to v3. It needs **villages v8** — 38,000 rows,
> update from v7. Interviews can be started now; they cannot be finalised until
> the list arrives.

This is cheap because the dataset *manifest* rode along (D1), so the new pins
are known without fetching a row. Without D1 this sentence would be
unavailable exactly when it is worth most, and the enumerator would learn about
the gap in a village, offline, at the roster.

---

## 5. Schema

### 5.1 The handset: v10 (`9.sqm`)

Two changes, both additive.

```sql
-- 1. A deployed version whose document has not arrived. Mirrors what
--    dataset_version has done since v8: the manifest is a statement about
--    what should be held, and it is recorded whether or not the expensive
--    half has been fetched.
ALTER TABLE form_version RENAME TO form_version_old;  -- ir_json NOT NULL → NULL
CREATE TABLE form_version ( ... ir_json TEXT, ... );   -- everything else as before
INSERT INTO form_version SELECT * FROM form_version_old;
DROP TABLE form_version_old;

-- 2. Per-scope status. A table rather than columns, for app_setting's reason:
--    the set grows when a scope is added, and a migration per scope is a
--    migration per screen.
CREATE TABLE sync_scope (
    scope TEXT NOT NULL PRIMARY KEY,   -- work | assignments | forms | datasets
    last_ok_at TEXT,
    last_attempt_at TEXT,
    last_error TEXT
);
```

`pull_cursor` stays in `sync_status`: it is the work scope's cursor and belongs
to it. Two queries change with the nullable column, and both are load-bearing:

- `heldFormVersionChecksums` must filter `ir_json IS NOT NULL`, or a
  placeholder reads as held and the document is never fetched (§8 break 4).
- `startableFormVersions` must filter `ir_json IS NOT NULL`, or a form nobody
  can render appears in the picker.

SQLite cannot drop a `NOT NULL`, hence the table rebuild — the same shape as any
column-type migration, and safe here because `form_version` is small (a
handful of rows) and the rebuild is one transaction. Every existing row has a
document, so the migration cannot lose one.

### 5.2 The server: one validator

No schema change, no new endpoint, no policy. One line: the pull's `limit`
becomes `ge=0`, and `limit=0` means "no ops this time" — `ops: []`,
`tombstones: []`, `nextCursor` echoing the cursor sent, `hasMore: false`, plus
whatever manifests the scope asked for. `next_cursor` already computes that
way for an empty batch, so the behaviour is already right and only the
validator forbids expressing it.

The alternative — let the forms action issue an ordinary pull and apply the ops
it happens to receive — was rejected because a person on a village link tapping
"update forms" should spend bytes on the form and nothing else, and because it
makes two scopes' "last updated" advance for one action.

That is the whole backend surface of this item, which is why it is smaller than
items 2 and 3.

---

## 6. Routes and the client, in outline

**Server:** `limit=0` on `GET /sync/pull`, plus a test that the cursor is
unchanged and the manifests still answer.

**`SyncClient`:** `syncOnce()` splits into three entry points over the same
machinery.

- `syncWork()` — register, crypto, push, pull op pages, apply the assignments
  statement, apply both manifests, media. Fetches no document and no row.
- `updateForms()` — manifest-only pull (`limit=0`, `scope=forms,datasets`),
  fetch the documents `missingFrom` names, apply, then report the pins the new
  versions need but the device lacks (§4.3).
- `updateReferenceData(datasetKey: String? = null)` — manifest-only pull, then
  rows or delta for the pinned versions not held complete, one dataset at a
  time, resumable, and one dataset's failure does not cost the others.

Each records its own `sync_scope` row. `applyManifest` on both stores gains the
ability to record what is not held; `FormStore.applyManifest` stops requiring a
document per entry.

**A new read for the screens:** what this device holds versus what it should,
per scope, as content — the form versions deployed and not downloaded, and per
pinned dataset version the rows held against `row_count` with whether a delta
base exists.

---

## 7. Screens

**Handset.** The sync bar keeps one primary action, *Send and receive work*,
with the ops-waiting count it has now. Beside it, a line that only appears when
there is something to choose — "Updates available: 1 form, 1 list" — opening a
**Updates** screen with the two actions, each carrying the content statement of
§3.3 and its own progress. Reference data lists one row per dataset with rows
held, total, and *update* versus *full download*.

The collection screen's existing missing-reference-data notice gains the action
and, at finalisation, the refusal of §4.2 naming the datasets.

The empty-list message on the submission list splits in two: "this environment
deploys no forms" versus "3 forms are deployed to this device and not
downloaded — Update forms".

**Console.** Nothing new. The PM's side of this item is what they already have
from item 0 and item 2: publish and deploy a form version, upload a sample. A
device-side inventory ("which devices hold which versions") is monitoring and
belongs to item 5, and this item deliberately does not build a second one. It
leaves the hook: the server already knows a device's `last_sync_at` and
`last_counter`, and what a device *holds* would be a new report — named here so
item 5 does not discover it late.

---

## 8. Breaks, to be run for real when the tests exist

At least one reaches through the handset rather than the console, per the rule
defect 26 set.

1. **Finalise a submission whose form version pins a dataset version the device
   does not hold complete.** Must be refused, naming the dataset. This is §2's
   failure 1 and the reason for D3.
2. **Apply the forms manifest without recording deployed-but-not-held.** The
   device silently stays on v2 and "update available" is unrepresentable.
3. **A manifest-only pull advances the ops cursor.** Ops skipped — defect 21's
   shape at a new door.
4. **`heldFormVersionChecksums` counts a placeholder as held.** `missingFrom`
   returns nothing and the document is never fetched: the update stays invisible.
5. **A placeholder version appears in the form picker.** Starting it renders
   nothing.
6. **Reference data made all-or-nothing again.** One dataset failing costs the
   others; the person cannot take `villages` today.
7. **A partial dataset version served** (the `complete` flag ignored) — the
   existing rule, re-run at the boundary where partiality became routine.
8. **Assignments moved out of the work sync into an optional action.** A device
   defers and walks to a reassigned household; the statement must be requested
   and applied by the work sync.

---

## 9. Assumptions this analysis was written under — say if any is wrong

**A1.** The three actions and their grouping: work carries ops, media, the
assignments statement and both manifests; forms carries documents; reference
data carries rows. Work is never presented as deferrable.

**A2.** Finalisation is blocked at the **form version's pins**, not per
relevant question, and starting and collecting are never blocked. Drafts and
their ops sync as normal while finalisation waits.

**A3.** Reference data is fetched **per dataset**, resumable, and one dataset's
failure does not cost the others. Forms are fetched as one action for all
missing documents, because a document is tens of kilobytes.

**A4.** Each scope's status is a statement about content — rows held of total,
versions waiting — with the time secondary; and the reference-data action says
whether it will be a delta or a full transfer before it is tapped.

**A5.** The only server change is `limit=0` on the pull. No new endpoint, no
schema, no policy.

**A6.** Media stays in the work sync. Connection rules for media (wifi only,
size caps) stay where they already are, the server's media policy, and are out
of scope here.

**A7.** No console surface in this item. Which devices hold which versions is
item 5's monitoring; this analysis names the hook and builds none of it.

**A8.** The corrected numbers in §0 stand: RCons's sample is 1,129 rows and the
38,000-row artefact is the village reference list. The design driver is
unchanged — the person on the handset chooses — but the expensive scope is
reference data, and the documents that say "37,000-row sample" get a correction
in the same commit.

---

## 10. What this item does not touch

- **Item 3's `rowSource: dataset`.** This item makes the *staleness* of a
  roster's list visible and refuses to call an interview complete without it.
  Which rows a roster shows, and defect 16's row order, remain item 3's.
- **Item 5's monitoring.** Named above; hook left, nothing built.
- **The engine.** No new rule, no new blocker, no vector change. The
  finalisation gate sits above the engine's verdict in shared core.
- **Encryption, the outbox, the op log.** Untouched.
