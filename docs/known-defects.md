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
