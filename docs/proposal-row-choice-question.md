# Proposal: a question whose choices are the rows of a repeat

**Date:** 14 September 2026
**Status:** **accepted and built, 14 September 2026** — Form IR §3.3, both
engines, `repeat-016`/`repeat-017`, the builder and the collection screen (#66).
Kept as written, because what it argued is the reason the thing has the shape it
has. Two things it did not have, both found by checking §8 against the paper:
the list is **per instance**, and `excludeSelf` is a flag rather than the §4.2
grant §8 was weighing — `docs/decision-rows-self-exclusion.md` decides both.
**Replaces:** `docs/proposal-answer-indexed-rows.md`, whose §3 is the argument
for this one — positional addressing is the wrong key regardless of base,
because deleting a row renumbers every row below it and an answer that was
correct becomes wrong retroactively with nothing to see.
**Closed:** `docs/known-defects.md` 32.

---

## 0. The short version

**A third `choices.kind`.** `select_one` with
`{"kind": "rows", "repeat": "members"}` offers the rows of that roster, stores
the **instance id**, and labels each option with the row's `summaryLabel`.

Almost none of it is new. The instance id is already the stable identity, and
`restore()` exists specifically so a server adopts it rather than minting its
own. `summaryLabel` already has a three-step fallback chain that already handles
the row nobody has named yet. `choices()` already returns one `{value, label}`
shape that a client renders without knowing which kind produced it. The export
already keys repeat rows on `instance_id` and already says in its manifest that
position is "for sorting, never for joining".

The feature is mostly wiring things that were built for this and have never been
connected.

---

## 1. What the stored value is

### The instance id, and it is already the identity the system uses

`FormInstance.restore()` is the evidence, and its docstring was written for
exactly this failure:

> An instance id is minted once, on the device, and every operation about that
> instance names it for the life of the submission (§2.3, §5.4) — so a server
> rebuilding the form to read a submission back has to take the ids it is given.
> **Minting fresh ones would renumber a household's members every time anything
> reads them** … a key that means a different person before and after a delete.
>
> Positions are deliberately not an input. `instances[repeat]` is an ordered
> list of **stable ids**, and the order is the order to display and export them
> in — never an addressing scheme.

### Stable across a sync and a fold — yes, and here is the chain

| | |
|---|---|
| Minted | On the device, once, `i1`, `i2`, … monotonic per submission |
| Carried | In the op `path`: `set` on `members[i3].name`, `repeat_add` on `members[i3]` |
| Folded | `fold.py` `note_instance(op.path)` / `forget(op.path)` — the fold reads ids out of paths and never renumbers |
| Rehydrated | `restore(instances=…, answers=…)` **adopts** the ids the fold produced |
| Exported | `REPEAT_KEY_COLUMNS` is `(submission_id, instance_id, instance_index)`, and the manifest says join on the first two |

So an answer holding `i3` means the same member on the device, on the server,
after a delete, after a reopen, and in a `.dta` a year later.

### `_rowKey` is not the key, and belongs beside it

`_rowKey` is the sample row's own identity and is **null for an
enumerator-added instance** (§2.3), so it cannot be the stored value — a
household's newborn has no sample row. It is still the more useful key for
anyone joining back to the sample, so:

> The export's repeat file already carries `instance_id`. A question of this
> kind exports its raw value (the id) **and** a `…_label` column of the row's
> summary label, exactly as a dataset-backed select already exports code and
> label. `_rowKey` needs no new column: it belongs to the roster's own row, not
> to the question that points at it.

---

## 2. What the enumerator sees when choosing

### `summaryLabel`, and the case we left open is already closed

§2.3 specifies the chain a runtime takes, in order:

1. `summaryLabel` rendered in the instance's scope — **unless it has at least
   one argument and every argument is null**, in which case it produces nothing
   and the next rule applies;
2. the source row's label, for an instance from a `rowSource`;
3. the instance's **1-based position in the current order**.

So the question the user and I left open when `summaryLabel` was specified —
*what does a row show before the name is entered* — was answered then and the
answer serves this feature unchanged. A member added ten seconds ago shows
`4`; the moment a name is typed the same row shows `Fatima`, on the same
recalculation as everything else, because §2.3 says the label is derived and
follows the answers.

**The option list therefore reads exactly like the roster the enumerator was
just looking at**, because it is produced by the same function —
`summaryLabel(repeat, instance, language)`, already implemented in both engines.

Two consequences worth stating:

- **A form with no `summaryLabel` offers a list of bare numbers.** That is
  usable but poor, and it is now an authoring choice rather than a limitation,
  because `summaryLabelArgs` has an editor as of PR #64. A §10.3 warning — *"a
  `rows` choice over a repeat with no `summaryLabel` will offer position
  numbers"* — is cheap and is the right nudge.
- **The label is not the stored value.** Two members called Fatima are two
  options reading `Fatima` and two different ids. That is correct and it is also
  a usability problem for the enumerator; it is the author's to solve by putting
  age or relationship in the summary label, which is what MICS instruments do on
  paper.

---

## 3. Whether the list is live — yes, and a dangling answer is loud

**The list is live.** It is resolved from `instances[repeat]` at the moment it
is asked for, exactly as a dataset list is resolved from its rows. A member
added after the question was answered appears; a member deleted disappears.

**An answer pointing at a row that is gone is a §6.3 membership error.** No new
machinery: `_values_outside_choices` already produces one `choice` error on the
field when a value is not in the list, and §6.2 makes that block finalisation.

That is the decision, and it is the opposite of the positional design's
behaviour, which is the whole point:

| | Positional | Identity |
|---|---|---|
| Delete a row above the target | every answer below silently means a different person | the answer still means the same person |
| Delete the target itself | the answer silently means whoever slid into that position | **a `choice` error naming the field, and the form will not finalise** |

The enumerator is told *"the person this refers to is no longer on the list"*
and must re-answer. Loud, at the moment the delete happens, on the device.

**Reading a field through the reference is null if the row is gone** (§4.4) —
but see §5: reading through is not part of this proposal.

---

## 4. One question type, or a `choices.kind`? — a kind

### A third kind, and the existing code says so

`FormInstance.choices(field_id)`:

> Each entry is `{"value": ..., "label": {lang: ...}}`, so a client renders both
> kinds the same way and **cannot end up implementing one of them itself**.

A third kind therefore costs the clients **nothing**. `select_one` with a rows
list renders in the widget that already exists, and `select_multiple` gets
"which members were present?" for free — a genuinely common question that no
new question type would have given us without asking for it twice.

A new `dataType` would instead need: a registry entry, a
`CollectableTypesTest` branch, a `CollectionScreen` `when` arm, an importer
mapping, a palette entry — and would still be a select underneath.

### The shape

```json
"choices": {
  "kind": "rows",
  "repeat": "members",
  "filter": <expr>
}
```

No `valueColumn` or `labelColumn`: the value is the instance id and the label is
§2.3's chain. That asymmetry with `kind: "dataset"` is deliberate — a dataset
row has columns an author chooses between, and an instance has an identity and a
summary label, both already defined.

### What changes where

| | |
|---|---|
| §3 | the third kind, and §3.2's performance contract restated for it |
| `compile_choices` / both engines | resolve `instances[repeat]` to `{value: id, label: summaryLabel(…)}` |
| `collectable-types-v0.1.json` | `choiceSources` gains `rows` — the axis exists precisely so a client's ability to present a *source* is separate from its ability to present a *type* |
| The importer | **nothing.** XLSForm has no spelling for this; it is a builder-authored shape, and the report should say so rather than guess |
| The builder | a `repeat` picker where the dataset kind has a key picker |
| `check_sensitivity_propagation` | a filter reading a sensitive field is a leak, by the path that already exists |

### The dependency edge, which is the part that can fail silently

A choice list's selector expressions are already collected into `depends_on` —
*"changing the district must re-resolve the village list and re-check the
village already chosen"*. A rows list needs the same, plus one thing the dataset
case does not have: **the labels are made of answers.** So the field depends on
every field the repeat's `summaryLabelArgs` reads, and on the filter's
non-`$row` references.

Without that edge the list is right and the *labels in it* are stale — a member
renamed after the list was drawn still reads by the old name. That is break 56's
shape for the third time, and §6 is the vector.

---

## 5. What this deliberately does not give you

**Reading a field of the chosen row.** `${members[@mother].sex}` — id-keyed
rather than position-keyed — is a separate §4.2 addition and is *strictly safer*
than the positional one, because ids do not renumber.

It is not proposed now because **MICS6 does not need it**. HL14 and HL18 record
a line number; HL20 copies HL14's value. All three are satisfied by storing an
identity. Nothing in the module computes from the referenced person's answers.

Proposing it anyway would be building the harder half for a use case nobody has
produced. When one appears, the shape is the `ref`-with-args node from the
previous proposal with `@` instead of `?`, and §1 and §2 of that document carry
over unchanged — including the finding that `collect_refs` already handles it.

**Nested repeats**, which IR v0.1 does not have, so "rows of which instance of
the outer repeat" is not a question yet.

---

## 6. `repeat-016`, which is written either way

The `dependsOn` assertion is the only part of this a working feature can fail
silently, so the vector is written before the implementation.

```json
{
  "id": "repeat-016",
  "description": "A rows-choice field depends on the fields its option labels are made of, so renaming a member relabels the option that points at them",
  "form": {
    "…": "repeat `members` with `name` and summaryLabel {0} over it; a select_one `mother` with choices.kind rows over members"
  },
  "steps": [
    { "addRow": "members", "set": { "members[i1].name": "Zubaida" } },
    { "addRow": "members", "set": { "members[i2].name": "Bilal" } },
    { "addRow": "members", "set": { "members[i3].name": "Amina" } },
    { "set": { "mother": "i2" },
      "expect": { "choices": { "mother": [
        { "value": "i1", "label": { "en": "Zubaida" } },
        { "value": "i2", "label": { "en": "Bilal" } },
        { "value": "i3", "label": { "en": "Amina" } } ] } } },

    { "set": { "members[i2].name": "Bilquis" },
      "expect": {
        "choices": { "mother": [ "…", { "value": "i2", "label": { "en": "Bilquis" } }, "…" ] },
        "dependsOn": { "mother": ["name"] },
        "values": { "mother": "i2" }
      } },

    { "deleteRow": "members[i1]",
      "expect": {
        "values": { "mother": "i2" },
        "errors": { "mother": [] }
      } },

    { "deleteRow": "members[i2]",
      "expect": { "errors": { "mother": [ { "kind": "choice" } ] } } }
  ]
}
```

Five assertions, each failing independently:

- **step 4's `dependsOn`** — the break-56 assertion. Fails if the label's inputs
  are not edges, while every list *looks* right on a fresh render.
- **step 4's `choices`** — fails if the list is cached rather than live.
- **step 4's `values`** — fails if a relabel disturbs the stored id.
- **step 5** — *deleting somebody else must not touch the answer.* This is the
  assertion the positional design cannot pass, and it is why this document
  exists.
- **step 6** — deleting the referent is a `choice` error, not silence.

**The fixture is deliberately not sequential** (`docs/project-conventions.md`,
"A sequential fixture cannot see an ordering bug"): three members whose
alphabetical order — Amina, Bilal, Zubaida — differs from creation order, the
interesting one in the **middle**, and the deleted one at the **front** so a
shift would be visible in the answer.

---

## 7. Cost

Not measured, because there is nothing new to measure: resolving the list is one
pass over `instances[repeat]` calling `summaryLabel` per row — the same work the
roster screen already does every recalculation, for the same rows.

Two contracts to write into §3, in §3.2's style, because they are met by shape
and an implementation could lose them:

> Resolving a `rows` list is **O(rows)** and never O(answers): one pass over the
> instance list.
>
> Membership is a **lookup by id**, not a scan of rendered labels.

The roster this was found on has 30 rows. §3.2's dataset contract exists because
a village list has 37,852; nothing here approaches that, and saying so is more
useful than a benchmark of a list with tens of entries.

---

## 8. The one thing I have not decided

**Whether a member can be offered as their own mother, and how to exclude
them.** MICS6 cannot; the roster row for Fatima should not offer Fatima.

`filter` is the mechanism, with `$row` bound to the candidate **instance** — and
that needs a way to say *"the candidate is not the instance I am answering
in"*, which means comparing two identities, which means an expression can see an
instance id. Nothing in §4.2 grants that today, and §2.3 already declined to
grant it for `_rowKey` on the grounds that what a row displays was still open.

Three options, none costed yet: grant `$row._instance` and `[.]._instance` as
§4.2 rows; give the `rows` kind a boolean `excludeSelf`; or leave it and let an
author filter on an answer instead (`$row.name != ${name}`, which is wrong for
two people with one name).

I would rather bring that back as its own small decision than fold a new §4.2
grant into this proposal quietly. **Everything else here I would implement as
written.**
