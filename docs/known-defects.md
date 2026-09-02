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
| **Why not fixed** | Desktop collection was never Phase 1 scope. Wiring a Swing file chooser and a location source into the desktop app would build a collection path nobody uses and nothing tests — the fix is to stop drawing the widgets, not to implement them |

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

