# RCons on DCP — what the current system does, and what it would take

**Based on:** `RconEnvironment-household_listing-sindh_ml_fm_listing_2` — the Sindh
male/female household listing survey, the largest questionnaire RCons has built.
**Date:** 4 September 2026
**Status:** analysis, for deciding scope. Nothing here is committed to.

---

## 1. The number that matters

| | |
|---|---|
| Hand-written section screens | **102 Kotlin files** |
| Lines in those sections | **48,769** |
| Total Kotlin in the app | **66,255** |
| Distinct sections in the questionnaire | 95 |
| Questions in the database | 2,128 |
| Options | 7,080 |

The questionnaire itself is already data. `questions` carries the text in three
languages, the type, the relevance, the constraint, the bounds. That part is
done and done well.

What is **not** data is the rendering and the navigation. Every one of those 95
sections has a bespoke Kotlin screen, averaging ~480 lines, written by hand for
this survey and thrown away at the end of it.

**That is the two weeks per survey.** On DCP those 48,769 lines are zero: the
form engine renders from the IR, and the same client runs every survey.

This is the entire commercial argument, and it is measurable rather than
asserted.

---

## 2. What already maps cleanly

RCons has independently arrived at most of the model DCP uses. The vocabulary
differs; the concepts do not.

| RCons | DCP | Note |
|---|---|---|
| `questions` table | Form IR | Same idea: the questionnaire as data |
| `options` table | `choices.items` | Direct |
| `samples` (1,129 rows) | Dataset / entity records | Direct |
| `list_school` (45,327 rows) | Dataset, external | Exactly what `select_one_from_file` was built for |
| `list_health_facility` (4,035) | Dataset | Same |
| `section_progress` | Case + visit + status | Keyed on `settlementCode + structureId + hhId + sectionName` |
| `enumerators` | Users with a project role | RCons has 22 for this survey |
| Roster | `repeat` | See §4 — the shapes differ in one respect |
| Three languages (ur/en/si) | i18n labels | DCP already carries per-language labels and RTL |
| `plausible_ranges.json` | Quality rules | 34 KB of range checks, already externalised |

None of the above needs new architecture. The dataset pipeline built for
`select_one_from_file` handles the 45,327-row school list without modification.

---

## 3. The one real incompatibility: skip-to versus relevance

This is the finding that decides how much work the import is.

**RCons expresses navigation as conditional jumps**, evaluated in order:

```
q8==1 to q10
q11==2 to q12a, q10<=6 to q12b, q10<15 to endSection, q11 to q13
q1>5 && q1<20 to q5, q0c>=10 to q2, q1==21 to q4, q1 to q5
```

Read as: *after this question, if q11==2 go to q12a; otherwise if q10<=6 go to
q12b; otherwise if q10<15 end the section; otherwise go to q13.*

**DCP expresses the same intent as declarative relevance**: a question carries a
condition under which it is asked. XLSForm, SurveyCTO, ODK and Kobo all work
this way.

These are not the same thing, and one does not translate mechanically into the
other:

- A single skip rule determines the relevance of **every question it jumps
  over**, not just its target. `q8==1 to q10` means q9 is not asked when q8==1 —
  so q9 acquires a relevance condition it never stated.
- Chains compose. A question skipped over by two different rules has a relevance
  that is the conjunction of both negations.
- Some skip sets are genuinely ambiguous — a jump backwards, or two rules whose
  conditions overlap, have no single declarative reading.

**Why skip-to exists:** it is how paper questionnaires are written, and RCons's
questionnaires start on paper. It is not a mistake; it is a faithful
transcription of the source document.

**Why DCP does not adopt it:** declarative relevance is what makes the
dependency graph, live recalculation and cross-engine conformance possible. A
question's visibility is a function of the answers, not of the path taken to
reach it. Changing that would undo the foundation.

### The options

| | Approach | Cost |
|---|---|---|
| **A** | Write a skip-to → relevance compiler in the importer, with a report naming everything it could not resolve | The real work. Most rules convert; the residue is manual |
| **B** | Add skip-to to the IR as a second navigation model | Rejected — two navigation models in one engine is exactly the drift the architecture exists to prevent |
| **C** | RCons rewrites the questionnaires as relevance | Not acceptable — thousands of questions, and it makes the platform harder to adopt, not easier |

**Recommendation: A**, and treat it as a first-class feature of the Migration
Center rather than a conversion script. The compatibility report already exists
and is the right place for the residue.

**This should be prototyped before anything else is scheduled.** Take the 2,128
questions in this database, run a skip-to → relevance conversion, and count what
converts cleanly. That number decides whether the pilot is a month or three.

---

## 4. Roster: mostly a repeat, with one gap

RCons's roster is DCP's `repeat`, with three ways of deciding how many
iterations:

| How the count is decided | DCP today |
|---|---|
| From an earlier answer — "how many people live here?" | `countExpr` — works |
| From the sample — a column stating the number | `countExpr` over a dataset value — works |
| **Enumerator decides as they go** — keep adding until the respondent says stop | **Not implemented** |

The third is the common case for a household member roster, and it is a small
addition: an "Add another" affordance bounded by `maxInstances`. `minInstances`
and `maxInstances` already exist; what is missing is the user-driven add.

`femaleRoasterDone` / `maleRoasterDone` on the sample row are completion flags —
in DCP that is visit status, not a column.

---

## 5. Question types RCons uses that DCP does not have

| Type | Count | Notes |
|---|---|---|
| Single Selection | 1,461 | ✅ `select_one` |
| Edit Text | 425 | ✅ `text` / `integer` / `decimal` |
| Custom Multiple Selection | 88 | ❓ Need to see what "custom" means |
| **Person Id** | 73 | ❓ Appears to reference a roster member. Probably a select from the roster |
| Multiple Selection | 65 | ✅ `select_multiple` |
| Input Field | 5 | ❓ |
| Custom Single Selection | 3 | ❓ |
| Time Picker | 2 | ⚠️ In the IR spec, not implemented |
| Enum Selection | 2 | ❓ |
| Date Picker | 2 | ✅ `date` |
| **Structure Map** | 1 | ❌ Map widget — `samples_polygon`, `samples_structure_points` |
| Note | 1 | ✅ `note` |

**Person Id (73 questions) is the one to understand first.** If it means "pick a
member from the roster", that is cross-repeat referencing, and it is a genuine
feature gap rather than a widget.

The `Custom` prefixes need a look at the section code to see what behaviour they
carry.

---

## 6. Two structural differences worth naming

**The sample is written to, not only read.** `samples` has 58 columns and mixes
sample data with collected answers — `memberAge` beside `upMemberAge` (updated).
DCP treats a dataset as immutable reference data and answers as operations.
Either the import splits them, or DCP needs a notion of a writable entity. The
first is simpler and probably correct.

**Progress is per section, not per submission.** `section_progress` records
completion for each `(household, section)` pair. DCP tracks a submission, and
screen position within it. For a questionnaire this size — 95 sections, split
male/female and v1/v2 — resuming at section granularity may matter to
enumerators. Worth confirming with them rather than assuming.

---

## 7. What DCP would give RCons that it does not have today

1. **No per-survey app build.** The 48,769 lines disappear. A new survey is a
   form and a sample, not a branch and an APK on 50 handsets.
2. **Form changes mid-fieldwork.** Deploy a new version; devices pick it up on
   the next sync. Today that is a rebuild and a re-install.
3. **End-to-end encryption.** Answers are encrypted on the device, in transit
   and at rest; the server cannot read them. Nothing in the current app does
   this — the local SQLite is cleartext.
4. **Encrypted local storage.** A lost handset today gives up every answer on
   it.
5. **Export in four formats**, including Stata and SPSS, with codes resolved to
   labels through the dataset version the form was published against.
6. **One engine on every platform.** The same form behaves identically on
   Android, iOS, desktop and the server, held there by conformance vectors.
7. **Programme managers set up surveys themselves** — no backend developer per
   survey.

---

## 8. What is missing before a pilot

In dependency order. Items 1–3 block everything else.

| # | Item | Why |
|---|---|---|
| 1 | **Enumerator login** | Today DCP identifies a device, not a person. With 22–50 enumerators, performance, back-checks and payment all depend on knowing who collected what |
| 2 | **Sample assignment**, supervisor → enumerator | Supervisors hold their own sample and their own team, and must not see each other's |
| 3 | **Skip-to → relevance compiler** | §3. Without it, importing an RCons questionnaire is manual |
| 4 | **User-driven roster** | §4. "Add another member" until the respondent stops |
| 5 | **Separate sync of sample and form** | RCons's app has separate tabs, updated on instruction. DCP pulls everything together |
| 6 | **Supervisor monitoring** | Progress against target, per enumerator |
| 7 | **Review and correction** | Flagged submissions to a queue; rejections back to the enumerator's device |
| 8 | Person Id, and the Custom types | §5 — after understanding what they do |
| 9 | Desktop data entry (dates, media) | Paper-based entry is not happening yet but is wanted. Two known defects block it |

Items 1–7 are roughly two months. Item 3 is the one with genuine uncertainty,
which is why it should be prototyped first.

---

## 9. Recommended next step

**Prototype the skip-to compiler against this database before scheduling
anything.**

The 2,128 questions here are a real corpus with real skip logic. Convert them,
count what resolves cleanly, and read the residue. That single number — the
percentage that converts without manual work — determines whether importing an
RCons questionnaire is an afternoon or a fortnight, and therefore whether the
pilot is realistic in one month or three.

Everything else in §8 is known work with known shapes. This is the only item
whose cost is unknown, and it is cheap to find out.

---

## 10. Open questions for RCons

1. What does **Person Id** do? Does it reference a member of the roster?
2. What makes **Custom Single/Multiple Selection** custom?
3. **Structure Map** — is drawing a structure polygon on a map required, or was
   it used once?
4. Do enumerators rely on resuming at **section** granularity, or would
   resuming within a submission be enough?
5. When a sample row is updated during collection (`upMemberAge` and the rest),
   is that a correction to the sample or a new answer? It changes whether the
   sample needs to be writable.
6. How is the questionnaire → CSV template tool built? If it can target a second
   format, XLSForm output would remove the skip-to problem for **new** surveys
   even if old ones still need conversion.

Question 6 is worth asking early. If that tool can emit XLSForm, the import
problem applies only to the existing corpus, not to everything RCons writes from
now on.
