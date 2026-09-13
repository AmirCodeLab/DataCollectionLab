# Answerability Vectors

Language-neutral fixtures for one publish-time refusal in Form IR §10.2: **a
form must not ship a question it shows and nobody can answer.**

The sibling of `conformance/reachability`, and the distinction is the point.
Reachability asks whether a question reaches a **screen**. This asks whether a
question that reached one can be **answered**. A form can pass the first and
fail the second, and one did.

One finding today: **a `note` carrying `required`.** §2.1 gives a note no value
and nothing can give it one, so `required` on one is permanently blocking under
§6.2 — the submission can never be finalised, and `firstBlockingScreen` sends
the enumerator to a screen holding a sentence and nothing to answer.

Both implementations must produce the same violations, in the same order:

- Python: `check_answerability` in
  `backend/app/modules/form_engine/answerability.py`; runner
  `backend/tests/test_answerability_conformance.py`
- Kotlin: `checkAnswerability` in `shared/form-engine/.../Answerability.kt`;
  runner `shared/form-engine/src/jvmTest/kotlin/com/dcp/form/AnswerabilityConformanceTest.kt`

## Where it came from

Not a case invented for the occasion. On 12 September 2026 a questionnaire the
size of RCons's Sindh listing was walked on a handset, and its one `note`
rendered with a required marker (`docs/scale-run-2026-09-12-sindh.md` §6.6). The
generator marked 70% of its questions required and did not exempt the one type
that stores no value — **which is precisely how an author writes it**. It
imported with no diagnostic, published with no refusal, deployed to two
environments and reached a phone. `docs/known-defects.md` 31.

## The five shapes

| | shape | outcome |
|---|---|---|
| 001 | `required: true` on a note | refused |
| 002 | a note with no `required` | clean — the ordinary case |
| 003 | a **statically false** `required` on a note | refused |
| 004 | one inside a repeat and one after it | refused, both, in document order |
| 005 | `constraint` and `readOnly` on a note | clean |

**003 and 005 are the two that make this a rule rather than a patch**, and they
pull in opposite directions.

003 says the refusal is of `required` **present at all**, not of `required`
evaluating true. A statically-false one is merely pointless; refusing only the
true ones would leave an author one edit away from a form that cannot be
finished, and would make the check depend on an expression's value at publish
time, which §10.3 says a static check must not do.

005 says the rule stops there. A `constraint` over null coerces true (§4.4.7)
and a `readOnly` over null coerces false, so both are inert on a note: equally
meaningless, and neither changes what the form does. A rule that refused them
too would be tidiness rather than a defect being prevented, and a form author
would meet a refusal with no failure behind it.

## Two expectations, not three

`expectedViolations` only — the publish gate's refusals, exact text, document
order. Message text is part of the contract because an author reads it.

There is no `expectedWarnings` or `expectedNeverShown` here as there is in
`reachability/`: this rule emits no warning, and a required note is not "never
shown" — it is shown, which is the whole difficulty. A vector format that
carried fields no vector in the set uses would be paperwork.

## Written, not generated

As for `sensitivity/` and `reachability/`: there are no bytes to reproduce here,
only a rule, and blessing one implementation's output would make the vectors
agree with whatever it currently does. Both sides are checked against the rule
as §10.2 states it.

## What this set is not, and the §10.2 refusals still without one

`docs/project-conventions.md` names the gap: most of §10.2 is held by a matched
pair of tests, one per engine, and nothing else — the nested-repeat refusal, the
repeat-inside-a-field-list refusal, and the four `rowSource` refusals. Those
belong in a set like this one and are not in it yet. This set exists for one
rule because that rule arrived with a defect behind it; it is the right home for
the others when somebody moves them.
