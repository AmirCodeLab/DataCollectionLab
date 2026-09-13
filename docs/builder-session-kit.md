# Half two: the session kit

**For:** `docs/is-the-builder-usable.md` §3.2 — one person who is not us, 45
minutes.
**Status:** ready to run. Everything needed is in this file.
**Waits on:** nothing. Half one is done (`docs/builder-audit-2026-09-13.md`).

---

## 0. The one change half one makes to this session

**The visual expression editor is the primary target.** Half one drove the
builder through synthetic events, found that unreliable, and used the Code tab
instead — so it says almost nothing about the visual editor, which is the half a
programme manager would actually use. Everything else in the builder now has
some evidence behind it. This does not.

So the paper questionnaire below is built around **one conditional question**,
and the observation that matters most is *what happens when they reach it*.

---

## 1. Who

Three criteria, and the job title is not one of them:

- has designed or run a questionnaire before, so they know what they are
  trying to say;
- has never seen this builder;
- is not a programmer.

A research assistant, an M&E officer, an academic colleague, a friend who has
run a survey.

**Not RCons.** Putting an unproven builder in front of the pilot customer is a
risk that cannot be taken back, and the point is to have the finding before they
see it.

---

## 2. What they are given

A single sheet. Hand it over, say *"build this so it can go on a phone"*, and
stop talking.

> ### Water and sanitation — household
>
> **W1.** What is the main source of drinking water for members of this
> household?
> `1` Piped into dwelling · `2` Public tap · `3` Tube well or borehole ·
> `4` Protected well · `5` Unprotected well · `6` Tanker truck ·
> `7` Surface water · `96` Other
>
> **W2.** How long does it take to go there, get water, and come back?
> *Record in minutes. If the water is on the premises, record 0.*
> Minutes: `___` (0 to 300)
>
> **W3.** *Ask only if W1 is not "Piped into dwelling".*
> Who usually goes to this source to collect the water?
> `1` Adult woman · `2` Adult man · `3` Female child under 15 ·
> `4` Male child under 15 · `8` Don't know
>
> **W4.** Does this household have a toilet facility?
> `1` Yes · `2` No
>
> ### Household members
>
> *List every person who usually lives here. For each one:*
>
> **M1.** Name
> **M2.** Age in completed years (0 to 95)
> **M3.** Relationship to the head of household
> `1` Head · `2` Spouse · `3` Son or daughter · `4` Other relative ·
> `96` Not related

Nine questions. It is deliberately shaped, and here is what each part is for —
**do not tell them this**:

| Part | What it tests |
|---|---|
| W1's `96 Other` | whether they find the stored value is separate from the label |
| W2's range and the "record 0" instruction | constraint, constraint message, hint — three different boxes |
| **W3's condition** | **the visual expression editor. The primary target** |
| The member list | that they reach for a repeat at all, and find the enumerator-adds-rows source |
| M3's `96` | the same as W1, on the second try — did they learn it |

---

## 3. The protocol

The whole content of it is restraint.

- They share their screen. **You say nothing** except *"what are you trying to
  do?"* and *"what did you expect to happen?"*
- 45 minutes, hard stop. If they have not published, that is the result.
- Do not fix a defect they hit. Write it down, let them work around it, keep
  watching. A session spent debugging is a session not spent observing.

**Before they arrive**: a fresh database, seeded, and an account that is *not*
an admin — the `pm` account the seed creates, with the published dev password.
Half one used it and every screen a programme manager needs was reachable.

Write down three things, and only three:

1. **Where they stopped.** Every pause longer than about twenty seconds, and
   what was on screen.
2. **Every word they had to ask about.** "Relevance", "calculate", "field-list",
   "row source", "sensitive", "argument". A word they ask about is a word the
   interface should not have used alone.
3. **Every thing they got wrong and did not notice.** This is the valuable one
   and the easiest to let slide past.

---

## 4. The success criterion

Not "did they finish" and not "did they like it":

> **Does the form they built ask the questions on the sheet?**

Compare their published IR against the page, question by question. The table
below is the whole marking scheme; each row is yes or no.

| | Check |
|---|---|
| 1 | Nine questions exist |
| 2 | W1 stores `96` for Other — not `8`, not the position |
| 3 | W2 refuses 301 **and says why** in words an enumerator could act on |
| 4 | W2's "record 0 if on the premises" is somewhere the enumerator will see it |
| 5 | **W3 is asked when W1 is anything but piped, and not asked when it is piped** |
| 6 | The member list is a repeat, and the enumerator can add rows without knowing the count in advance |
| 7 | M2 refuses 96 |
| 8 | M3 stores `96` for Not related |
| 9 | The form published |

**Row 5 is the one to watch.** Rows 1–4 and 6–9 are capability, and half one
already knows the builder can do all of them. Row 5 is the visual expression
editor, and nothing knows anything about it.

A second, cheaper criterion if the first passes: **hand them a second sheet and
watch them do it again.** The second form is where you find out whether they
learned the tool or were carried by novelty.

---

## 5. What would make this dishonest

From `docs/is-the-builder-usable.md` §4, repeated here because this is the file
that will be open during the session:

- sitting beside them answering questions — every answer you give is a finding
  you have deleted;
- counting "they finished" without checking what they built;
- fixing a defect mid-session;
- reporting the session and not the diff. **The write-up records what they built
  against what they were given, or it is an anecdote.**

One more, specific to this sheet: **do not explain what W3's italic line
means.** "Ask only if W1 is not piped" is how a questionnaire writes a
condition, and whether they can turn that sentence into a relevance expression
without help is the single thing this session exists to find out.

---

## 6. What it cannot tell you

Whether they can maintain a form across a season, debug one already in the
field, or work alongside a second editor. Those need the pilot. This answers one
question: **can a competent stranger turn a page of questions into a working
form, without us in the room.**
