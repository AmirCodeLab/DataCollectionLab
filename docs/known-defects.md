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

## Closed

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
