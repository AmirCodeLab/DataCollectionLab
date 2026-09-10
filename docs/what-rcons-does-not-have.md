# What RCons still does not have

10 September 2026, with Phase 3's six items done and merged.

This is not the defect register — that is `docs/known-defects.md`, twenty rows
open. It is the shorter question behind it: **a survey firm starts using this
on Monday. What do they hit?**

Everything below is drawn from what the runs showed or from what the code says,
not from the roadmap. Where a thing has been walked and works, it is not here.

---

## 1. The first day, before any data

**They cannot create their own organisation or project.** There is no
`POST /projects`, no organisation route, and no first-admin bootstrap.
`scripts/seed_dev.py` is the only path that exists and it refuses to run
outside development, on purpose — it publishes a password. Every run this
project has ever done, including all five end-to-end walks, has been against
the dev seed's single organisation.

This is the gap that gates everything else, and it is invisible from inside the
product because every screen works perfectly once a project exists.

**There is nowhere to run it.** `deploy/` has held one empty `.gitkeep` since
the initial commit, while the README lists it as "Docker Compose and deployment
tooling". `docker-compose.yml` is the development stack: Postgres with the
password `dcp`, no TLS, no backup, no restore.

**And nothing says who holds the key.** The encryption is real and the server
genuinely cannot read an encrypted project's answers — the console decrypts in
the browser with a file a person loads. Which means a lost private key is lost
data, and neither the pilot scope nor the current-system document mentions key
custody, device loss, or recovery once. This is not a missing feature; it is a
missing procedure, and it is the one whose absence is unrecoverable.

## 2. The first week, with their questionnaire

**No real RCons form has ever been imported.** Every form walked in every run
is ours: `household_survey` (three screens) and `village_check` (two
questions). Their instrument is **95 sections, 2,128 questions, 7,080 options**,
and their corpus is 22 forms. Nothing in this repository has been run at that
size. The importer has third-party fixtures, and none of them is theirs.

This is the single highest-information thing available and it costs a day.

**Two of their question types have no widget.** Their type census lists 2 Time
Pickers and 2 Date Pickers. `date` is collectable; **`time` is not** — nor is
`datetime`, `boolean`, `barcode`, `geotrace` or `geoshape`
(`specs/collectable-types-v0.1.json`, which the importer reports from, so an
author is told rather than surprised). Four questions in one instrument is not
much. It is also not zero, and it is discovered on import, not in the field.

**No photograph has ever been taken.** `image` and `signature` are listed
collectable and the capture code compiles on all three targets, but the breaks
register is explicit: no photograph has been taken through the CameraX or
AVFoundation path on a device or a simulator, because no automated environment
here has a camera. A household survey with a photo question would find out on
the first house.

**A rebuilt server strands every handset** (defect 21). A device that synced
against an earlier database sends a cursor the new one has never issued, gets
200 and nothing, and says **"All changes synced"**. The only remedy today is
clearing the app's data. The first week of a pilot is exactly when a server
gets rebuilt.

**A form cannot be tested before release** (defect 3). Every device in a
project is on production, whatever the deployment says — seen in the very first
run: the console offered "development", reported success, and the form did not
arrive until it was published to production. So "try it with two enumerators
first" is not available.

## 3. The first week, with their people

**There is no screen for quality rules.** Item 6 runs them, and the rule in its
run was created with `curl`. RCons already has **34 KB of range checks** in
`plausible_ranges.json`, externalised and ready — and there is no way to enter
them, import them, or look at them. Item 6's own outline named a rules screen;
it was not built.

**There is no export screen.** The exporter works, in four formats, with codes
resolved through the pinned dataset version, and it is measured. Nothing in the
console offers it. Getting data out means calling the API by hand.

**And the export has a ceiling** (defect 13). Every submission is held in
memory at once: 12,000 of them peak at 1,083 MB and past the limit the process
is OOM-killed. `DEFAULT_LIMIT` is 5,000 to keep that away from a reviewer. With
1,129 sample rows this survey stays under it. The next one may not.

**Resume is per submission; theirs is per section.** `section_progress` records
completion per `(household, section)` pair, and their enumerators have worked
that way for years on a 95-section instrument. DCP resumes a submission, not a
section. Whether that matters is open question §13 q2 and it has been open since
4 September. It is not answerable by asking — it is answerable by watching one
enumerator work.

**A calculate can block finalisation with nothing to fix** (defect 15): a
Finalize button that refuses, and no screen to send anyone to. Their forms are
full of derived values.

**A sample-preloaded roster does not work** (defect 16). Row order does not
reach a device, so a household member roster filled from the sample is refused
by the spec until it does. Rosters themselves work — that was fixed in item 3 —
but the shape RCons uses is the preloaded one.

## 4. Things that are fine, and worth saying so

Sample assignment with supervisor isolation, separate form and data sync with
the cost shown before the tap, supervisor monitoring whose numbers agree with
the lists beneath them, review and correction round-tripping on one submission
id, encrypted collection, and export in four formats — all walked end to end on
a real handset, all with the breaks watched to fail.

Two of the twenty open defects sit inside that chain — 15, a calculate that can
block finalisation with no screen to send anyone to, and 21, the stranded
cursor — and both are named above. The other eighteen are around it: the
builder's preview, the desktop client, performance on a held dataset, iOS
parity, the console's own gaps. **The path from a form to an exported answer
works.** What is missing is nearly all of what surrounds it.

---

## The shortest honest path to a pilot

In order, and each one is a gate rather than a task list.

### 1. A server that is theirs

Provisioning for an organisation, a project, its environments and its first
administrator, outside the dev seed. Somewhere to run it with TLS and a
**restore that has been performed**, not merely configured. And a written
answer to who holds the project's private key, where the copy lives, and what
happens when a handset is lost.

Defect 21 is fixed here or it is written into the runbook as "clear the app
after any server rebuild" — but it is decided here, because the alternative is
discovering it during fieldwork.

*Nothing below can start until this is true.*

### 2. Their questionnaire, imported once

Give RCons the XLSForm template they are owed — it has been a dependency of
item 0 since 4 September — and import one real form from the 22. Read the
report. This will surface the type gaps, the size, and whatever the corpus
holds that no fixture does. Repeat for two more forms.

*This is the cheapest step and the one that changes the plan the most. Do it
before deciding anything below.*

### 3. The two screens that make it self-service

Quality rules, so `plausible_ranges.json` can be entered rather than curled.
Export, so data leaves without an API client. Both are small. Both are the
difference between a platform and a demonstration.

Fix defect 3 with them, so a form can be deployed to development and tried
before it reaches 50 handsets.

### 4. One real day, on the real instrument

Not a demonstration: a day of actual collection, with a handful of enumerators,
on an imported RCons form at its real length, with the handsets offline for as
long as they are normally offline. Watch what happens to resume. Watch what
happens to a 95-section form on the screen. Measure the sync.

*Open question §13 q5 — how many enumerators, questions and days in the next
fieldwork — is still open, and it sizes this step. Ask it now.*

### 5. The data leaves, and somebody uses it

Export what that day produced into Stata, and give it to whoever will actually
analyse it. The loop RCons runs closes outside the platform — they generate the
next survey's sample by exporting from this one — so an export nobody has
opened is not a finished chain.

### 6. Then the pilot

And desktop entry after it, which is the phase that was always next: they
collect on paper and key in, and defects 1 and 2 are what block it.

---

## What this does not settle

Two things that are decisions rather than work, and both belong to somebody
other than this repository.

**Training.** A programme manager is expected to author forms in the builder.
Neither planning document mentions training, onboarding or support once. The
whole commercial argument is that a survey stops costing two weeks of Kotlin —
that argument depends on somebody at RCons being able to use the builder, and
nothing has tested whether they can.

**Sizing.** There is deliberately no timeline, and that stands. But the pilot
cannot be sized while question §13 q5 is unanswered, and it has been open for
six days.
