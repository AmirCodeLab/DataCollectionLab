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
| **Status** | **Open, and this row is incomplete** |
| **Why not fixed** | Desktop collection was never Phase 1 scope — the desktop app is a supervision and review client (see defect 2) |

Reported from a desktop run during review. It is recorded here so it is not
lost, but **the observed symptom has not been written down and has not been
reproduced in this repository**, so the row cannot yet say what is wrong.

What is established: the date path is entirely shared code. `DateAnswer` is
common Compose, `DateUtil.kt` is pure civil-date arithmetic with no platform
half, and `todayIsoDate()` returns a local-timezone `YYYY-MM-DD` on all three
platforms. There is no desktop `actual` anywhere in it. So any desktop-only
difference comes from Material3's own desktop implementation of `DatePicker` —
which is present, not a stub, and picks up `java.util.Locale.getDefault()` and a
kotlinx-datetime calendar model where Android picks up `java.util.Calendar` for
the same locale.

**To close this row:** paste the observed symptom (what was on screen, what was
expected) and the desktop locale it was seen under.

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
