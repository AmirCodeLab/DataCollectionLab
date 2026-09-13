# Is the builder usable by a programme manager?

**Date:** 13 September 2026
**Status:** a proposal for how to find out. Nothing here is scheduled, and it is
not gate 3. Written down because it is an analysis that would otherwise exist
only in a terminal (`docs/project-conventions.md` rule 12), and because the
last builder analysis to live that way was lost.

---

## 0. Why the question is the right one

"Programme managers set up surveys themselves — no backend developer per
survey" is item 7 of `docs/rcons-current-system.md` §7, and with the 48,769
lines of hand-written section screens it is **the commercial argument**. Every
other claim this platform makes — offline collection, encryption, supervision,
export — has a competitor who also makes it. This one is the reason a survey
firm would move.

It has never been tested. Every form in every run was authored by the person who
wrote the builder, in a terminal or through the API.

---

## 1. What the runs actually say

Two builder runs, both on 7 September 2026, both in `docs/e2e-run-2026-09-07.md`.
A form was built in the builder, published, deployed and collected on a handset,
with no console error and no 5xx. That is a real result: **the mechanism works
end to end.**

Look at what was built. Text, integer, select_one, date at the top level; a
plain group; a field-list group; a repeat. The fields are called `text_4`,
`select_one`, `integer`, `decimal`.

Those are palette item names. **The form was built from the palette outward —
"add one of each thing the builder offers and check it survives" — rather than
from a questionnaire inward — "here is a page of questions, express it."**

That is a sharper statement of the weakness than "its author walked it", and it
is the one that matters:

- **Nobody had to decide how to express a question**, because no question
  existed to express. Every node was chosen from a menu of nodes.
- **Nobody met a question the builder cannot express**, because the form was
  drawn from what it can.
- **Nobody hit the naming rules**, because every name was generated.
- **The vocabulary was never a barrier** — relevance, calculate, field-list,
  row source, sensitive — because the person driving already had it.

A form built that way can pass while a real questionnaire fails, and nothing in
the run would have shown the difference.

## 1.1 The second piece of evidence, and it is the adversarial one

In the week of 8–13 September this platform **accepted, published and deployed
to two environments** a form containing:

- three questions no client can present (defect 28),
- a `note` marked `required`, which can never be answered, so the submission
  could never be finalised (defect 31),
- and 154 questions — 7% of the instrument — that rendered as **blank screens**
  on a handset (defect 30).

Every one of those was an author mistake. Two of them were made by a *program*
following ordinary rules ("mark most questions required"; "emit the nearest
type"). The platform caught **none** of them until somebody went looking, and
all three are now fixed only because a 2,128-question form was walked by hand.

That reframes the question usefully. The risk is not mainly *can a programme
manager find the button*. It is **will they build a form that is quietly
wrong** — and the measured answer, for the three kinds of wrong we happen to
have tested, was yes.

---

## 2. What "usable" decomposes into

Four questions hide inside it, and they do not need the same instrument:

| | Question | Needs a user? |
|---|---|---|
| **a** | Can the builder **express** a real questionnaire at all? | No |
| **b** | Can somebody without our vocabulary **drive** it? | Yes |
| **c** | Does it catch their mistakes, in words they can act on? | Partly — §1.1 is already evidence |
| **d** | Is it faster than the two weeks per survey it replaces? | Yes, and a stopwatch |

**(a) gates the rest.** If a roster with preloaded rows means leaving the
builder, no amount of usability polish matters and the user test is wasted.

---

## 3. The smallest honest test

Two halves, in order. Roughly a day each, plus 45 minutes of somebody else's
time. And one thing before either.

### 3.0 First, fix the five console defects we already know about

`docs/e2e-run-2026-09-07.md` records five, all of them in the authoring path:
popovers that do not dismiss on Escape, an Add menu clipped mid-word, badges
sitting over tree labels, a publish panel that keeps a stale refusal, and no
accessible names on the palette or the tree.

They were found by the author, who worked around them without noticing. **A
stranger will not work around them**; they will spend the session on them, and
the session will measure our unfixed backlog instead of our design. About a day,
and it removes the noise.

### 3.1 Half one — the capability audit. No user. Done by us.

Take **one real questionnaire written by somebody else.** Not ours, not
invented, and not RCons's (we do not have theirs). A published instrument of the
right shape: a DHS or MICS household listing module, or the listing section of
any national survey — these are freely available and were written by people with
no knowledge of this platform.

Take **one section, about 40 questions**, chosen **before opening the builder**
and chosen because it contains the hard things: a roster, a relevance chain two
levels deep, a constraint with a message an enumerator reads, a select from a
long external list, and two languages.

Then build it **in the builder only.** No API call, no XLSForm import, no
terminal, no editing IR by hand. The rule that makes this a measurement: **every
time you have to leave the builder, stop and write down why.**

The output is a list of the places the builder cannot go. That is evidence
regardless of whose hand is on the mouse, and it is the finding that would be
most expensive to make *after* putting somebody in front of it.

**Say in the write-up what it does not prove.** The author will find the path
through their own tool. This measures capability and says nothing about
usability.

### 3.2 Half two — one person who is not us. 45 minutes. This is the test.

**n = 1 is enough at this stage**, because what we are looking for is a wall,
not a preference. The first stranger finds the catastrophes; the fifth finds the
polish, and we are nowhere near polish.

**Who.** The criteria matter more than the job title:

- has designed a questionnaire before, so they know what they are trying to say;
- has never seen this builder;
- is not a programmer.

A research assistant, an M&E officer, an academic colleague, a friend who has
run a survey. **Not RCons.** Putting an unproven builder in front of the pilot
customer is a sales risk that cannot be taken back, and the whole point is to
have the finding before they see it.

**The task.** Hand them a **one-page paper questionnaire** — 8 to 12 questions,
including one that is conditional and one roster — and say: *build this so it
can go on a phone.* A specific artefact with a specific end state. Not "have a
look around", which measures curiosity.

**The protocol, whose entire content is restraint.**

- They share their screen. You say nothing except *"what are you trying to
  do?"* and *"what did you expect to happen?"*
- 45 minutes, hard stop. If they have not published, that is the result.
- Write down three things: where they stopped, every word they had to ask
  about, and **every thing they got wrong and did not notice.**

**The success criterion, and this is the part to be hard about.** Not "did they
finish" and not "did they like it". It is:

> **Does the form they built ask the questions on the paper?**

Compare their published IR against the page, question by question, including the
conditional one and the roster. That is objective, and it is the only criterion
that catches a silent failure — which, on the evidence of §1.1, is where the
risk actually lives.

**A second criterion, if the first passes and it is cheap.** Give them a second
page and watch them do it again. The second form is where you find out whether
they learned the tool or were carried by novelty.

---

## 4. What would make this test dishonest

Each of these is easy to slip into, which is why they are written down before
the test rather than after:

- **Choosing the questionnaire after seeing the builder.** Pick it first, or
  have somebody else pick it. Otherwise the instrument is selected to fit the
  result.
- **Sitting beside them answering questions.** Silence is the instrument. Every
  answer you give is a finding you have deleted.
- **Counting "they finished" as success** without checking what they built.
- **Running it on a large form.** That measures the builder's scale defect,
  which is already measured (`docs/scale-run-2026-09-12-sindh.md` §4.2: 1.5 s
  per click at 2,128 questions) and is not this question.
- **Fixing a defect they hit, mid-session.** Write it down, let them work
  around it, keep watching. A session spent debugging is a session not spent
  observing.
- **Reporting the session and not the diff.** The write-up records what they
  built against what they were given, or it is an anecdote.

---

## 5. What it cannot tell you

Worth naming so the result is not over-read:

- whether a programme manager can **maintain** a form across a season;
- whether they can **debug** one that is already in the field;
- whether two people editing one form **collide**;
- whether they can do any of it on their own machine, with their own IT, their
  own browser and no one to ask.

Those need the pilot. This test answers exactly one question: **can a competent
stranger turn a page of questions into a working form, without us in the room.**

---

## 6. Cost, and where it sits

| | |
|---|---|
| Fix the five known console defects | ~1 day |
| Capability audit (§3.1) | ~1 day |
| One session plus its analysis (§3.2) | 45 min of theirs, ~½ day of ours |

Call it two and a half days to put evidence under the commercial argument.

**It belongs before gate 3, not after.** Gate 3 is the two self-service screens,
and self-service presumes the thing being served is usable. If §3.1 finds that a
real section cannot be built in the builder, gate 3's scope changes — and that
is much cheaper to learn now than after the screens are built.
