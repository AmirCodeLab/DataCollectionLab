# Decision: excluding a member from their own list, and what the paper said when asked

**Date:** 14 September 2026
**Status:** decided. Taken before any of `docs/proposal-row-choice-question.md`
was implemented, because two of the three findings below change the shape of
the thing rather than an argument to it.
**Decides:** §8 of `docs/proposal-row-choice-question.md` — *"the one thing I
have not decided"*.

---

## 0. The short version

1. **Self-exclusion is required by the module that motivated the feature.** Not
   inferred from it — required by all three of its questions, and at HL20 the
   instrument spends a reserved code to avoid needing it.
2. **`excludeSelf: true` on the `rows` kind, not a §4.2 grant.** The evidence
   demands exactly one predicate, the flag is the only form of it an author
   cannot get subtly wrong, and it leaves the general grant available later.
   A grant does not stay available: it is authoring surface, and forms in the
   field are written against it.
3. **A third finding, not asked for and not in the proposal: the list HL14
   needs is per instance.** The question sits on the member's own row, so every
   member's list is a different list. `choices(field_id)` cannot express that —
   it takes a field id and resolves a repeat field against *the first
   instance*, in a line that says it is a simplification. The feature makes
   that simplification wrong.
4. **A fourth: HL20 needs an option that is not a row** (`90`, "No one"). Real,
   expressible today by other means, and deliberately **not** built now. §5
   writes out the workaround so that the decision is a decision rather than an
   omission.

---

## 1. The question

`docs/proposal-row-choice-question.md` §8, in full:

> **Whether a member can be offered as their own mother, and how to exclude
> them.** MICS6 cannot; the roster row for Fatima should not offer Fatima.
>
> `filter` is the mechanism, with `$row` bound to the candidate **instance** —
> and that needs a way to say *"the candidate is not the instance I am
> answering in"*, which means comparing two identities, which means an
> expression can see an instance id. Nothing in §4.2 grants that today, and
> §2.3 already declined to grant it for `_rowKey`.

And the reason it is decided now rather than after: a §4.2 grant added once
forms exist that were authored without it is a retrofit, and the spec's
reference table is the part of the IR with the least room to be wrong.

---

## 2. What the paper says

Two sources, both consulted for this decision.

**The model instrument.** MICS6 model Household Questionnaire, module `HL`, as
published through IPUMS-MICS —
`https://mics.ipums.org/mics-action/source_documents/survey_form_mics6_hh.xml`,
the same source `docs/builder-audit-2026-09-13-the-pick.md` recorded. Fetched
again 14 September 2026.

> **HL13.** Does (name)'s natural mother live in this household? `1 Yes` `2 No
> (Go to HL15)`
>
> **HL14.** Record the line number of mother and go to HL16: `_ _`
>
> **HL18.** Record the line number of father and go to HL20: `_ _`
>
> **HL20.** Copy the line number of mother from HL14. If blank, ask: Who is the
> primary caretaker of (name)? **If 'No one' for a child age 15-17, record
> '90'.** Number: `_ _`

**The interviewer's manual.** *Instructions for Interviewers*, MICS Punjab 2017
(Bureau of Statistics, Government of the Punjab) —
`https://bos.punjab.gov.pk/system/files/Manual%20Instructions%20for%20Interviewers%2026.10.2017.pdf`,
205 pages, fetched 14 September 2026. A country adaptation, not the model: its
HL7A/HL7B are additions. Its HL11–HL20 numbering and skip pattern are the
model's, and it is the *manual* the model questionnaire does not carry. That
this is the pilot's own province is a convenience, not the reason it was used.

> **HL14.** *Record the line number of mother and go to HL16.*
> If the natural mother is living in the household, ask who she is (**she must
> be recorded in the List of Household Members if she lives in the household**),
> record her line number and go to HL16.
>
> **HL18.** *Record the line number of father and go to HL20.*
> If the natural father is living in the household, ask who he is (he must be
> recorded in the List of Household Members if he lives in the household),
> record his line number and go to HL20.
>
> **HL20.** … If the child is living with his/her mother in the same household,
> you will copy the line number from HL14, and will not need to ask this
> question. If HL14 is blank or '00', then you will ask this question to
> establish the primary caretaker of the child. **This person should be a
> member of the household (who should be age 15 or above).**
>
> … If the child is age 15-17 and there is no primary caretaker of this child,
> record '90'. You will need to interview the child him/herself as he/she is
> emancipated.

And the structure around them, which is what makes the answer unambiguous:

> **HL11.** Age 0-17? … For everyone age 18 and older, HL12-HL20 will be left
> blank.
>
> **HL12.** Is (name)'s natural mother alive? … If the child's natural mother is
> not alive or if the respondent does not know, you will continue with question
> HL16.

---

## 3. Finding 1 — self is never a valid answer, in any of the three

**HL14 and HL18 by definition.** The questions are asked of a child aged 0–17
(HL11) whose natural mother is alive (HL12) and lives in this household (HL13).
Nobody is their own natural mother. The wrong answer is not merely implausible,
it is impossible, and it is impossible for every member the question is asked
of — not for an edge case.

**HL20 by construction, and this is the stronger evidence.** HL20 is the one
place where "this person is their own answer" has a plausible reading: a
15–17-year-old living alone is their own carer in every ordinary sense. The
instrument does not record that as a self-reference. It spends a **reserved
code, `90`**, on it, and instructs the interviewer to record `90` and treat the
child as emancipated. An instrument that wanted self-reference had the obvious
opportunity here and declined it, in favour of a sentinel that is deliberately
outside the line-number range.

So: three questions, three different reasons, one answer. The roster row for
Fatima must not offer Fatima.

### 3.1 Why the paper never says "not yourself"

Because the paper has no list. HL14's answer space on paper is two blank boxes
and the enumerator's knowledge of who is on the roster; the instruction is
*"ask who she is"*, and the enumerator writes `04`. There is nothing to exclude
from, so the question never comes up, and the supervisor's edit pass is where a
child recorded as their own mother would be caught — after the field visit,
against a paper form, possibly weeks later.

**The obligation arrives with the list.** The moment the platform offers a
chooser instead of two boxes, it is making a claim about what a permitted
answer is, and every name it shows is a name it is saying could be the mother.
Offering Fatima her own name is not a neutral omission of a check the paper
also lacks — it is a new wrong option that the paper never presented, created
by the act of digitising the question.

This is the general form and it is worth keeping: *converting a write-in into a
pick-list moves a validity question from the supervisor's desk into the
instrument, whether or not the instrument is ready to answer it.* We are the
ones who introduced the list. The check comes with it.

---

## 4. Finding 2 — the list is per instance, and the engines cannot say that yet

HL14 is asked **on the member's own row**. `hl14_mother` is a field inside
`members`, offering the rows of `members`. So:

- Ali's row must offer everyone except Ali;
- Fatima's row must offer everyone except Fatima.

**These are two different lists for one field**, and that is true for any
self-excluding rows question — the flag does not create the problem, it makes
an existing simplification untenable.

Today, both engines expose:

```python
def choices(self, field_id: str) -> list[dict[str, Any]]:
```

and resolve a repeat field's scope like this (`runtime.py`, `_scope_of`):

> Resolution inside a repeat is the instance currently being evaluated;
> `choices()` called from outside one uses **the first instance**. Repeats with
> dataset-backed lists are not exercised until v0.2's repeat screen flow, so
> this is deliberately the simple reading.

That comment is honest and it has now expired. A rows question inside the
repeat it draws from is precisely a repeat field with a scope-sensitive list,
and "the first instance" would hand Ali's list to Fatima — which, for
`excludeSelf`, is the single most damaging wrong answer available: her own name
present, and Ali's missing.

**The decision:** `choices()` takes an **instance-qualified path**, exactly as
every other address into a repeat already does.

```
choices("mother")                   # a form-level question, unchanged
choices("members[i2].hl14_mother")  # this member's list
choices("hl14_mother")              # inside a repeat: the first instance, as today
```

The last line is kept rather than made an error, because it is what the
existing behaviour is and no vector should change meaning silently as part of
this work. It is the reading a form-level caller gets and it stays documented
as a simplification.

The vector format needs nothing new: `expect.choices` is already a map keyed by
path, and `set`/`values` already carry `members[i1].name`. The key becomes a
path in the same spelling.

**This is a public API change in both engines**, and it is the part of this
feature with the largest reach. It is worth saying plainly that the proposal
did not name it: §4 of that document said clients "change by nothing", which is
true of the *rendering* and false of the call that fetches the list.

---

## 5. Finding 3 — HL20 needs an option that is not a row, and that is not built now

`90` ("No one", for a child 15–17) is an option in HL20's answer space that
corresponds to no row of the roster. So does `00` where an adaptation uses it
(the Punjab manual's *"if HL14 is blank or '00'"*).

A `rows` list cannot express it: every option it produces is an instance.

**Not built, and the reason is not cost.** It is that the sentinel is
expressible today and self-exclusion is expressible by nothing at all. HL20 is
authored as two questions and a calculate:

```
hl20_has_caretaker   select_one yes/no
                     relevant: age 15–17 and hl14_mother is null
hl20_caretaker       select_one, choices.kind rows over members, excludeSelf
                     relevant: hl14_mother is null and
                               (age < 15 or hl20_has_caretaker = 'yes')
hl20                 calculate
                     if(hl20_has_caretaker = 'no', '90',
                        coalesce(hl14_mother, hl20_caretaker))
```

One extra question the paper does not have, and one column that comes out the
same shape the paper's does. That is a real cost and it is a smaller one than
adding literal options to a list of rows before anybody has fielded the first
one.

**What it would look like when it is worth it**, recorded so the next person
does not re-derive it: an `extra` array of inline items appended to the
resolved list, membership being the union, and — the part that needs care — a
compile-time refusal of an `extra` value that could collide with an instance
id. Ids are minted `i<n>` but `restore()` deliberately adopts ids from another
minter, so the refusal cannot be a pattern match on the minted shape alone and
needs its own thinking. That is the whole reason it is not a five-line addition
to this change.

---

## 6. The decision on §8: `excludeSelf`, not a §4.2 grant

```json
"choices": {
  "kind": "rows",
  "repeat": "members",
  "excludeSelf": true,
  "filter": <expr>
}
```

**What it means.** The candidate list omits the instance the field is being
answered in. It is a §10.2 semantic error on a field that is not inside
`repeat` — there is no "self" to exclude, and a flag that silently did nothing
would be a control that "does nothing", which this repository has a rule about.

**Why not the grant.** The alternative was `$row._instance` and `[.]._instance`
as §4.2 rows, and the argument against it is four things, in descending order
of how much they matter.

1. **An author can get the expression subtly wrong, and cannot get the flag
   wrong at all.** Inside a choice filter, `$row` is the candidate and every
   other reference resolves from the answering scope. `$row._instance !=
   [.]._instance` is therefore correct and `$row._instance != _instance` is
   also correct and `$row.name != name` *looks* correct, is what somebody will
   write, and is wrong for the two members of a household who share a name. The
   failure is a list with one wrong option in it — which nothing renders
   differently, nothing errors on, and an enumerator has no way to notice.
   Break 56's shape again: right-looking output, wrong because of an edge
   nobody asserted.

2. **A grant cannot be taken back; a flag can be joined later.** Forms are
   versioned and fielded (§9), so every reference form the spec grants is one
   the engines must resolve for as long as those forms exist. `excludeSelf`
   adds no expression surface, so granting `_instance` afterwards — if a real
   case demands it — costs exactly what it costs today. The ordering is
   asymmetric and only one direction is reversible.

3. **The audience.** The builder audit was run as `pm`, the programme-manager
   role, and half two of `docs/is-the-builder-usable.md` is about whether
   somebody who is not us can author with it. "Don't offer this person as their
   own mother" is a checkbox. `members[.]._instance` is a machine identity in a
   reference picker that currently shows question labels, and it means nothing
   to the person the builder is for.

4. **The evidence demands one predicate, not a facility.** The three questions
   need "the candidate is not the answering instance" and nothing else.
   Notably, the other identity-shaped check a household listing wants —
   *the father must not be the same person as the mother* — **needs no grant at
   all**: `${hl14_mother} != ${hl18_father}` compares two stored answers, and a
   stored answer is an ordinary value whatever it identifies. That is worth
   knowing before granting anything: half of the identity comparisons anybody
   would ask for already work.

**What §2.3's earlier refusal is worth here.** §2.3 declined to make `_rowKey`
referenceable, and it gave a reason with a shelf life — *"what a row displays
is still open"* — which `summaryLabel` and PR #64's editor have since closed.
So that precedent does not decide this one, and it would be dishonest to lean
on it. What does carry over is the part of §2.3's reasoning that was never
conditional: `_rowKey` has a workaround, because `bind` puts it in a question
where every §4.2 rule already reaches it. **An instance id has no such
workaround** — it is minted at runtime and cannot be bound — which is exactly
why the flag has to exist in *some* form rather than being left to authors.

**What we give up.** Any filter predicate about identity other than self:
"not my sibling", "not the head of household's spouse". None appears in HL,
none in RCons's 73 questions (`docs/rcons-current-system.md` §5), and the first
one that does gets to make the case for the grant with a real form behind it.

---

## 7. What this adds to the build

Against `docs/proposal-row-choice-question.md` §4's "what changes where":

| | |
|---|---|
| §3 | `excludeSelf` on the `rows` kind, with the per-instance sentence — *the resolved list depends on the instance the field is answered in* |
| §10.2 | `excludeSelf` on a field not inside `repeat` is a semantic error |
| Both engines | `choices()` accepts an instance-qualified path; the rows resolver omits the answering instance |
| Vectors | `repeat-016` unchanged (a form-level question, the dependency edge); **`repeat-017` is new** — the HL14 shape: the question inside the repeat it draws from, a different list per instance, and the answer surviving a delete of somebody else |
| The builder | the repeat picker gains the checkbox |

`repeat-017` is the vector this decision exists for, and it is the one that
catches finding 2: an engine that resolved one list per field passes every
other vector in the set and fails this one on Fatima's row.
