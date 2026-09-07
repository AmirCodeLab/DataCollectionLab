# Reachability and Liveness Vectors

Language-neutral fixtures for the publish-time check in Form IR §10.2 and
§10.3: **a form must not ship questions it can never ask.** Two findings:

- a question that is not a `calculate` and sits on no screen of §11.1's
  partition (defect 14's shape);
- a container that provably never appears — a `relevant` that is statically
  false, or a repeat that can never hold an instance — holding at least one
  answerable question.

Both implementations must produce the same violations, the same warnings and
the same "never shown" list, in the same order:

- Python: `check_reachability`, `never_shown_questions` in
  `backend/app/modules/form_engine/reachability.py`; the warning in
  `runtime.py` `_lint`; runner `backend/tests/test_reachability_conformance.py`
- Kotlin: the same names in `shared/form-engine` (`Reachability.kt`); the
  warning in `Runtime.kt` `lint()`; runner
  `shared/form-engine/src/jvmTest/kotlin/com/dcp/form/ReachabilityConformanceTest.kt`

## The six shapes, and where they came from

These are **not cases invented for the occasion.** They are the six shapes
`docs/phase3-item0-builder-scope.md` §0.2 probed against the Python reference
on 6 September 2026 — every one compiled, published clean and asked nobody
anything — reproduced by `scripts/probe_publishable_empty_containers.py` and
lifted from it verbatim, in the same order. Each vector's `shape` is the
probe's own label, and `test_the_six_shapes_are_the_probe_s_own` fails if the
two drift apart. Two of the six are shapes an XLSForm author essentially
cannot write and a builder author writes by accident on the first afternoon.

| | shape | outcome |
|---|---|---|
| 001 | empty inline roster, no add | refused |
| 002 | `countExpr = 0` | refused |
| 003 | statically false `relevant` on a group | refused |
| 004 | statically false `relevant` on a question | **warning** — staging is real work (§10.3) |
| 005 | empty field-list group | **clean** — nothing inside, nothing lost |
| 006 | `maxInstances: 0`, enumerator repeat | refused |

## Three expectations per vector

- `expectedViolations` — the publish gate's refusals, exact text, document
  order. Message text is part of the contract because an author reads it.
- `expectedWarnings` — the compile warnings, exact text. This is the first
  suite to assert a warning at all (known defect 17): until it existed a
  specified warning that neither engine emitted was indistinguishable from a
  clean form.
- `expectedNeverShown` — every answerable question the document itself says
  is never shown, structured, so a builder's badge reads ids rather than
  parsing prose. On a refused form this is what the badge *would* say; on a
  compiled one it is what `POST /forms/compile` returns as `neverShown`.

## Written, not generated

As for `sensitivity/`: there are no bytes to reproduce here, only a rule, and
blessing one implementation's output would make the vectors agree with
whatever it currently does. Both sides are checked against the rule as stated.
