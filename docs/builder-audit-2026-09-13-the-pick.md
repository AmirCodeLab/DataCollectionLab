# The capability audit: what was picked, and why — written before opening the builder

**Date:** 13 September 2026
**Status:** pre-registration. Nothing below has been attempted. The audit itself
is a separate document and does not exist yet.

This file exists because of one line in `docs/is-the-builder-usable.md` §4:

> **Choosing the questionnaire after seeing the builder.** Pick it first, or have
> somebody else pick it. Otherwise the instrument is selected to fit the result.

So the pick is recorded first, with its reasons, and with the specific things it
is expected to be hard about. Anything the audit later reports as a limit can be
checked against this list: a limit named here in advance is a prediction; a limit
that only appears afterwards is a discovery. Both are worth having and they are
not worth the same.

---

## 1. What was picked

**MICS6 — Household Questionnaire — module `HL. LIST OF HOUSEHOLD MEMBERS`,
questions HL1 to HL20, in full.**

Source: the MICS6 model Household Questionnaire as published through
IPUMS-MICS, `https://mics.ipums.org/mics-action/source_documents/survey_form_mics6_hh.xml`,
fetched 13 September 2026. UNICEF's Multiple Indicator Cluster Surveys round 6
model instrument.

It is one module, twenty questions, and it is a household listing — the same
kind of instrument as the one this platform's pilot customer runs.

## 2. Why this one

Against the four properties §3.1 of the plan asks for:

- **Real.** It is a model questionnaire that has been fielded in dozens of
  countries. Every design decision in it was made by somebody solving a survey
  problem, not a software one.
- **Public.** Freely published by UNICEF; no permission needed to reproduce it
  in a test.
- **Written by somebody else.** Nobody on this platform had any part in it. It
  predates this repository by years.
- **Chosen before opening the builder.** Today, from a search for the module
  rather than from a survey of what our builder can do. I have not looked at a
  single builder screen since deciding.

And one more reason that is specific rather than generic: **a household listing
roster is the exact shape of RCons's instrument.** `docs/rcons-current-system.md`
§4 is about their roster; §5 is about `Person Id`, which is a field pointing at a
person. If the builder cannot express MICS6's HL module, the objection is not
academic.

## 3. What is in it, and what it should be hard about

Twenty questions. Predictions, so that the audit can be checked against them:

| | The thing | Why it should be hard |
|---|---|---|
| **A roster with no known count** | HL2 is "tell me the name of each person who usually lives here", probing for more. The enumerator adds members until the respondent stops | The third row-source in `docs/rcons-current-system.md` §4, and the one it calls the common case. It exists in the IR; whether the builder offers it is the question |
| **A relevance chain two deep, per row** | HL11 (age 0–17) gates HL12–HL20; HL12 (mother alive) gates HL13; HL13 (mother in household) gates HL14 or HL15 | Relevance *inside* a repeat, evaluated per instance, built through a visual editor |
| **A range constraint with a rule an enumerator reads** | HL6: "Record in completed years. If age is 95 or above, record 95" | A constraint plus the message that explains it, plus a hint that is not the message |
| **A 16-code list with non-sequential codes** | HL3 relationship: 01–14, then **96** Other, **98** Don't Know | Whether the builder lets the stored value differ from the position. A builder that numbers options 1..n cannot express this list, and 96/98 are not decoration — they are how every survey in this family codes "other" and "don't know" |
| **Derived fields with a condition** | HL8, HL9, HL10: "record line number if woman and age 15–49" and two more | `calculate` with a condition, three times, and a builder has to make that expressible without the author writing IR |
| **A reference to another row of the same roster** | HL14 records the **line number of the mother**, who is another member of this same household. HL18 the father. HL20 copies HL14 or asks for a caretaker | **The one I expect to fail.** `docs/rcons-current-system.md` §5 examined `Person Id` and concluded it was *not* a reference into a roster — "which would have been cross-repeat referencing and a genuine feature gap". HL14 is exactly that, in a published instrument, and it is not exotic: every listing survey that records parentage needs it |
| **Two languages** | MICS instruments are fielded translated | Per-language label editing, and whether a second language is a first-class column or an afterthought |
| **A "go to next line" skip** | HL11's "2 No (Go to next line)" | Skip-to expressed against the *roster*, not the form. §3 of the RCons analysis is about skip-to → relevance; this is the version of it that lives inside a repeat |

## 4. The rule for the audit

**Build HL1–HL20 in the builder only.** No API call, no XLSForm import, no
terminal, no editing IR by hand, no `scripts/`. The console, a browser, and
nothing else.

**Every time I have to leave the builder, stop and write down why.** That list
is the output. It stands regardless of whose hand is on the mouse, which is the
whole reason half one comes before half two.

Three things that would make the result worth less, named here so they are
harder to do later:

- **Substituting a question for one the builder can do.** If HL3's codes cannot
  be 96 and 98, that is a finding, not a reason to renumber them 15 and 16.
- **Counting a workaround as a capability.** "You can express it if you write
  the expression by hand in the code tab" is a finding about the visual editor,
  and the audit records both halves.
- **Stopping at the first wall.** Note it, work around it *in the builder* if
  there is a way, and keep going — a list of eight limits is worth far more than
  the first one.

## 5. What this cannot tell us

That the builder is usable. The author of a tool finds the path through it.
This measures **capability**, and capability only; §3.2 of the plan is the part
that needs somebody else's hands, and it waits until this is read.
