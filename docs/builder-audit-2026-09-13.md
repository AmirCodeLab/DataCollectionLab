# Capability audit: MICS6 HL in the builder, and where it stops

**Date:** 13 September 2026
**What was run:** MICS6 Household Questionnaire, module `HL. LIST OF HOUSEHOLD
MEMBERS`, built in the console's form builder and nothing else.
**Pick and predictions:** `docs/builder-audit-2026-09-13-the-pick.md`, written
and committed before the builder was opened.
**This is half one of `docs/is-the-builder-usable.md`.** It measures
**capability** and says nothing about usability: the author of a tool finds the
path through it. Half two needs somebody else's hands and waits.

---

## 0. The answer

**A real MICS6 module can be built in the builder, and one question in it
cannot be expressed at all.**

Signed in as the seeded `pm` account — the programme-manager role, not admin —
a form was created, four HL questions were built with their real text, real
codes and real constraints in two languages, and the form compiled at every
step. No terminal, no API call, no XLSForm, no hand-edited IR.

The wall is the one predicted: **HL14, HL18 and HL20 record the line number of
another member of the same household, and a row of a roster cannot refer to
another row.** Everything else met or beat the prediction.

---

## 1. What was built

`mics6_hl`, revision 28, a repeat `members` holding four questions:

| HL | id | type | what it exercised |
|---|---|---|---|
| HL2 | `hl2_name` | text | required, hint, two languages |
| HL3 | `select_one`¹ | select_one | **16 inline codes, 01–14 plus 96 and 98**, labels in two languages |
| HL6 | `hl6_age` | integer | `${hl6_age} >= 0 and ${hl6_age} <= 95`, a constraint message, a severity, a relevance reading HL3 |
| HL14 | `hl14_mother_line` | integer | the cross-row reference — see §3 |

¹ HL3's id stayed `select_one`: an id rename commits on blur, and one edit was
made through a synthetic event that never blurred. That is this run's
instrument, not the builder — the same rename done with real keystrokes worked
immediately, twice.

Not built, and so not claimed either way: HL4, HL5, HL7–HL13, HL15–HL19. The
audit stopped when the predictions had been answered rather than at twenty
questions, because the list of walls is what the exercise is for.

---

## 2. What worked, against the predictions

| Prediction | Result |
|---|---|
| **A. A roster with no known count** | ✅ **and it is the default.** "where the rows come from" offers `the enumerator adds rows` first, with `an answer decides the count`, `a fixed list in the form`, and `rows from the sample` — the last disabled with the engine's own reason quoted |
| **C. A range constraint with a message an enumerator reads** | ✅ Constraint, a per-language constraint message, **and a severity select** — "an error blocks finalisation, a warning does not (§6.1)". MICS-style soft checks are expressible |
| **D. A 16-code list with non-sequential codes** | ✅ **The single best result.** The choices table has `value`, `label en`, `label ur` as separate columns, so `96 Other` and `98 Don't Know` are exactly what a survey needs them to be. A builder that numbered options 1..n would have failed the module outright |
| **G. Two languages** | ✅ Every label, hint, constraint message, add-row label and choice label is per language, and the Urdu fields right-align. RTL is not retrofitted |

Three more things worth recording that were not predicted:

- **The palette is the registry over the wire.** Unavailable types are listed
  and disabled with `collectable-types-v0.1.json`'s own sentence — "In §2.1, no
  widget yet" — so an author reads why rather than wondering where `time` went.
- **The plan pane answers every edit.** Screens renumber live, a stale plan is
  dimmed and labelled, and `integer — no longer in the form` appeared the
  instant a question was renamed.
- **The refusal is the server's, verbatim.** An empty expression term produced
  `unresolvable reference '' in field 'hl6_age'` and the plan pane said "The
  plan below is for the last version that compiled." The document that does not
  compile is never silently kept.

---

## 3. The wall: a roster row cannot refer to another row

MICS6 HL14: *Record the line number of mother.* HL18 the father's. HL20 copies
HL14 or asks for the caretaker. All three point at **another member of the same
household** — another row of the same roster.

**The reference picker, from inside the repeat, offers one section and three
entries:**

```
THIS INSTANCE — MEMBERS
  hl2_name     HL2. Please tell me the name of each …
  select_one   HL3. What is (name)'s relationship t…
  hl6_age      HL6. How old is (name)?
```

Nothing else. No other row, no `members[n]`, no household-level view of the
roster from within it.

**The aggregate form does work**, which is a real partial capability. This was
accepted and compiled:

```
${hl14_mother_line} <= count(${members[].hl2_name})
```

So the line number can be bounded by the number of members. What cannot be done
is look at the row it points to. Indexing by an answer is a parse error, with
the caret on the offending character:

```
${members[${hl14_mother_line}].hl3_relationship} != ''
                             ^
unexpected character ']'
```

A row index must be a literal. So none of these can be expressed, in the
builder or in the IR:

- the mother's line number must belong to a member of this household;
- …who is female;
- …who is not this person;
- …and whose age is greater than this person's.

Every one of those is a check a household listing wants, and MICS's enumerator
instructions assume a supervisor doing them on paper.

**What the platform can do instead**: collect HL14 as a plain integer that
nobody validates. That is what paper does. It is not what a digital instrument
is bought for, and this is the first module we have tried that needs more.

### 3.1 Why this is worth more than a feature request

`docs/rcons-current-system.md` §5 examined RCons's `Person Id` — 73 questions —
and concluded, correctly, that it was *not* a reference into a roster:

> The reading it invited was "pick a member from the roster", which would have
> been cross-repeat referencing and a genuine feature gap. It is not that.

That conclusion was right about RCons and it closed the question one module too
early. **MICS6 HL14 is exactly the thing that analysis said would have been a
genuine feature gap**, in a published instrument fielded in dozens of countries,
and it took twenty minutes to find once a real questionnaire was picked instead
of a synthetic one.

---

## 4. Every time I had to leave the builder

The rule was to stop and write down why. Three, and only the third is a wall:

1. **Interpolating a field into a roster row's summary.** The row-summary field
   says so itself: *"{0} slots need summaryLabelArgs, edited as IR (§2.3,
   §7.1)"*. So a roster showing `Fatima, 34` rather than `1, 2, 3` needs the IR
   edited by hand. The builder is honest about it, which is the good half.
2. **Interpolating an answer into a question's label**, for the same reason and
   with the same note under the label field: *"{0}, {1} slots interpolate
   labelArgs, edited as IR (§7.1)"*. MICS6 writes `(name)` in twelve of HL's
   twenty questions and means the member's name — so this is not a corner case
   in this module, it is most of it. **Twelve questions read `(name)` on screen
   where a fielded instrument reads the person's name.**
3. **The cross-row reference** (§3). Not a matter of leaving the builder — there
   is nowhere to go.

Items 1 and 2 are the same missing thing: `labelArgs` / `summaryLabelArgs` have
no editor. That is one piece of UI, and it would move this module from "reads
(name)" to "reads Fatima".

---

## 5. Observations that are not walls

Recorded because half two will meet them, and a stranger will not work around
them the way the author did:

- **The editor pane keeps its scroll position when a different node is
  selected.** Adding a question mid-form leaves you looking at the middle of the
  previous question's editor; `id` and `label` are off-screen above. This run
  typed a question's id into its hint box because of it. A person would see it;
  a person adding their fortieth question would still be scrolling up each time.
- **The test-case pane's message names the wrong cause.** While the form did not
  compile it read: *"Not run: the engine is unavailable (unresolvable reference
  '' in field 'hl6_age'). Build it with scripts/build_engine_wasm.sh."* The
  engine bundle was present and fine; the form was broken. The remedy offered —
  build the Wasm bundle — is for a different problem, and it is the kind of
  wrong instruction that costs an hour.
- **Each question in a roster is its own row screen.** Four questions, four row
  screens. MICS6 fills HL2–HL4 vertically for every member and then asks
  HL5–HL20 person by person, which is a different rhythm. Whether a field-list
  group *inside* a repeat collapses them was **not tested**.
- **Escape dismisses the pickers**, the palette menu is not clipped, badges sit
  on their own line, and the palette and tree carry accessible names — the five
  defects of `docs/e2e-run-2026-09-07.md` are fixed and were fixed on the day.

---

## 6. What this run did not test

Named so the result is not read as wider than it is:

- **A two-level relevance chain.** One level was built and accepted
  (`hl6_age` relevant on HL3). HL11 → HL12 → HL13 was not built, so "relevance
  inside a repeat, two deep, through the visual editor" is **untested**.
- **`calculate`.** The fieldset is there, with Visual and Code tabs. It was
  never filled, so HL8–HL10 ("record line number if woman and age 15–49") are
  untested.
- **The visual expression editor.** Driving it through synthetic events was
  unreliable and the run switched to the Code tab — which is part of the builder
  by design (scope §2: visual *with* a code escape hatch), but it means **this
  audit says almost nothing about the visual editor**, which is precisely the
  half a programme manager would use. That is half two's to answer, and it is
  now the most important thing half two will look at.
- **Publishing.** The form was never published or put on a phone. This is a
  capability audit of the authoring surface only.

---

## 7. What follows

1. **`labelArgs` needs an editor.** Twelve of twenty MICS6 HL questions say
   `(name)`. Without it, the single most common pattern in household listing
   instruments reaches an enumerator as literal parentheses. This is the
   cheapest high-value thing this audit found.
2. **Cross-row reference is a real gap and now has a real instrument behind
   it.** It is an IR question before it is a builder question — §3 — and
   `docs/rcons-current-system.md` §5's conclusion should be read as "not needed
   *by RCons's Person Id*", not "not needed".
3. **Half two should watch the visual expression editor above all**, since this
   run could not.
4. The scroll-position and wrong-remedy observations in §5 are small and would
   each waste a stranger's session.

**The commercial argument survives this audit.** A programme manager can express
a real module of a real international instrument in the builder, including the
parts — non-sequential codes, per-language labels, an enumerator-driven roster,
a constraint with a message — that a naive builder gets wrong. What it cannot do
is name another person in the household, and it cannot yet put a person's name
inside a question.
