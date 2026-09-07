# Known defects

Things that are wrong and have not been fixed yet, with the reason they are
still open written down beside them.

This is not `known-breaks.md`. That file records guarantees whose defence has
been watched to fail — it is evidence about tests. This one records behaviour
that is broken and is being left broken on purpose, so that "we know" and "it is
fixed" stay distinguishable in the repository rather than in someone's memory.

A defect leaves this file in one of two ways: it is fixed, or it is decided to
be permanent and moves into `docs/project-conventions.md` as a documented limitation. It does not
leave because it has been here a long time.

Rules that make it worth keeping:

- **Every row names the symptom an enumerator or reviewer sees**, not the code
  smell. "The Save button does nothing" is a defect; "`mediaCapture` is null on
  desktop" is its cause.
- **Every row says why it is still open.** "Out of scope for the current phase"
  is a good reason. No reason at all is not.
- **A row that overstates or understates what is broken is worse than no row.**
  If the observation cannot be reproduced, say so in the row.

## Open

### 1. The desktop date question — reported, not reproduced here

| | |
|---|---|
| **Where** | `clients/composeApp/.../CollectionScreen.kt` → `DateAnswer`, on the desktop client |
| **Status** | **Open — symptom recorded, and it did not reproduce here** |
| **Why not fixed** | There is nothing yet to fix. Four attempts to reproduce it all showed the picker opening; see below |

**Reported symptom.** Clicking the "Pick a date" field focused it — the border
turned purple — and nothing else happened. No picker. On the focused field,
Space, Enter and typing `2026-08-30` each changed nothing; all four screenshots
were byte-identical (sha256 `01f0e572302ea24b…`). Compose Desktop, 800x600
window, macOS dark appearance, English. Driven with synthesised CGEvent clicks
and System Events keystrokes rather than by hand.

**It did not reproduce**, by four routes, on 2026-08-30:

1. `DateQuestionTest` (`:clients:composeApp:jvmTest`), which drives the real
   composable on the JVM target with Compose's own injection: mouse and touch
   both open the picker.
2. The same composable in a **real 800x600 Compose Desktop window**, clicked
   with a synthesised `CGEvent` — the report's own instrument. The click reached
   the overlay and the dialog composed.
3. The **full desktop app**, navigated to a date question: same result.
4. A real hand click on 2 and 3, which is what the report asked for.

The picker also lays out on screen rather than off it: instrumented,
`DatePicker` measured 720x1024 px at `Rect(440, 4, 1160, 1028)` with its button
row at `y=1028..1124`, inside a content area 1144 px tall. That fits with
20 px to spare at 800x600, which is tight enough to be worth knowing — a
smaller window would not fit it.

**What the report's own evidence does and does not settle.** The CGWindowList
check ruled out the wrong thing. Compose Multiplatform renders a `Dialog` as a
layer *inside* the parent window, not as a platform window, so an unchanged
window list is what a working picker looks like too — confirmed here: the
process still reported exactly one window with the picker open. The
byte-identical screenshots are the load-bearing evidence, and they are not
explained.

One detail still contradicts every reproduction: the report says the **field**
took focus. The transparent overlay sits above the field and consumes the
click, so a click that opens the picker does not focus the field underneath —
and a click that focuses the field means the overlay was not hit. The only way
`DateAnswer` omits the overlay is `enabled == false`, and a disabled
`OutlinedTextField` does not take focus either. So the two halves of the
reported symptom do not fit together in this code, which is the strongest
reason to think something environmental was in play.

**This row is now blocking something, 4 September 2026.** It never carried the
"desktop was never Phase 1 scope" reason — its reason is and remains that there
is nothing yet to fix, four reproductions having failed. What has changed is the
cost of leaving it unresolved: RCons collects on paper and keys the forms in
afterwards, and desktop entry is what they want for it
(`docs/phase3-pilot-scope.md` §9 — the phase after Phase 3). A date question
that may or may not open its picker cannot be an open question on the client
somebody is about to key a survey into. Resolve it one way or the other before
that phase starts, rather than letting it sit.

**To close this row:** a reproduction on the current tree that says which build
was running, or a decision that the report was an artefact of the synthetic
input and the row can go. Do not close it on the strength of the tests alone —
they are `DateQuestionTest`, they are now in CI, and break 23 in
`known-breaks.md` is the evidence they can catch this symptom; but every one of
them passed before the investigation started too.

### 2. Desktop draws media widgets that silently do nothing

| | |
|---|---|
| **Where** | `clients/composeApp/src/jvmMain/.../MediaCapture.jvm.kt`, and `mediaCapture == null` in `CollectionViewModel` |
| **Status** | Open |
| **Why not fixed** | Scheduled, not deprioritised: desktop entry is the phase after this one. The old reason — "desktop collection was never Phase 1 scope" — is wrong now, see below |

An image, signature or geopoint question on desktop renders its full widget and
every control on it is inert. No message, no refusal, no disabled state — the
control behaves exactly as it does when it has not been tapped:

- **Choose from gallery** is drawn unconditionally in `ImageAnswer`, because only
  the camera button is behind `isCaptureSupported()`. `rememberGalleryPicker` on
  the JVM calls `onPicked(null)`, which the widget reads as "the enumerator
  cancelled". Tapping it is indistinguishable from not tapping it.
- **The signature canvas** draws strokes normally and enables **Save signature**
  once there are some. `onSignatureDrawn` returns at `mediaCapture ?: return`.
  The strokes stay on screen, so it looks saved.
- **Capture position** calls `rememberLocationPermissionRequest`, whose JVM
  actual answers `onResult(true)` — permission granted — and then
  `onCaptureLocation` returns at the same null check. The button does not even
  enter its "finding position" state.

This is the opposite of what the code says it does. `MediaCapture.jvm.kt`'s
header says desktop makes the image question "show its gallery button and
nothing else, rather than a shutter that does nothing", and the gallery button
*is* the shutter that does nothing. `docs/project-conventions.md` said "desktop refusing rather
than pretending" until this was filed; it now says desktop collects nothing.

**Why the reason changed, 4 September 2026.** This row said the fix was to stop
drawing the widgets, on the grounds that implementing them "would build a
collection path nobody uses and nothing tests". Both halves of that have a
customer now. RCons collects on paper and keys the forms in afterwards, and
desktop entry is what they want for it — so the path has a user, and stopping
at "not available on this device" would close the row while leaving them without
the client they are asking for.

That does not make it urgent. Desktop data entry is named in
`docs/phase3-pilot-scope.md` §9 as **not** in Phase 3, deliberately, with these
two defects given as what blocks it — it is the phase after this one. **Do not
fix it here.** What changes today is only the reason: this row is scheduled work
waiting its turn, not a widget nobody wanted.

The smallest honest fix below is still the right thing to do *if* desktop entry
slips again. It is no longer the thing to do by default.

The smallest honest fix is the one `CollectionViewModel` already documents for
unsupported question types: on a build with no `MediaCaptureGraph`, render
image, signature and geopoint as "not available on this device" and draw no
control at all. Rendering a widget that cannot answer a question is worse than
skipping it, because the enumerator thinks they have answered.

### 3. Every device in a project gets the production environment's forms

| | |
|---|---|
| **Where** | `backend/app/modules/forms/service.py` → `device_environment_id` |
| **Status** | Open |
| **Why not fixed** | Nothing enrols a device into an environment, because there is no auth layer and no enrollment UI. A stored `device.environment_id` that nothing can set would be null on every row and a second source of truth beside the derivation still doing the work |

A device's environment is **derived** from its project rather than assigned to
it: `production` if the project has one, else `staging`, else `development`. So
a project with both a staging and a production environment gives every device
production, and there is no way to put one phone on staging to test a form
before it ships to the field.

That is a real limitation of form delivery rather than a bug in it. What works
today is the part that must not be got wrong later: the manifest is scoped by
`form_deployment.environment_id`, so once a device *has* an environment the rule
is already enforced and watched (`known-breaks.md` row 26). What is missing is
only the assignment.

The derivation deliberately matches `_ENVIRONMENT_PREFERENCE` in
`app/modules/sync/service.py`, which is what the push path uses to file a
submission. The two must keep agreeing: a device handed forms from one
environment while its data is recorded against another would be a far worse
failure than the one this row describes, and it would be invisible from both
ends.

The fix is `device.environment_id`, set at enrollment, defaulting to this same
derivation for devices that predate it. It belongs with the auth work, not
before it.

### 4. A deployment cannot be retired

| | |
|---|---|
| **Where** | `backend/app/modules/forms/service.py` → `deploy_version`; `form_deployment.retired_at` |
| **Status** | Open |
| **Why not fixed** | Withdrawal is fully implemented on the *reading* side — the manifest, the client's `deployed` flag and retention all handle a version disappearing — and only the endpoint that would cause it is missing. Adding it is an API change with its own contract regeneration, and nothing in Phase 2 part 1 needs it |

`POST /forms/versions` deploys, and it is additive by design: deploying v3 to
production does not retire v2, and there is no call that sets `retired_at`. So a
project accumulates deployments, and every version ever deployed stays in every
device's manifest.

The consequence today is bounded and not silent: a device holds more form
versions than it needs, and its picker still offers only the newest version of
each form (`startableFormVersions`), so an enumerator is never shown a stale
questionnaire. The cost is storage and manifest size, both small at the scale of
one customer.

It matters more than that reads, though, because the untested path is the one
that runs when something has gone wrong — a form withdrawn because it was
published by mistake. The client half of that is tested (`FormStoreTest`:
`a version the server stops deploying is withdrawn, not deleted`, and the
retention pair); the server half cannot happen at all.

### 5. Nothing checks that a device's forms and its submissions agree

| | |
|---|---|
| **Where** | The seam between `forms.service.device_environment_id` and `sync.service._ENVIRONMENT_PREFERENCE` |
| **Status** | Open — no symptom observed |
| **Why not fixed** | Both currently read the same list in the same order, so there is nothing to reproduce. Filed because the duplication is the kind that drifts, and the drift would be silent |

Two functions in two modules independently decide which environment a device
belongs to. They agree today by inspection, not by construction, and there is no
test that would fail if one changed.

If they diverged, a device would be handed the forms of one environment and have
its submissions filed against another. Every screen would look correct on both
sides: the phone shows the form it was given, the console shows a submission
under a form version that exists. Only a comparison across the two would show
it, and nothing performs one.

The fix is one function with one caller each, not a test — a shared rule cannot
drift. It was left as two because moving it means moving `_ENVIRONMENT_PREFERENCE`
out of the push path, and that is a change to the code that decides where every
submission is recorded, which does not belong in the same commit as form
delivery.

### 6. The settings screen can state the wrong reason a device has no forms

| | |
|---|---|
| **Where** | `clients/composeApp/.../SettingsScreen.kt` → `FormsSection`; `SyncResult.formError` |
| **Status** | Open — narrowed, not closed |
| **Why not fixed** | The remaining case needs `formError` persisted beside `last_sync_at` and `last_error` in `sync_status`, which is a migration and a change to the record of what a sync did. That belongs on its own, not appended to the settings screen |

With no forms on the device and a successful sync behind it, the screen says:

> None. This device has synced, so its project has no form deployed to this
> device's environment.

That is a **conclusion**, and it is the right one almost always — publishing is
not deploying, and this is the single most common reason a phone comes up empty.
But it is stated with more confidence than the screen can support: it is also
what appears when the manifest arrived and a document did not.

That path is no longer silent — `refreshForms` now reports an entry whose
document would not fetch (break 34), and the submission list shows it as
"Forms not refreshed: …". Two things still make the settings screen the wrong
place to read it:

- **`formError` is not persisted.** It lives on the `SyncResult` handed to
  whoever called `syncOnce`, which is `SubmissionListViewModel`. The settings
  screen never sees it, and neither screen has it after a relaunch — the
  explanation of a failure outlives the app by less time than the failure does
- **so the two screens disagree**, and the one an enumerator is sent to for an
  explanation is the one holding the weaker information

The fix is `sync_status.last_form_error`, written where `recordSyncSuccess` and
`recordSyncError` already write, and read by both screens. Until then the screen
overstates a correct conclusion, which is a smaller fault than the silent skip
it replaced and is still a fault.

### 8. In a project_e2e project, nothing checks choice membership after the client

| | |
|---|---|
| **Where** | The console's decryption path (`web/src/lib/decryptSubmission.ts`), and Form IR §6.4 |
| **Status** | Open — named in the spec so the gap is visible |
| **Why not fixed** | It belongs to the console's decryption work, not to the engine change that created the question. Building it inside the membership item would have meant a half-done console feature attached to a finished engine one |

§6.3 says a `select_one` value must be one of its question's choices. §6.4 says
where that is enforced, and the honest answer differs by security mode:

| | `standard` | `field_level` | `project_e2e` |
|---|---|---|---|
| Client | yes | yes | yes |
| Server, on push | yes | non-sensitive only | **no** |
| Console, after decryption | n/a | sensitive fields | **not built** |

In `project_e2e` the server stores `value_ciphertext` and holds no private key,
so it cannot check membership and does not pretend to. The only party that can
is a key holder in the browser, and the console does not check.

**So a `project_e2e` project today gets a client that validates and nothing
else.** A hand-crafted push carrying `gender = "purple"` is stored, syncs, and
appears in the console as an answer. Nothing is wrong with the encryption — the
property that the server cannot read the data is the same property that stops it
checking the data — but the check that should compensate is missing.

The fix is a membership pass in `decryptSubmission`, where the plaintext and the
form version are both available, surfacing a submission whose values are not in
their lists. Until then, §6.4's console column is a description of what should
happen rather than what does.


> **Defects 9 and 10 are both downstream of defect 4.** A device holds two
> versions of a list only because nothing retires a form deployment, so every
> form version ever deployed keeps its reference data alive on every device
> forever. Fixing 4 removes the reason for the copy that costs 9 its 56 seconds,
> and removes the second version that costs 10 its regression. Neither blocks
> collection — the acceptance passed on a handset with both present — but they
> are the largest thing between datasets and a field, and they are one fix.

## 9. Applying a dataset delta costs 56 seconds on a Pixel

Measured, 2026-09-03: a device holding v1 of a 37,852-row village list receiving
v2 with 300 rows changed transfers **66 kB** — a 109× saving over the 7.05 MB
full list, exactly what the delta was built for — and then spends **56 seconds**
applying it.

The time is not in the network. The device seeds the new version by copying
37,852 rows and about 76,000 index entries from the old one inside SQLCipher,
because a dataset version's rows are keyed by version id and another form
version may still pin the old one.

Left open rather than fixed because the cheapest fix is not in this layer: when
nothing else pins the base version the copy could be a rename, and what keeps
the base pinned is defect 4 below — nothing retires a form deployment, so every
version ever deployed keeps its reference data alive. Fixing that removes most
of this by removing the reason for the copy.

It is a background cost inside a sync rather than a wait in front of an
enumerator, which is why it is a defect and not a blocker. It is still 56
seconds of a phone doing nothing useful, every week, per project.

## 10. Per-keystroke filtering degrades 10x when a second dataset version is held

Measured, 2026-09-03, and **not explained**. At district → village over 37,852
villages a device holding one version answers in 7.3 ms (median, 12.3 ms at the
95th percentile). A device holding two answers in 77–88 ms.

The obvious explanation is the size of `dataset_cell`, and it is wrong: a device
that reached two versions by two *full syncs* measured 7.9 ms on exactly the
same data, and one that reached them by applying a *delta* measured 77 ms. The
lookup is a primary-key seek with the version id as a literal in both cases.

Recorded rather than guessed at. Candidates not yet ruled out: the WAL after a
113,000-row copy transaction, page fragmentation from `INSERT ... SELECT` into a
WITHOUT ROWID table, or SQLCipher page-cache pressure at 31.7 MB. The next step
is `PRAGMA` diagnostics on the device, not more code.

It matters because 77 ms per keystroke is at the edge of feeling broken, and
because a device only holds two versions at all because of defect 4.

## 11. A text answer of exactly `ENCRYPTED` is indistinguishable from the token

An unreadable value exports as the literal `ENCRYPTED`, because every
statistical tool treats blank, `NA` and `NULL` as missing and will compute a
mean over the rows that happen to be readable without saying so. A token is a
value no analysis can mistake for an absence — but a respondent whose answer to
a text question *is* the word `ENCRYPTED` produces a cell nothing in the file
distinguishes from one the server could not read.

**What an analyst sees.** A cell reading `ENCRYPTED` in a plaintext text
column. The manifest is what resolves it: every column that can carry the token
is listed with an `unreadable` reason, and a cell with that text in any other
column is somebody's answer. That is stated in the manifest's own notes.

**Why it is still open.** Every fix costs more than it buys. A sentinel nobody
would type (`\x00ENCRYPTED`) is unreadable in a spreadsheet, which defeats the
point of a token a person can see. A per-column escape rule means a reader has
to unescape before comparing, which is a new way to be subtly wrong. A separate
"is this readable" column per column doubles the file.

It is recorded rather than fixed because the collision is narrow — a text
question, answered with that exact word, in a project where the column is not
encrypted — and because the manifest already answers it for anyone who reads it.
Revisit if a real form hits it.

## 13. An export holds every submission in memory at once

Measured, 2026-09-03, by `scripts/measure_export.py`. **Time is fine and memory
is not.** 5,000 submissions export in 7–16 seconds depending on format and peak
at about 530 MB of process RSS; 12,000 submissions peak at **1,083 MB**. One
export request can therefore exhaust a 2 GB self-hosted box, and two concurrent
ones certainly can.

**What an enumerator or reviewer sees.** Nothing, up to the limit. Past it the
process is killed by the OOM killer and the request dies with no useful error —
which is the worst available symptom, because it looks like the server falling
over rather than like a request that asked for too much.

**Where it goes, and where it does not.** The dataset is not the problem, and
that was worth measuring rather than assuming: at 12,000 submissions a 500-row
village list and a 37,852-row one both peak at 506 MB of Python allocations.
Label resolution is already cached per dataset version — three row fetches for a
whole export, O(1) per cell — so there is nothing to gain there. The cost is
`export_form` holding the entire run alive simultaneously: every op as an ORM
object, every fold, every projection, every table row, and the writer's copy on
top. Roughly 40 KB per submission above a 130–150 MB floor.

**Why it is still open.** The fix is streaming — fold, project and write one
submission at a time, so peak memory is a function of the *widest row* rather
than of the row count — and that is a redesign of `service.export_form` and of
`Table`, which currently holds `rows` as a materialised tuple. Doing it blind,
on the strength of a number nobody had measured, is exactly what §3.2 says not
to do: the first dataset cut cost 1,589 ms per keystroke and only a Pixel said
so. Now the number exists, so the redesign can be judged against it.

Two things narrow it in the meantime, both deliberate rather than accidental:

- `DEFAULT_LIMIT` is 5,000 and the HTTP route caps at it, so the endpoint cannot
  be asked for the 12,000-submission case at all.
- `scripts/export_submissions.py --limit` is **not** capped, because a CLI run is
  one at a time and an operator knows their machine. A customer who needs all
  12,000 rows today can have them on a box with the memory.

The honest statement of the boundary: **this exporter is sized for a project,
not for a country.** A form with more than about 10,000 submissions needs either
the streaming rewrite or an export sliced by environment, status or date — and
there is no date filter yet, which is the cheapest of the three to add.

## 15. A calculate can block finalisation with no screen to send anyone to

| | |
|---|---|
| **Where** | `backend/app/modules/form_engine/screens.py` and `shared/form-engine/.../Screens.kt` — `first_blocking_screen` / `firstBlockingScreen` return nothing for a field that is on no screen |
| **Status** | Open. Reproduced against the Python reference, 5 September 2026. Named by §6.2 since repeat screen flow landed, and no closer to fixed for it |
| **Why not fixed** | The fix is a decision about what a runtime shows when the blocking field is one nobody can answer, and it is not the same decision as repeat screen flow. Filing it separately so item 3 does not close it by accident |

**What an enumerator sees: a Finalize button that refuses, and nothing to fix.**

A `question` may carry both `calculate` and `constraint` (§2.1), and a computed
total that must stay under a limit is a real quality check rather than a
contrivance. Such a field is relevant, it is evaluated like any other
(`runtime.py:657` evaluates a constraint for any field holding a value), and a
failed hard constraint makes it **blocking** under §6.2. But §11.1 gives a
calculate no screen — correctly, since there is nothing on it to answer — so
there is no screen holding the blocking field and nothing to navigate to.

Reproduced with a three-field form, `total = a + b` constrained to `<= 100`,
`a = 80`, `b = 40`:

```
screens in the plan  : [(0, ('a',)), (1, ('b',))]
total's value        : 120
total's errors       : [{'kind': 'constraint', 'message': {...}, 'severity': 'error'}]
blocking_fields      : ['total']
can_finalize         : False
first_blocking_screen: None
```

§6.2 already anticipates `firstBlockingScreen` being nothing while `canFinalize`
is false, and requires a runtime to refuse and SHOULD name the field. **It used
to attribute the case to repeats** — "a blocking field inside a repeat has no
screen at all, because §11.1 excludes repeats from the plan" — which stopped
being the reason when `8c0fade` made a calculate produce no screen. That change
was right, and it moved the case from repeats to calculates without the sentence
following it.

Repeat screen flow (§11.3) then removed the repeat reason entirely, and §6.2's
final bullet now names this one instead and points here. So the spec is accurate
again and the defect is unchanged: **being named is not being fixed.** The
sentence describes the dead end; nothing has been built to get an enumerator out
of it.

**The part that is worse than a missing sentence.** The constraint's own
`constraintMessage` is attached to a field that is never drawn, so the one
string written to explain the problem has nowhere to appear either. An
enumerator gets a refusal, no location, and no message — a dead end in the
field, at the end of an interview, which is the moment with the least patience
for one.

**Both engines, by construction.** `Screens.kt` excludes a calculate on the same
line and `firstBlockingPosition` returns null on the same condition. Only the
Python reference has been watched to do it; no vector covers the pair
(`canFinalize: false`, `firstBlocking: null`) **on a calculate** at all, which is
why nothing said so. `screens-008` covers it on a repeat field, and that case now
resolves to a real position — which is exactly why this one is easy to mistake
for covered.

**What closing it needs to decide**, and the reason it is a decision rather than
a patch: where a runtime sends somebody for a field that cannot be answered.
Three candidates, none obviously right — the nearest screen holding a field the
calculate *depends on* (§5.1 already has the graph, and it is where the wrong
input actually is); a screen the plan does not otherwise have; or a refusal that
names the field and its message without navigating. The third is what §6.2
already requires and no client implements.

## 16. A dataset's published row order does not reach a device

| | |
|---|---|
| **Where** | `shared/core/.../db/datasets.sq` (`dataset_row` has no order column; three read queries `ORDER BY r.rowid`), `DatasetStore.applyDelta`, and `backend/app/modules/entities/rows.py` `version_checksum` |
| **Status** | Open. Measured 6 September 2026 — `scripts/measure_dataset_row_order.sh` |
| **Why not fixed** | Found while specifying Form IR §2.3's `rowSource`, which is the first feature that needs the order. Fixing it is a device migration, a wire field and a decision about a version's content address; doing that inside the spec change would have been three things in one commit. §2.3 refuses `kind: "dataset"` until it lands, so nothing ships on top of it meanwhile |
| **Blocks** | **A roster preloaded from the sample — Form IR §2.3 `rowSource` with `kind: "dataset"`, and therefore Phase 3's household member roster.** One of the two reasons that source is refused; the other is `_metadata.case_key` (item 2). Both must clear before it can be scheduled, and this one is the easier to miss, because cases are a visible dependency and this is a `SELECT` with no `ORDER BY` |

**What an enumerator would see: a household in an order nobody chose.** A roster
preloaded from the sample (§2.3) creates one instance per dataset row, so the
list on the repeat screen *is* the sample's row order. Today it would be the
head of household third, and after any correction to any member, last.

The server is not where this is wrong. `dataset_record.ordinal` (migration 0005,
break 48) is stored, is the sort key of `dataset_rows_page`, `dataset_rows_for`
and the delta's changed-row walk, and is the paging cursor. The order is intact
right up to the response body — and then `dataset_rows_page` returns
`[dict(data) for _, data in page]`. **The ordinal is the cursor, not a field.**
It never goes over the wire, there is no column for it on the device, and
`datasets.sq` reads rows back with `ORDER BY r.rowid`: insertion order, which
matches the published order only for as long as nothing re-inserts.

Two things then re-insert. Both measured, on the device's own schema:

```
$ ./scripts/measure_dataset_row_order.sh
PASS  after first sync             m3 m1 m2 m4
FAIL  after the delta's seed       m1 m2 m3 m4   (published: m3 m1 m2 m4)
FAIL  after one changed row        m2 m3 m4 m1   (published: m3 m1 m2 m4)
```

1. **The delta's seed re-sorts the whole version.** `copyRowsToVersion` is
   `INSERT ... SELECT ... WHERE dataset_version_id = ?` with no `ORDER BY`, so
   SQLite serves the scan from the `(dataset_version_id, record_key)` primary
   key and assigns the new rowids in **key order**. The head of the household
   moves from first to third on the first delta, with no row having changed.
2. **A changed row moves to the end.** `insertRow` is `INSERT OR REPLACE`, which
   deletes and re-inserts, minting a fresh rowid.

And two more that no script reaches, because they are about what is never sent:

3. **A reorder cannot be delivered.** The delta's changed-set test is
   `before.get(key) != projection(dict(data))` — content only. A version that
   reorders rows without changing any of them produces `changed == []`.
4. **A reorder cannot be published.** `version_checksum` sorts by key before
   hashing, deliberately, *"so that two servers that inserted the same rows in
   different orders agree"*, and `publish_dataset_version` is idempotent by that
   address. Re-uploading the same sample in a new order returns the existing
   version.

So this is not an omission. **Order is excluded from a dataset version's
identity by a stated decision**, and that decision was right while a dataset was
a choice list, where order is presentation. §2.3 makes it data. That is the
thing to decide before any of the code below is written, and it is why Form IR
§3.1 records the conflict instead of asserting the sentence it wants.

**Nothing that exists could have caught this.** The server-side guard from break
48 publishes `V000…V249` — a fixture where published order and key order are the
same sequence, so it passes against a store that sorts by key, and it is
evidence about paging rather than about order. The device side has no order
assertion at all. This is break 87's shape a second time: a fixture in which the
wrong answer and the right answer coincide.

**What this blocks, stated where somebody scheduling work will read it.** A
preloaded roster is the household member list — the shape RCons's fieldwork is
built around — and it cannot ship until row order is part of a dataset version's
identity. That is not a polish item to do afterwards: a roster whose rows arrive
in an order nobody chose is wrong in a way that looks right, because every name
is present and every answer attaches to the correct person. Only the sequence is
somebody else's, and nothing on the screen says so. Item 2's cases are the
dependency everyone will see; this is the one that gets scheduled around.

**What closing it needs**, in the order it has to happen:

1. Decide whether row order is part of a version's content address. If yes,
   `version_checksum` folds the ordinal in — forward-only, because a device
   compares against the stored `dataset_version.checksum` column and nothing
   recomputes an existing one, so no device re-fetches.
2. Carry the ordinal on the wire, store it on `dataset_row`, and read by it
   rather than by `rowid` in all three queries. That closes (1) and (2) above
   together: with an explicit order column, neither the seed copy's scan order
   nor a re-minted rowid can be observed.
3. Make the delta able to say a row moved — a row enters `changed` when its
   ordinal changed as well as when its content did.
4. Fix the fixtures. The server test needs a published order that is not key
   order, and the device needs an order assertion of its own; `ORDER BY rowid`
   held for two versions of this schema with nothing watching it.

Step 2 is a device schema migration, which is the reason this is a defect and
not a paragraph in the §2.3 commit.

**A note on the measurement.** The first version of the script read both stages
after all three had run, and stage 2 printed stage 3's answer — the two losses
are independent and each hides the other. It is in the script's comments because
the same mistake would make a fix look complete when only one half of it was.

## 17. The spec promises five compile warnings and both engines emit two

| | |
|---|---|
| **Where** | `specs/form-ir-v0.1.md` §10.3; `shared/form-engine/.../Runtime.kt` `lint()`; `backend/app/modules/form_engine/runtime.py` `_lint` |
| **Status** | Open, narrowed. Read from both engines 6 September 2026; `unreachable relevance (statically false)` implemented on both engines 7 September 2026 with `conformance/reachability` 004 asserting it — the first vector in the repository to assert a compile warning. Two of the five remain unimplemented |
| **Why not fixed** | Two of the three missing warnings need a definition before they can be written, and until this commit the third did too. `unreachable relevance (statically false)` had no definition of *statically false* anywhere in the specification; §10.3 now has one, and the container case it separates out is a §10.2 error rather than a warning. `repeat with no bound` and `unused calculate` are still one line of prose each with no rule under them. Implementing any of the three ahead of its definition is how the two engines come to disagree |
| **Blocks** | Phase 3 item 0. A visual builder's whole value over a spreadsheet is telling an author what is wrong while they are still looking at it, and the warnings are most of what there is to tell them |

**What an author sees: a form that publishes clean and is not clean.** §10.3
says a runtime warns on five things. Both engines warn on two — missing
translation, and a decimal field with an equality constraint — and they are the
same two, line for line:

```
Runtime.kt:381   "${f.fieldId}: missing translation for ..."
Runtime.kt:384   "${f.fieldId}: direct equality comparison on a decimal field"
runtime.py:349   f"{f.field_id}: missing translation for ..."
runtime.py:354   f"{f.field_id}: direct equality comparison on a decimal field"
```

Three named warnings have no implementation on either engine:

| §10.3 promises | Emitted |
|---|---|
| missing translation | both engines |
| decimal equality comparison | both engines |
| unreachable relevance (statically false) | both engines, since 2026-09-07 (`reachability-004`) |
| repeat with no bound | **neither** |
| unused calculate | **neither** |

**The conformance suite cannot see this, and that is the part worth recording.**
Rule 2 — every vector passes identically on both engines — is the strongest
guarantee in this repository, and it is a comparison. Two engines that are
identically incomplete pass it. There is no vector to fail here in any case:
none of the 113 files in `conformance/vectors` asserts a compile warning at all
(`screens-006.json` mentions `"severity": "warning"`, which is a soft
constraint, not this). So the promise has stood unimplemented for as long as it
has existed and nothing in the repository was ever in a position to notice.

This is the same failure as a guard that does not run (break 24), arriving from
the other side. There, a suite existed and CI did not execute it. Here, a
specified behaviour exists and no engine implements it — and in both cases the
repository reads as better defended than it is, because an absent warning is
indistinguishable from a clean form.

**Fixing it is three separate pieces of work, not one.** Each missing warning
needs a definition in the specification before an engine can carry it, one
vector shape per warning in `conformance/vectors`, then both engines. The
alternative — writing whichever engine is nearer to hand and letting the other
follow — produces exactly the divergence §10 was written to prevent.

## 18. The engine executes no vector on iOS

| | |
|---|---|
| **Where** | `shared/form-engine/build.gradle.kts` (the iOS targets), `.github/workflows/ci.yml` (no macOS runner) |
| **Status** | **Open, and down to one platform.** JVM, wasmJs and Android each execute all 116 vectors as of 6 September 2026. iOS executes none |
| **Why not fixed** | It needs a macOS runner, which the project does not have. That is the whole of it — the runner is already `commonTest` and would compile for iOS with one `actual` reading files through `platform.posix`. Adding that source set **without** a runner makes `scripts/check_ci_runs_every_suite.py` fail on purpose (break 24(h)), and that refusal is correct: a suite no job can execute is the failure, not the fix |
| **Blocks** | Nothing today. iOS is a client target and the engine compiles for it; what is absent is evidence that it evaluates identically |

**What changed, and what did not.** The row used to say the engine was verified
on one platform of four. The step runner has moved from `jvmTest` to
`commonTest`, and each target's count is read from that target's own JUnit XML:

```
conformance/vectors on jvmTest              116 vectors
conformance/vectors on wasmJsNodeTest       116 vectors
conformance/vectors on testAndroidHostTest  116 vectors
```

| Target | Compiles | Executes |
|---|---|---|
| JVM | yes | 116 vectors, all five suites |
| wasmJs | yes | **116 vectors** |
| Android | yes | **116 vectors** |
| iOS | yes, since 6 Sep 2026 — it did not before | **nothing** |

**Not closed, deliberately.** Three of four is not four, and iOS is a platform
this product ships a client on. Closing a row that says "verified everywhere"
while a shipping target evaluates nothing is the shape this row was corrected
for once already: it asserted iOS was untested when iOS did not compile, and
the lesson was that an untested target and an unbuildable one are
indistinguishable from inside a green CI run. A closed row and an unverified
platform would be the same mistake with the labels swapped.

**Rule 2 is wider than it was and is still not everywhere.** "Every vector
passes identically on both engines" now means Python against Kotlin on three
targets rather than one. On a handset running iOS it remains a design property
— the module is dependency-free of UI and framework code, and that is enforced
by review — rather than a tested one. Kotlin/Native is exactly where a
difference would be plausible: integer width, string comparison, date
arithmetic.

**What closes it.** A macOS runner, an `iosSimulatorArm64Test` source set with a
posix reader, and the CI job in the same commit. `iosSimulatorArm64Test` already
exists as a Gradle task and runs locally on a developer's Mac, so the work is
small; the runner is the cost, and it is a budget decision rather than an
engineering one. Until then this row stays open and says so.


## 20. The handset shows a blank screen for a roster

| | |
|---|---|
| **Where** | `clients/composeApp` — the screen for a `repeat`; seen on the Android emulator 7 September 2026 (`docs/e2e-run-2026-09-07.md`) |
| **Status** | Open |
| **Why not fixed** | The roster UI is the half of phase 3 item 3 that was left after the engines landed (§11.3, `screens-012`…`025`): the engine has the instance list, the add rule and the row labels, and the shared UI does not render them yet |
| **Blocks** | Collecting any form with a repeat on a handset — which the builder can now author in an afternoon |

A form authored in the builder with a repeat over a fixed list of two rows
(`rowSource.kind: "inline"`, `allowAdd: false`, one question bound to the
row's value) reached the emulator and showed, at screen 5 of 7, nothing: no
row list, no "Mother" or "Father", no control to enter an instance. Previous
and Next worked; the two questions inside the repeat could not be answered,
and the submission finalized and synced without them.

The engine is right about the screen — it is one screen, the plan names it,
the row screens exist beneath it — and the publish gate is right to have let
the form through, since the rows are there. What is missing is the view. It is
the same shape as defect 14 one level up: the questions are in the document,
they survive publish, and on the phone nothing asks them.

## 21. A device with a cursor from another database pulls nothing and calls itself synced

| | |
|---|---|
| **Where** | `shared/core/.../SyncClient.kt` (the pull loop), `backend/app/modules/sync/service.py` `pull`; seen on the Android emulator 7 September 2026 (`docs/e2e-run-2026-09-07.md`) |
| **Status** | Open |
| **Why not fixed** | Needs a decision about what a server *is* to a device: the pull cursor is a position in one server's op log, and nothing identifies the log. A cursor is only meaningful against the database that minted it, and the protocol carries no way to say which one that was |
| **Blocks** | Any rebuild or restore of a server, and any test environment recreated beside a device that has synced before — which is every emulator on every developer's machine |

The device had synced against an earlier database and kept `pull_cursor =
287`. The database was recreated, the seed ran, a form was published and
deployed. The device pulled with `cursor=287`, the new log had fewer entries
than that, the server answered 200 with nothing, and the app wrote "All
changes synced" — with a form deployed to its environment that it would never
receive. It was not an error; it was a success with nothing in it.

That is the "0 ops waiting" shape one layer down: a state that reads as
finished and is not, with nothing on screen to say so. A device that
**failed** to sync would have been noticed. This one reported done.

The fix is not "reset the cursor on error" — there was no error. The pull
response needs to name the log it is a position in (a server or database
identity the device stores beside its cursor), and a device whose stored
identity does not match must treat its cursor as void and start from zero,
saying so. Until then, `pm clear` on the device is the only remedy, and it is
one nobody will know to apply.

## Closed

### 19. A roster row's label sat outside the sensitivity check — **fixed 2026-09-06**

| | |
|---|---|
| **Where** | `specs/form-ir-v0.1.md` §10.2 (the prose definition); `backend/app/modules/crypto/envelope.py` `check_sensitivity_propagation`; `shared/form-engine/.../Sensitivity.kt` |
| **Status** | **Closed 6 September 2026**, in the commit that made `summaryLabel` real — not one commit later |
| **What fixed it** | The walk, not the symptom. Both engines collect a repeat's own expressions per key and `checkSensitivityPropagation` walks them, so `countExpr` is covered by the same change rather than waiting for its own defect row |
| **Evidence** | `sensitivity-006` and `sensitivity-007` on both engines, and breaks 102–104 watched to fail — 102 is this defect exactly, and it fails the publish gate and not only the check |

**What a reviewer would see, the day after step 3 ships: a name marked
`sensitive` printed on the roster screen, with a clean publish behind it.**

`check_sensitivity_propagation` iterates `compiled_form.order` — fields — and
tests each field's `depends_on`. That is exact and it is the right shape for
every case it covers. **A repeat is not a field.** It gets no `CompiledField`,
so it has no `depends_on`, so nothing it carries is ever examined, and
`summaryLabelArgs` is carried by a repeat.

**Question labels are already handled, which is why this is narrow.** Both
engines collect `labelArgs` and `constraintMessageArgs` into the field's
dependency set, deliberately and with the reasoning written at the collection
site: a label interpolating a sensitive field is refused at publish by the
check that already exists. `conformance/vectors/label-005` asserts the
dependency edge itself rather than a render, precisely so that dropping it
fails something. None of that reaches a repeat's own strings.

**§10.2's prose is also narrower than both engines.** It defines a leak as a
field whose `calculate`, `relevant`, `constraint`, `required`, `readOnly` or
`default` reads a sensitive field. Labels are not in that list and are
nevertheless enforced. That is the inverse of defect 17 — there the
specification promises what no engine does, here the engines do what the
specification does not describe — and it is the reason this gap was easy to
state backwards on first reading. The list should say what is actually checked.

**Two things to do, and the order matters.**

1. **Correct §10.2's definition** to cover interpolation arguments, so the
   prose matches the two implementations that already agree with each other.
2. **Extend the check past fields when `summaryLabel` lands**, in the same
   commit that lands it, with a `sensitivity` vector for a roster row reading a
   sensitive question. Doing it in a later commit means shipping a version in
   which the leak is reachable, and the window would be invisible: a form that
   publishes clean is exactly what this check exists to make impossible.


**Why it closed here rather than in a commit of its own.** The window it would
have opened is the reason. Between a release that parses `summaryLabel` and a
release that checks it, a form interpolating a sensitive name onto the repeat
screen would publish clean — and a form that publishes clean is precisely what
this check exists to make impossible, so the gap would not have looked like
anything. Break 102 is that state, reproduced deliberately: it fails
`test_the_publish_gate_agrees_with_the_vector`, which is the assertion that the
server refuses the form rather than merely reporting on it.

**What stayed narrow.** The first reading of this defect was that §10.2 omits
labels and therefore a sensitive name leaks through any label. That was wrong
and the row said so before it was fixed: `labelArgs` and
`constraintMessageArgs` have been dependencies since §7.1 and were always
checked. Only `summaryLabelArgs` was outside, and only because a repeat is not
a field. §10.2's prose now describes both shapes, which is the other half of
the fix and the half that would have let the next person state it backwards
again.


A defect leaves this file when it is fixed, or when it is decided to be
permanent and moves into `docs/project-conventions.md` as a documented limitation. There is a
third way, and it needs recording too: the defect was never real. Deleting the
row silently would leave the next person free to re-derive the same wrong worry.

### 14. A repeat's questions reached a handset and were never asked — **fixed 2026-09-05**

| | |
|---|---|
| **Was** | `Screens.kt` and `screens.py` — `is RepeatNode -> Unit // excluded from the screen plan (spec 11.1)` |
| **Closed by** | Form IR §11.3, then the screen planner on both engines with `screens-012`…`screens-025` |

**The symptom.** A form containing a repeat imported, compiled, published,
deployed, reached a handset — and asked none of the roster's questions. Nothing
on any screen looked wrong, no control misbehaved, and nobody had anything to
report. The answers were simply missing, with no trace of why. For the pilot
customer that is the household member roster, which is most of a listing survey.

Measured on the XLSForm template's own IR before the refusal was added: 13
screens, and **none** of the roster's four questions on any of them — while the
import report said, in those words, "This form can be published."

**Why it stayed open as long as it did, which is the part worth keeping.** It
was never a missing widget. §11.1 excluded a repeat subtree from the screen plan
and deferred repeat flow to v0.2, so the collection screen offered no add
control because there was no screen for one to be on. The engine's instance
semantics had been complete and unreachable the whole time — `addInstance`,
`deleteInstance`, both bounds, eight vectors. Reading the code moved the gap
rather than closing it (`docs/phase3-pilot-scope.md` §5), and what was left was
a **spec decision**: whether an instance is a screen, a sub-sequence or a list
with a detail view. Guessing it would have been worse than the gap, and that is
why this row said so rather than saying "small".

**The interim, which behaved exactly as designed.** From 2026-09-04
`import_workbook` refused such a form — `questions_cannot_be_asked`,
`blame="platform"` — so the defect stopped being silent while it was still open.
The check was written against **reachability** and not against repeats, which is
what made it correct rather than merely effective: when §11.3 landed and a
repeat's questions became reachable, the refusal stopped firing **on its own**,
and not one line of its logic had to change. `test_xlsform_template.py` then
failed on the assertion that said the roster was still off-screen — the failure
this row predicted, arriving on schedule — and both it and
`docs/xlsform-template.md` §5 now assert the opposite.

**What replaced the exclusion.** A repeat is one screen holding the instance
list; its children are partitioned by the same §11.1 rules into an instance plan
rendered once per instance; an instance is entered and left; and no instance
count enters the screen plan, so the "N of M" a household of six reads is the
same one it read at five.

**What this did not close.** §6.2's other reason for having nowhere to navigate
to — a `calculate` carrying a failing hard constraint blocks finalisation and
has no screen. That is its own row, filed before this one landed so that closing
this could not close it by accident.

**Still to build on it:** the roster UI — the list, the add and remove
affordances, and `addLabel` / `summaryLabel`, which §2.3 now **specifies** and
neither engine parses yet. The engine no longer stands in the way, which is what
this row was about; the screen it needs exists and nothing is refused any more.

### 12. A Stata `str#` over 2,045 characters — **withdrawn, the premise was wrong**

Recorded 2026-09-03 as "written whole and unverified, because there is no Stata
in this environment to open it with". That was not a limitation of the
environment; it was a question I had not asked properly.

**What was actually true.** Reading the bytes rather than the library settles
it in one line: a `.dta` encodes each variable's type as a uint16 in
`<variable_types>`, and over 2,045 **bytes** readstat writes `32768` — a Stata
`strL`, which holds 2 GB. Nothing is out of spec and nothing is truncated. A
40,000-byte remark round-trips whole. `test_statistical_writers.py` asserts the
type code so a future readstat that stopped doing this fails a build.

**What the wrong worry was hiding.** Two real things, both found by asking the
question properly:

- **SPSS, not Stata, is where the limit bites.** readstat wrote 40,000 bytes
  into a `.sav` past SPSS's documented 32,767-byte maximum without a word — the
  same shape as its writing a `.dta` variable name Stata refuses. That is now
  enforced by `statistical.MAX_STRING_BYTES` and refused rather than truncated
  or written out of spec.
- **The check has to be in bytes.** Both formats size a string in bytes, and
  20,000 Arabic characters are 40,000 of them. The original row said
  "characters", and a character-counted check would wave straight through the
  case this product meets first. Break 69.

The lesson worth keeping is the one `known-breaks.md`'s method note now carries
in a different form: "I cannot check this here" is sometimes true and is often
a question asked at the wrong level. There was no Stata, and there did not need
to be — the file format is a published specification and the bytes were on disk.
