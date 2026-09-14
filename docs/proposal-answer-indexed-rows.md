# Proposal: an answer-indexed reference into a roster

**Date:** 14 September 2026
**Status:** proposal. Nothing implemented, nothing scheduled.
**Closes:** `docs/known-defects.md` 32, if accepted.
**Found by:** building MICS6's HL module in the builder
(`docs/builder-audit-2026-09-13.md` §3). HL14 records the line number of a
member's natural mother, HL18 the father's, HL20 copies HL14 — all three point
at another row of the same roster, and `${members[${hl14_mother_line}].sex}` is
`unexpected character ']'`.

---

## 0. The question up front: what passes every test?

**It is 3, and it is not a prediction — it is already shipped.**

`Runtime.kt` `summaryLabel`, the fallback when a roster row has no summary
label:

```kotlin
return (position + 1).toString()
```

**The handset prints rows as 1, 2, 3.** §4.2 addresses them as
`members[0]`, `members[1]`, `members[2]`. MICS6 calls HL1 a *line number* and
numbers it from 1.

So an author looks at the roster, sees the mother on line 2, writes
`members[${line}]` where `line` is 2, and reads **the third person**. The form
compiles, the expression evaluates, every test passes, and the answer is wrong
by one row in a way nothing on any screen can show.

Everything else in this proposal is ordinary engineering. §3 is the part that
decides whether this feature is worth having.

---

## 1. Syntax and the AST node

### The surface form stays as the author wrote it

`${members[${hl14_mother_line}].hl3_relationship}` is what somebody typed with
no documentation in front of them, and the parse error already points at the
exact character. Keep it.

### The AST is a `ref` with arguments, not a new op

§4.2 has four path forms and none takes an expression. The proposal adds a
fifth:

| Path form | Meaning |
|---|---|
| `members[?].name` | Field `name` in the instance at the position given by the node's **first argument** |

```json
{
  "op": "ref",
  "path": "members[?].hl3_relationship",
  "args": [ { "op": "ref", "path": "hl14_mother_line" } ]
}
```

`?` cannot collide with anything: §2.4 identifiers are letters, digits and
underscores, and `[.]`, `[]` and `[0]` are the existing three.

**Why reuse `ref` rather than add an op — and this is the finding that decided
it.** `collect_refs` walks `expr.get("args", [])` on *every* node
unconditionally, after its `ref` branch has stripped `members[?].` down to the
target field. So the node above yields **both** edges with the collector
**unchanged**:

```
(i) ref + args  ->  ['hl14_mother_line', 'hl3_relationship']
(i) compound    ->  ['hl3_relationship', 'line']       # index = line - 1
```

A new op does not:

```
A (index inside the path string)  ->  ['hl3_relationship']       # index invisible
B (new op, path split into fields) ->  ['hl14_mother_line']      # target invisible
```

Both of those are break 56's shape — an edge missing from the graph while every
rendered value looks right. The `ref`-with-args shape is the only one of the
three that is correct in the collector we already have, which is a reason to
prefer it beyond taste.

### What still has to change

Five places, none of them large:

| | |
|---|---|
| `expression.py` / `Expression.kt` | `_resolve` takes the path only; it needs the node, or the resolved index passed in. This is the one real refactor — the resolver signature |
| The code parser | `${a[${b}].c}` → the node above |
| `expression_text.py` | render the node back to that text, so the round trip in `ExpressionEditor` holds |
| `shapes.ts` | the visual editor cannot express it; it must fall to the Code tab with the existing `BEYOND_VISUAL` note, not silently drop it |
| §4.2 | the fifth row, and §3's sentence |

---

## 2. Null and out of range

There are **four** ways this reads null, and all four are already decided by
rules that exist:

| | Why null |
|---|---|
| The index is unanswered | §4.4.1 — an unanswered question is null |
| The index is not an integer | §4.7 — an argument not of its declared type is null, never an error |
| The index is out of range | §4.2's existing exception — a positional read of an instance that does not exist is null, because instance count is runtime state |
| The instance exists and the field is unanswered | §4.4.1 again |

So the rule is one sentence and it is not new: **an answer-indexed read is a
positional read whose position is computed, and every way of failing to find a
value is null.**

§4.4.7 then decides what that means where it matters:

- `relevant`: null → **true**. A question whose condition reads a row that
  is not there is **shown**.
- `constraint`: null → **true**. It **passes**.

That is the right direction and it is worth naming out loud: a broken
cross-row reference is permissive, never destructive. It will not hide a
question or block finalisation.

**It is also why §3 is dangerous.** The same rule that makes a missing row safe
makes a *wrong* row silent: reading the person above the one you meant produces
a perfectly good value, and nothing anywhere is null.

---

## 3. One-based or zero-based — the decision

### Recommendation: zero-based, consistent with `members[0]`, and the mismatch is mitigated in the builder rather than in the IR

The alternatives, and why they lose:

**1-based for `[?]` only.** Then `members[0]` and `members[?]` with index 0
address different rows. Two bases in one addressing scheme is a worse defect
than the one it fixes, and it is permanent.

**Convert silently** — treat the index as 1-based and subtract. Then an author
who *did* write 0-based, or who wrote `count() - 1`, is silently wrong instead.
The population of authors is not all of one kind, and guessing which is a coin
flip performed on their data.

**Refuse the ambiguous case.** There is nothing statically detectable. `${line}`
where `line` is an integer question is exactly as plausible 0-based as 1-based.

So: **`members[?]` is 0-based, one rule, stated in §4.2 in the same sentence as
`members[0]`.**

### What is done about it instead

Not a warning — there is nothing to warn on. Three things, in the order they
help:

1. **The builder's index field is labelled with its base and offers the
   conversion.** "Row number, counting from **0**" with a one-click *"my number
   counts from 1"* that writes `sub(${line}, 1)` into the AST. Explicit,
   visible in the expression afterwards, no magic, and it is the moment the
   author is thinking about it.
2. **§4.2's new row says it beside the literal form**, so the two are read
   together.
3. **A §10.3 warning for the one detectable symptom.** A 1-based author's *last*
   row always reads out of range. That is not statically detectable either, but
   it is detectable in **test mode**: a saved test case that walks the roster
   and gets null on the final row is the signature. Worth wiring into the test
   pane rather than the compiler.

### The residual risk, stated rather than buried

None of that eliminates it. An author who ignores the label reads the wrong
person and no gate anywhere can tell. **This is the cost of the feature and it
should be weighed before accepting it**, because §4 below is why it cannot be
detected: a wrong-row read is a correct evaluation of a correct expression.

### And a second silent failure that no choice of base fixes

**Positions are not stable.** Delete row 2 of a five-row roster and rows 3, 4, 5
renumber. Every already-answered "mother's line number" in that household now
points at a different person — silently, retroactively, and after the answers
were given.

Paper does not have this problem because paper does not delete rows. The app
does: §2.3 gives an enumerator-driven roster `allowDelete`, and the scale run
walked it.

So positional addressing is the wrong key for this feature *even when the base
is right*. The correct key is the row's identity, which the IR already has two
of — the internal instance id, and `_rowKey` for a sampled row (§2.3, and §2.3
already notes `_rowKey` "is not yet an expression reference"). The feature that
uses it is **a question whose choices are the rows of a repeat**: the enumerator
picks "Fatima, 34" from a list, the IR stores an identity, and nothing
renumbers.

That is a larger feature and it is not what was asked for. It is named here
because it dissolves both silent failures at once, and because accepting this
proposal as written means accepting them both.

---

## 4. The dependency graph

### What the edge has to be

A relevance reading `members[?].y` with index `x` depends on **`x` and on
`y`** — on `y` as a field, meaning every instance of it, because changing `x`
changes which instance is read and the reader must be ordered after all of
them.

### It already works, and that was verified before writing this

`collect_refs` unchanged, on the proposed node:

```
['hl14_mother_line', 'hl3_relationship']
```

Both edges. Kotlin's `collectRefs` walks args the same way.

### Why ordering is what this buys, not re-triggering

`recalculate()` is a **full pass in topological order** (§5.2) on both engines,
not a dirty-set walk. A missing edge therefore does not leave a permanently
stale value — it computes the reader *before* its input in the same pass, so
the reader sees the previous pass's value and corrects on the next one. That is
a one-pass lag, not a permanent error, and it is exactly the class of bug that
survives casual testing.

Break 56 is the precedent and its lesson is the same: the edge was load-bearing
three ways and **the render was not one of them**. Here the edge is load-bearing
for ordering, for `check_sensitivity_propagation` (an index reading a sensitive
field is a leak), and for `_check_references` turning an unresolvable index into
a compile error.

### The vector that fails if it is not

Modelled on `label-005`, which asserts `dependsOn` directly and is the only
reason break 56 was catchable:

```json
{
  "id": "repeat-016",
  "description": "An answer-indexed row read depends on the index AND on the field, because changing the index changes which instance is read",
  "form": { "…": "a roster of three, each with `name`; a question whose relevant reads members[?].name indexed by `pick`" },
  "steps": [
    { "set": { "pick": 0 }, "expect": { "values": { "seen": "…first…" } } },
    { "set": { "pick": 2 },
      "expect": {
        "values": { "seen": "…third…" },
        "dependsOn": { "seen": ["name", "pick"] }
      } },
    { "set": { "pick": 9 }, "expect": { "values": { "seen": null },
      "relevant": { "seen": true } } }
  ]
}
```

Three things, and each fails independently:

- **step 2's `values`** fails if the read does not follow the index;
- **step 2's `dependsOn`** fails if either edge is missing — this is the break-56
  assertion and the one that would otherwise pass while everything looked right;
- **step 3** fails if out-of-range is an error rather than null, and its
  `relevant: true` fails if §4.4.7's boundary rule is not applied.

A fixture note, from `docs/project-conventions.md`'s "A sequential fixture
cannot see an ordering bug": the three rows must have names whose alphabetical
order differs from their creation order, and the interesting row must be the
**middle** one, or an implementation that reads the first or the last passes.

---

## 5. Cost

Measured, because break 226's lesson is that nobody measures this and the
vectors cannot.

**Baseline**, the Sindh-scale form — 2,128 questions, 2 repeats, the
enumerator-driven roster grown to 30 rows, full `recalculate()`:

```
recalculate: first 4.6 ms, then 4.4–8.5 ms
~2,489 field paths evaluated per pass for that roster alone
```

**Marginal cost of the feature**, 200,000 iterations each:

```
positional read              0.45 µs
read + index evaluation      0.69 µs
delta                        0.24 µs
```

An answer-indexed read is a positional read plus one expression evaluation:
**O(1), not O(rows)**, because the instance list is already an ordered list and
the index is a subscript.

Thirty such reads — one per row of the roster — cost **7.2 µs against a 4.4 ms
pass: 0.16%.** Per keystroke, on the largest form this platform has ever been
shown.

**Cost is not the constraint on this feature.** Saying so is the point of
measuring, and it is worth being explicit that the risk lies entirely in §3.

Two contracts worth writing into §4.2 anyway, in §3.2's style, because they are
met by shape rather than by optimisation and an implementation could lose them:

> Resolving `members[?]` is **O(1) in the number of instances** — a subscript
> into the ordered instance list, never a scan for a match.
>
> The index is evaluated **once per read**, not once per instance.

---

## 6. What I recommend

1. **Take the AST shape in §1.** It is the only one of three that is already
   correct in `collect_refs`, and that is not a coincidence — it is what
   reusing an existing node buys.
2. **Take §2 unchanged.** Four null paths, one existing rule each, permissive at
   the boundary.
3. **Do not take §3 without deciding about §3's last part first.** Zero-based is
   the right choice *within* positional addressing, and positional addressing
   has a second silent failure that outlives the choice. If a row can be
   deleted, an already-answered line number can come to mean a different
   person. I would want that decided before implementing, because the
   identity-keyed alternative makes this proposal unnecessary rather than
   smaller.
4. **Write `repeat-016` before the implementation, not after.** Its `dependsOn`
   assertion is the only part of this that a working feature can fail silently.
5. Cost needs no work.

**The honest summary:** the mechanism is small, well-supported by what already
exists, and cheap. The feature it delivers is a reference that can quietly point
at the wrong person in two independent ways, and only one of them is fixable by
a decision in this document.
