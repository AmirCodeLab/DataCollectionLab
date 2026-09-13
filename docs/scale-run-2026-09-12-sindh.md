# The first time the platform met an instrument its own size

**Date:** 12 September 2026
**What was run:** a questionnaire matching every published number of RCons's
Sindh male/female household listing — 95 sections, 2,128 questions, 7,080
options, three languages, a 45,327-row school list, a 4,035-row health-facility
list, two rosters — built, imported, compiled, published, deployed, opened in
the console's builder and pulled onto a handset.
**Why:** every form this platform has ever been shown is three screens. Nothing
had ever answered what happens at the size it was built for.

---

## 0. What this instrument is, said first because everything below depends on it

**It is not RCons's questionnaire.** What this repository holds of their largest
survey is a *measurement* of it — `docs/rcons-current-system.md` — and never the
survey. There is no `questions` table here to read, and no way to obtain one.

So `scripts/generate_sindh_scale_form.py` reproduces every published number
exactly and invents everything else: the section titles, the question text, the
option labels, every `relevant` and every `constraint`. The Urdu and Sindhi are
real script because RTL and UTF-8 width are part of what is under test; they are
not translations of anything. The generator's docstring marks the line between
reproduced and invented, clause by clause, and
`backend/tests/fixtures/xlsform/PROVENANCE.md` says it again.

What it can support is a claim about **size and shape** — whether this platform
survives an instrument 700 times the largest form it had been shown. It cannot
support any claim about RCons's content, and nothing here should be sent to them
as though it could.

Two assumptions inside it are worth naming because they move numbers:

- **One choice list per select question.** `options` is 7,080 rows against 1,617
  select questions, which is what a table keyed by question looks like. A real
  workbook shares `yes_no` across hundreds of them. So the `choices` sheet here
  is the worst case rather than the likely one.
- **Relevance is a density, not a transcription.** About 55% of non-gate
  questions carry a condition reading an earlier answer, some two levels deep.
  `docs/phase3-pilot-scope.md` §12 is why there was nothing to transcribe: the
  skip logic is Urdu prose a person converts by hand.

Reproduce it with:

```bash
python scripts/generate_sindh_scale_form.py
python scripts/import_xlsform.py \
    backend/tests/fixtures/xlsform/sindh-scale/sindh-listing-scale.xlsx --out reports/
```

The workbook is 401 KB, the two CSVs 2.29 MB and 192 KB. None is committed; the
generator is.

---

## 1. The headline, before the detail

**The platform survives the size. Three things in it did not, and only one of
them was about size at all.**

The importer, both engines, the screen planner, the publish gate, the sync
protocol and the handset all handle 2,128 questions without a change. The
console's builder renders it correctly and is too slow to use.

| Found | What it was | Where |
|---|---|---|
| **The Python engine's topological sort** | quadratic with a linear key: **16.3 s per compile**, paid by every import and every keystroke-triggered recompile in the builder. No conformance vector could ever have reported it, because the *order* it produced was right — and the Kotlin engine never had it | §3.1, break 226 |
| **The publish gate never asked whether a question could be collected** | the importer refused three unpresentable questions by name and `POST /forms/versions` published the identical document to two environments. Defect 7 one layer out | §5.1, defect 28 |
| **Every `select_multiple` and every `note` drew a blank screen on the handset** | a second hand-maintained list of types in the view model, drifted. **154 of 2,128 questions** — and 154 of RCons's real census. Nothing in this repository could see it | §6.4, defect 30 |

Only the first is a scaling defect. The other two were always there and it took
an instrument with 154 multi-selects and 95 sections to walk into them.

| | Before this run | After |
|---|---|---|
| `import_xlsform.py` over the workbook | 16.2 s | **1.3 s** |
| `check_publishable` on the IR | 16.3 s | **14 ms** |
| `POST /forms/compile` over HTTP | (would have been ~16.4 s) | **44–49 ms** |
| Screens for 2,128 questions | 2,101 | **469** with `field-list` (§4.1) |

---

## 2. The compatibility report, in full

```
sindh-listing-scale.xlsx: 2128 question(s) from 2322 survey row(s)
  dataset school                    45,327 rows  2/5 columns read  sha256:545293db1df0…
  dataset health_facility            4,035 rows  2/5 columns read  sha256:b7e8e023ac7f…
  3 error(s), 0 warning(s), 0 note(s)
  coverage: 50385 non-empty cells, all accounted for
  source sha256: 3e81d26ebddb735ae44f30280dc9c1082eed5227beae78658b5ea707c525a50a
  importer:      0.1.0

This form CANNOT be published until the errors above are resolved.
```

The three errors, verbatim, are the whole of what it refused:

```
ERROR  survey row 795,  column 'type'   `s31q0729` is a `geoshape` question. That is a
                                        valid Form IR type, but no client can present it
                                        yet, so an enumerator would see a question they
                                        cannot answer.
ERROR  survey row 1536, column 'type'   `s61q1408` is a `time` question. [same]
ERROR  survey row 2135, column 'type'   `s86q1957` is a `time` question. [same]
```

**50,385 non-empty cells, every one accounted for, and three errors.** That is
the result. Not a single warning, not a single unreported cell, and no
diagnostic about expressions, languages, choice lists, repeats or the two
companion CSVs.

Two things worth reading out of it that are easy to miss:

- **`2/5 columns read`** on both datasets. The CSVs carry `district`, `tehsil`
  and `status` that the form never names, and the importer says so rather than
  storing them silently. That is the projection a delta compares (§3.1).
- **The errors are ours, not the author's.** All three are types Form IR §2.1
  defines and no client has a widget for. The message says so in those words,
  which is the difference between "check your spelling" and "we have not built
  this yet".

---

## 3. How long the import takes, and how long compile takes

Measured in-process, so no interpreter start:

| | |
|---|---|
| `import_workbook` (workbook + both CSVs) | **1,008 ms** |
| — of which the two CSVs (49,362 rows) | 140 ms |
| `check_publishable` (§10, sensitivity, reachability) | **14.4 ms** |
| `CompiledForm` alone | 9.6 ms |
| `build_screen_plan` | 0.9 ms |
| `FormInstance` construction | 4.4 ms |
| `recalculate()` over 2,128 fields | 3.4 ms |
| IR, compact JSON | **1,527,198 bytes** |

Over HTTP, against uvicorn and Postgres:

| | |
|---|---|
| `PUT /forms/{id}/draft` (2.5 MB body) | 179 ms |
| `POST /forms/compile` | 44–49 ms, 261 KB response |
| `POST /projects/{id}/datasets` — 45,327 rows | **4.93 s** |
| `POST /projects/{id}/datasets` — 4,035 rows | 0.46 s |
| `POST /forms/versions` (publish + deploy to two environments) | **225 ms** |

### 3.1 The break the run was for

Before the fix, `import_workbook` was **15.7 s** and `check_publishable`
**16.3 s**. A profile put 14.8 of those 17 seconds in one line:

```python
ready.sort(key=self.order.index)     # inside the Kahn loop
```

`self.order` is a **list**, so `.index` is a linear scan, and the scan ran once
per ready element per iteration of the loop. About half the fields in this form
start at indegree zero, so the ready set is ~1,000 entries and the loop runs
2,128 times. On a three-screen form that is free. Here it was the entire cost of
an import and of every compile — and `POST /forms/compile` is what the builder
calls on **every edit**, so an author would have waited sixteen seconds per
keystroke-triggered recompile.

A min-heap keyed on document position produces the **identical order** in 9.6 ms.
Measured side by side on this form: 16.28 s against 0.010 s, `topo_order` equal
element for element, a 1,626× difference.

**No vector could have seen it, and that is the interesting part.** A vector
fixes the inputs and compares the outputs; the output was always right. And the
Kotlin engine never had the problem — `Runtime.kt` has always kept its document
index in a `Map` — so the two engines agreed exactly while differing by three
orders of magnitude. `docs/project-conventions.md` already says a vector cannot
see *which* artifact a caller chooses. This is the same boundary arriving
through cost rather than through choice, and it is worth adding to that section
in those terms:

> A vector compares what two engines answer. It says nothing about what either
> one spent, so two implementations of one algorithm can agree on every vector
> and be a thousand times apart.

Breaks 226 and 227, and `backend/tests/test_compile_scales.py`. Break 226 was
watched: reinstating the sort makes the guard fail with `compiling 2,000
questions took 12.0s` while the whole rest of the backend suite and every
conformance vector stay green — which is exactly the signature the row claims.

---

## 4. The screen plan's size, and whether the builder's tree survives it

### 4.1 The plan

| | |
|---|---|
| Screens | **2,101** |
| — question screens | 2,099 |
| — repeat screens | 2 |
| Instance plans | 2, of 13 and 16 screens |
| Askable questions | 2,128 (all of them) |
| Never-shown questions | 0 |
| Compile warnings | 0 |

2,128 questions and 2,101 screens, because the two rosters put 29 questions
inside instance plans and contribute one screen each. §11.3 holds: a repeat is
one screen whatever it contains.

**There was no field-list group anywhere in it, and there could not have been.**
`appearance` was a known-ignored column in the importer — "the IR carries
`appearance` but no client reads it yet", a reason that was true of the column
and not of the value. Both engines and `build_screen_plan` have implemented
§11.1's field-list screen since the partition existed; only the column was
missing, so **no workbook could ever ask for one** and every imported form was
one question per screen. For a 95-section listing survey that means an
enumerator reads `1 of 2101` and taps 2,101 times.

**Fixed the same day, and here is what it is worth.** The importer now reads
`field-list` and `table-list` on a group (break 229). Re-importing the same
2,128 questions with them grouped in blocks of six:

| | one question per screen | blocks of six |
|---|---|---|
| Screens | **2,101** | **469** |
| — question screens | 2,099 | 467 |
| — repeat screens | 2 | 2 |
| Askable questions | 2,128 | 2,128 |
| Import | 980 ms | 937 ms |
| Errors | 3 | 3 |

Nothing else moves: every question is still asked, both rosters are intact, the
same three refusals and no others. 2,101 against 469 is the difference between a
form an enumerator can work through and one they cannot — and **where the
groupings belong is RCons's to say**, because they are on the paper original and
in nothing they have sent us. `docs/xlsform-template.md` §2.1 now asks for them,
which it could not honestly do while the column was discarded.

The first run of the flag is worth keeping: it put a `begin repeat` inside an
open block, and the importer refused it — a repeat inside a field-list group is
§10.2's contradiction, and until the column was read no workbook could produce
one. Four errors, 29 roster questions unaskable, and the refusal is what said
so. The fixture was fixed, not the rule.

### 4.2 The builder

It renders, it is correct, and it is not usable.

Measured in Chrome against the real console and a real backend, with the
three-screen seeded form measured in the same tab under the same conditions as a
control:

| | Household Survey (3 screens) | Sindh listing (2,101 screens) |
|---|---|---|
| DOM nodes | 1,034 | **35,242** |
| Route change → fully rendered | 521 ms | **4,152 ms** |
| Selecting a question in the tree | 33 ms | **1,489 ms** |

The control is what makes those numbers mean anything: the automation tab runs
with `document.visibilityState === "hidden"`, which clamps `setTimeout` to one
second and stops `requestAnimationFrame` entirely. Two earlier readings taken
with `rAF` looked like multi-second freezes and were **withdrawn** — they were
the instrument, not the app. `MutationObserver` is not throttled, both columns
above are measured with it, and the small form being fast in the same tab is
what rules the throttling out.

So: **the tree survives, in the sense that it renders every one of 2,128
questions and 2,101 screen-plan cards correctly** — nested sections, RTL Urdu
and Sindhi in the label fields, inline choice tables, the screen badge on each
row. And an author who clicks a question waits a second and a half. Nothing is
virtualised; the left tree, the middle editor and the right screen plan are all
fully realised in the DOM.

Two smaller things the run showed:

- Selecting a question does **not** scroll the tree to it. On 95 sections that
  means the selected row is usually off screen.
- The draft round trip is 1.49 MB down and 2.5 MB up, and a `422` from the
  draft route echoes the entire submitted document back — 1.5 MB of response for
  a one-field schema error.

### 4.3 Preview

**The preview works, and it is the best result in this run.** The same Kotlin
engine the handset runs, compiled to Wasm, compiled the 2,128-question form in
the browser and rendered screen 1 of 2,101 with its required-answer message.

Answering one question and having the page settle: **53 ms**.

And the number underneath it moved correctly. After answering the first
question, the progress pair went from `1 / 2101` to `2 / 2096` — five screens
left the relevant set because of one answer, live, on a 2,101-screen plan.

---

## 5. Which of their question types have no equivalent, with counts

Every one of the twelve rows of `docs/rcons-current-system.md` §5 was emitted as
the nearest XLSForm spelling — the spelling `docs/xlsform-template.md` §6 tells
RCons to emit — including for the ones with no answer. Nothing was quietly
substituted with `text` to make the import clean.

| RCons type | Count | Emitted as | Outcome |
|---|---|---|---|
| Single Selection | 1,461 | `select_one` (2 as `select_one_from_file`) | imports |
| Edit Text | 425 | `text` 191 / `integer` 170 / `decimal` 64 | imports |
| Custom Multiple Selection | 88 | `select_multiple` | imports **as a plain multi-select** |
| Person Id | 73 | `text` / `integer` with `default` | imports |
| Multiple Selection | 65 | `select_multiple` | imports |
| Input Field | 5 | `text` | imports **as a guess** |
| Custom Single Selection | 3 | `select_one` | imports **as a plain select** |
| **Time Picker** | **2** | `time` | **REFUSED — no widget** |
| Enum Selection | 2 | `select_one` | imports **as a guess** |
| Date Picker | 2 | `date` | imports |
| **Structure Map** | **1** | `geoshape` | **REFUSED — no widget** |
| Note | 1 | `note` | imports |

**Three questions out of 2,128 have no equivalent: two `Time Picker` and one
`Structure Map`.** That is 0.14% of the instrument, and it is the whole of the
type gap.

But the count understates the exposure, and the report cannot see the rest:

- **96 questions were imported on an assumption, not on knowledge** — 88 Custom
  Multiple, 5 Input Field, 3 Custom Single. They imported cleanly *because this
  generator chose what to emit*. If `Custom` carries behaviour, 91 questions
  arrive stripped of it with **no diagnostic at all**, which is worse than a
  refusal. §10.2 of the RCons analysis has been asking what `Custom` means since
  4 September and it is still the open question.
- **`Structure Map` as `geoshape` is our substitution too.** There is no XLSForm
  spelling for a map widget over `samples_polygon`; `geoshape` is the nearest
  thing in the IR and it is not implemented either way.

### 5.1 A refusal that does not reach the publish gate

The importer refuses the three. `check_publishable` does not — and the form was
**published and deployed to two environments with all three questions in it**
(`POST /forms/versions` → 201, 225 ms). Nothing between the workbook and the
handset would have stopped a `time` question reaching an enumerator who cannot
answer it.

That is defect 7's shape one layer up: the collectable registry was consulted by
the importer and by nothing else, so any path that is not an import — the
builder's Publish button included — bypassed it.

**Fixed the same day.** `check_collectability` joins §10's checks in
`check_publishable`, the importer now says the sentence that module owns rather
than its own copy, and the refusal names the registry version it refused
against. It is deliberately not a §10 rule and has no Kotlin twin: §10 is a
statement about a document and collectability is a statement about an app
version, so there is nothing for two engines to agree about. `docs/known-defects.md`
28, break 228, `backend/tests/test_collectability_gate.py`.

One case it does not close, stated rather than assumed: a self-hosted install
running an older APK than its server. The form publishes here and still arrives
unanswerable there, and closing it needs a device to report its build's registry
version at registration — sync §4, which the registry file's own comment already
names as the shape left open.

---

## 6. What the engine does with 95 sections on a handset

### 6.1 The engine, measured

On the JVM (cold, single shot, so pessimistic), over the same 2,128-question IR:

| | |
|---|---|
| `FormIr.parse` | 260 ms |
| `CompiledForm` | 126 ms |
| `buildScreenPlan` | 2.0 ms — 2,101 screens, instance plans of 13 and 16 |
| `FormInstance` | 17 ms |
| `recalculate()` | 3.5 ms, then 3.2 ms |
| `set` one answer (recalculates) | 3.1 ms |
| `FormNavigator` construction | <1 ms |
| 200 `next()` steps | <1 ms total |
| `canFinalize` over 2,128 fields | 0.9 ms |
| Progress on the first screen | `(1, 2101)` |

Opening the form costs about **390 ms once**; everything after it is single-digit
milliseconds. The engine is not the problem at this scale and is not close to
being the problem.

### 6.2 The handset run

A Pixel 6 Pro on Android 17, app data cleared, the debug build installed, the
server reached through `adb reverse`.

What worked, in order: device registration (293 ms), sign-in as the seeded
enumerator (147 ms), `Sync work` fetching no document and reporting **"Updates
waiting: 2 forms and 2 lists"**, `Update forms` pulling both form versions —
including the 1.53 MB IR, 125 ms server-side — and then, correctly:

> 2 forms downloaded. They need health_facility v1 — not downloaded, school v1 —
> not downloaded. Interviews can be started now; they cannot be finalised until
> it arrives.

Then the 45,327-row school list, fetched in **23 pages of 2,000 rows** (21–40 ms
each server-side) and applied on the device in **under eight seconds** —
between the 4-second and 8-second screenshots. That is a first full download
over a loopback tunnel, so it is a measurement of the device's write path and
not of a village connection; `docs/known-defects.md` 9 (56 s to apply a delta on
a Pixel) is a different operation and is not contradicted by this.

**The form was not opened on the device at this point** — the screen timed out
during the dataset download and the handset has a secure lock, which is not
something to work around. **The phone came back later the same evening and the
walk happened after all: §6.4, and it found the worst defect in this run.**


### 6.4 The walk, on ART, and what it found

The phone came back unlocked later the same evening. The app opened the form
**offline** — no server, everything out of the local encrypted database — which
is the case that matters and is the one no earlier run had exercised at this
size.

| | |
|---|---|
| Tap the form → first screen drawn | **1.5–1.9 s** (parse 1.53 MB from SQLCipher, compile 2,128 fields, plan 2,101 screens, draw) |
| Answer one question → screen settled | **< 260 ms**, and the count moved `1 / 2101` → `1 / 2096` |
| 100 `Next` taps | 4.03 s — **40 ms per screen** |
| 193 more | 7.04 s — **36 ms per screen**, no drift 300 screens in |
| A `select_one` over the **45,327-row** school list | renders immediately as "Search 45327 options" with a lazy list |
| Typing 8 characters into that search | 0.69 s total, filtering live, one exact match found |

Every worry in the old §9 came back negative. The engine is not the constraint
on a phone either, and the searchable lazy list the registry's note describes is
real and is fast at 45,327 rows.

**And then screen 300 of 2,096 was blank.** Section heading, empty space, Next
still working. Screens 299 and 301 rendered correctly on either side.

It was not the size and it was not the dataset. `s13q0317` is a
`select_multiple` with two inline options, and `CollectionViewModel` held a
second hand-maintained list of collectable types — `SUPPORTED_TYPES` — which was
missing `select_multiple` and `note`. `questionUi` returned null for them, so
the question was dropped before any widget was chosen and the screen drew
nothing: not the label, not the "this build cannot ask you this" message the
composable's `else` branch exists for. Confirmed on a second question, screen
297, before concluding anything — "a control that does nothing is two claims".

**154 of 2,128 questions.** In RCons's own census it is the same number:
`Multiple Selection` 65 + `Custom Multiple Selection` 88 + `Note` 1 = **154
questions, 7% of the instrument, silently blank.**

Nothing could have caught it. The seed form has neither type, so five
end-to-end runs walked past. `CollectableTypesTest` drives the real composable
in both directions — the right design — but constructs its own `QuestionUi`,
and `questionUi` is what decides whether a `QuestionUi` exists. The gap was
*between* two tested things, which is break 57's shape exactly. And the registry
lists `select_multiple`, so the importer had been telling authors the question
was fine.

Fixed by **deleting** the list rather than synchronising it — break 57's lesson
again, that removing the choice beats testing it. `OneCollectableGateTest` is
the guard, and it is a lint, because what it asserts is that a piece of code
does not exist. Defect 30, break 230.

### 6.5 The re-walk, on the rebuilt APK

Because everything else about defect 30 was found by walking the phone, the fix
was too. Same device, same draft, same answer, so the screen numbers are the
ones §6.4 reported blank.

| | |
|---|---|
| **Screen 297** — `s13q0314`, `select_multiple`, 2 options | **renders**: label, two checkboxes, hint |
| Ticking both boxes | both hold — the control takes input, it does not merely draw |
| **Screen 299** — `select_one`, the control | renders, as it did before |
| **Screen 300** — `s13q0317`, `select_multiple`, 2 options | **renders** |
| **Screen 1779** — `s79q1811`, the form's one `note` | **renders**: a label and nothing under it, which is what a note is (§2.1). **The first time this platform has shown a `note` on a handset** |
| Paging 300 → 1500 | 1,200 taps advanced exactly 1,200 screens |
| **Screen 2096 of 2096** | reached; `Next` becomes `Finalize` |

The whole 2,096-screen form pages end to end and every screen in it draws.

Tapping `Finalize` refused, by name and for the right reason:

> Cannot finalise: health_facility v1 not downloaded — tap Reference data.

That is item 4's pin-readiness gate, and it fires **before** the answer gate —
which is why the run could not also observe §6.6 on the device.

### 6.6 A `note` marked `required` can never be answered

The note at screen 1779 renders with a `*`. It is marked required because the
generator marks 70% of questions required and did not exempt the one type that
stores no value — an author would make the same mistake, and nothing anywhere
stopped it.

Nothing stopped it at import (no diagnostic), nothing stopped it at publish
(`check_publishable` passed), and on the Python reference the consequence is
exact:

```
note state: required=True value=None errors=[{'kind': 'required'}]
blocking:   ['n1']
can_finalize: False
```

**A note has no value and can never acquire one, so the submission can never be
finalised** and `goToFirstBlocking` sends the enumerator to a screen holding a
sentence and nothing else. It is defect 15's family — a blocking field nobody
can answer — but not defect 15: that one has *no screen*, this one has a screen
with nothing on it.

Filed as `docs/known-defects.md` 31 and **closed the next day as a §10.2 rule**,
which is what it always wanted to be. Unlike defect 28, this **is** a property
of the document: "a question that stores no value cannot be required" is true
wherever the document is read. So it got the whole treatment — Form IR §10.2,
`form_engine/answerability.py`, `Answerability.kt`, `conformance/answerability`
(five vectors), the publish gate, and the importer reporting it against
`survey row 1975, column 'required'` of this very workbook. Breaks 231 and 232.

The generator was changed to exempt notes, so the fixture now obeys the rule it
caused. The mistake it made is the artefact worth keeping, and it is kept in the
generator's comment and in the vector set's README rather than in a file that
imports with a permanent error.

Not observed on the device, and the run says so rather than inferring it: the
reference-data gate refuses first, so the answer gate was never reached.

### 6.3 One thing the handset said that is wrong

The Updates screen's Forms card reads **"A form is tens of kilobytes."** This
form's IR is **1.53 MB**. The string is a hard-coded constant in
`UpdatesScreen.kt:101`, not a figure read from the version.

Item 4 exists so that every card on that screen states what the tap will cost —
"Update from v1 — only the rows that changed" against "Full download — about
11.3 MB", measured off rows the device holds. The reference-data cards do that.
The forms card does not, and it is wrong by fifty times on the first real
questionnaire it was shown. `docs/known-defects.md` 29.

---

## 7. What this changes

1. **The engine is not the constraint.** Neither engine, on any platform tried,
   takes longer than 400 ms to open this form or longer than 4 ms to recalculate
   it. That was the open question and it is closed.
2. **The builder is the constraint.** 1.5 s per click is not something an author
   can work in. The tree, the editor and the screen plan all need windowing
   before a 95-section questionnaire is edited in the console rather than
   imported into it.
3. **One question per screen was a product decision nobody had made.** 2,101
   taps was what an imported XLSForm produced, because `appearance` was not
   read. Now it is, and the same questions in blocks of six are 469 screens.
   What remains is not ours: RCons has to say where the groupings go.
4. **The type gap is three questions.** The `Custom` prefixes are 96 more, and
   they are unanswerable from here — §10.2 of the RCons analysis needs an answer
   from RCons before any number in §5 is trustworthy.
5. **Reference data at 45k rows is fine.** 4.9 s to publish, under 8 s to apply
   on a phone, 23 pages, no special handling — and on the phone it renders as a
   searchable lazy list that filters in under a second (§6.4).
6. **The gap between two tested things is where the worst one was.** Defect 30
   was not about size, and no test in this repository could reach it: the seed
   form lacked the types, the composable test built its own input, and the
   registry said the type was fine. What found it was walking a form that
   contained one. The lesson is not "write more tests" — it is that a corpus
   with every type in it, walked on hardware, sees what a unit test above the
   engine and a unit test below it both miss.

---

## 8. The method, and where to distrust it

- **Every number in §4.2 has a control** measured in the same tab, in the same
  state, on the three-screen form. Two readings without one were withdrawn as
  instrument artefacts. `docs/project-conventions.md`, "A control that 'does
  nothing' is two claims", is the rule that caught it, one domain over.
- **§3's before/after are both in-process** on the same machine within minutes of
  each other. The HTTP numbers are the median of three.
- **§6.1 is the JVM, not ART.** Kotlin/JVM on a laptop is not a phone; the
  numbers are there to show the shape of the cost, not the cost.
- **Nothing here measures a real network.** The handset reached the server over
  `adb reverse`, which is loopback. Every transfer figure is a floor.
- **The fixture is synthetic** (§0), and its two structural assumptions —
  per-question choice lists and invented relevance at 55% density — are the two
  places a real workbook would move a number.

---

## 9. Owed

**Nothing from §6.4 is outstanding.** The re-walk happened (§6.5): screens 297,
300 and 1779 all render on the rebuilt APK, the form pages end to end, and a
`note` has now been shown on a handset for the first time.

What the run leaves behind, in the order it matters. **Defect 31 is closed** —
it became Form IR §10.2 on 13 September, with both engines, a vector set and the
importer (§6.6).

- **Defect 29** — the Updates screen's "A form is tens of kilobytes" about a
  1.53 MB IR. Needs an IR size on the sync manifest.
- **The builder's windowing.** 1.5 s per click is the one number in this run
  that says "not usable" rather than "slower than it should be".
- **The recipe for reaching a laptop server from a real phone is not written
  down.** `docs/project-conventions.md` describes the emulator's `10.0.2.2`;
  this run used `adb reverse tcp:8000 tcp:8000` with the app pointed at
  `http://localhost:8000`, which is what makes a physical device work over
  wireless adb without touching a firewall.
