"""The export projection: relevant answers only, keyed by stable instance id.

Form IR §5.3 says two things about a non-relevant field and they exist for
different reasons:

  - it **retains** its value, so an enumerator correcting an earlier answer does
    not destroy what they typed;
  - it is **excluded from export**, so an analysis does not contain answers to
    questions nobody was asked.

`FormInstance` holds both halves. `values` is the retained one and `answers()`
is the exported one, and reaching for the wrong one produces a file in which
every count is right, every type is right, and a household that said "no
children" reports the three it had typed before changing its mind. Nothing
about that file looks wrong.

So this module is the **only door**. `project_for_export` builds a
`FormInstance`, reads `answers()`, and returns a frozen value object; the
instance is local and never escapes, so nothing downstream has a `values` to
reach for. `backend/tests/test_export_reads_only_answers.py` is the lint that
keeps it that way — the same move as `compiledFormForSubmission` taking no
version and `dataset_rows_for` taking none either: remove the choice rather
than test for it having been made correctly.

The second thing it is careful about is **instance identity**. A row here is
keyed by the stable instance id the device minted (§2.3, §5.4), never by
position. Positional addressing resolves against the *current* ordered list and
deleting an instance does not renumber storage, so `members[1]` means a
different person before and after a delete: an export keyed on position
disagrees with yesterday's export about who is who, and a join between the two
is silently wrong.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from .datasets import DatasetSource
from .expression import collect_refs
from .runtime import CompiledForm, FormInstance


def field_of(path: str) -> str:
    """The field id a value path names. `members[i3].age` -> `age`."""
    return path.split("].", 1)[1] if "]." in path else path


@dataclass(frozen=True)
class RepeatRow:
    """One instance of one repeat.

    `instance_id` is the id storage recorded, and it is the only key an export
    may use. `index` is where the instance currently sits in the ordered list —
    useful to sort by and never to join on.
    """

    repeat_id: str
    instance_id: str
    index: int
    #: field id -> value. Called `cells` rather than `values` on purpose: there
    #: is no attribute named `values` anywhere on the export path.
    cells: Mapping[str, Any]


@dataclass(frozen=True)
class ExportProjection:
    """What one submission contributes to an export, and what it cannot."""

    #: field id -> value, for fields outside every repeat. Relevant only.
    top: Mapping[str, Any]
    #: repeat id -> its instances, in storage order.
    repeats: Mapping[str, Sequence[RepeatRow]]
    #: Value paths the server cannot read, either because the op carrying them
    #: was ciphertext or because they are computed from one that was. These
    #: export as the `ENCRYPTED` token, never as a blank.
    unreadable: frozenset[str]
    #: Value paths that are here, or absent, on the strength of a relevance
    #: expression that read something unreadable. The engine coerces null to
    #: true at that boundary (§4.4), so the safe direction is taken and the
    #: column is included — but "included" is then a guess, and the manifest
    #: says so rather than the file implying certainty it does not have.
    relevance_uncertain: frozenset[str]
    #: Paths in storage this form version has no field for. Named rather than
    #: raised on: a submission whose form was later edited still has answers
    #: that survived, and the ones that did not belong in the manifest.
    unmapped: frozenset[str]


def project_for_export(
    form: CompiledForm,
    *,
    stored: Mapping[str, Any],
    instances: Mapping[str, Sequence[str]],
    unreadable: Collection[str] = (),
    today: date | None = None,
    now: datetime | None = None,
    metadata: Mapping[str, Any] | None = None,
    datasets: DatasetSource | None = None,
) -> ExportProjection:
    """Rebuild one submission and project it for export.

    `stored`, `instances` and `unreadable` are what the op log folds to
    (`submissions.fold.fold_ops`); `form` is the version that submission was
    collected under, which the caller obtains from
    `forms.service.compiled_form_for_submission` and therefore cannot choose.

    An unreadable path is restored as **null**, because null is the truth: the
    server does not know what it says. §4.4 then coerces null to true at the
    relevance boundary, so a question gated on an encrypted answer stays in the
    export rather than vanishing from it — the safe direction, recorded in
    `relevance_uncertain`.
    """
    instance = FormInstance(
        form, today=today, now=now, metadata=dict(metadata or {}), datasets=datasets
    )
    unreadable_paths = set(unreadable)
    # An unreadable path is not in `stored` — the fold drops a value the server
    # cannot read — so it is put back as null here. Null is what it actually is
    # from this side, and restoring it explicitly is what makes a path the form
    # no longer has show up in `unmapped` whether or not it was encrypted.
    restored: dict[str, Any] = {path: None for path in unreadable_paths}
    restored.update(stored)
    unmapped = instance.restore(instances=instances, answers=restored)

    answers = instance.answers()

    hidden = _unreadable_fields(form, unreadable_paths)
    uncertain = _relevance_uncertain_fields(form, hidden)

    top = {fid: value for fid, value in answers.items() if "]." not in fid}
    repeats: dict[str, list[RepeatRow]] = {}
    for repeat_id, ordered in instance.instances.items():
        rows = []
        for index, instance_id in enumerate(ordered):
            prefix = f"{repeat_id}[{instance_id}]."
            rows.append(
                RepeatRow(
                    repeat_id=repeat_id,
                    instance_id=instance_id,
                    index=index,
                    cells={
                        field_of(path): value
                        for path, value in answers.items()
                        if path.startswith(prefix)
                    },
                )
            )
        repeats[repeat_id] = rows

    return ExportProjection(
        top=top,
        repeats={rid: tuple(rows) for rid, rows in repeats.items()},
        unreadable=frozenset(p for p in answers if field_of(p) in hidden),
        relevance_uncertain=frozenset(p for p in answers if field_of(p) in uncertain),
        unmapped=frozenset(unmapped),
    )


def _unreadable_fields(form: CompiledForm, unreadable: Collection[str]) -> frozenset[str]:
    """Field ids whose exported value the server cannot vouch for.

    Ciphertext to start with, then everything **computed** from it. That second
    half is the one worth having: `total_income` over three encrypted incomes
    evaluates to 0, and 0 written into a CSV is not an absence an analyst can
    see — it is a number, and it is wrong. So a calculate that reads an
    unreadable field is unreadable itself, transitively, in topological order.

    Granularity is the field, not the instance: if one member's income is
    ciphertext the roster's total is unreadable for every submission. That is
    conservative, and it costs nothing real — encryption is decided per field
    (`sensitive`, envelope §5.2) or per project, never per instance, so a field
    that is ciphertext anywhere is ciphertext everywhere it was collected.
    """
    hidden = {field_of(path) for path in unreadable} & set(form.fields)
    for field_id in form.topo_order:
        if field_id in hidden:
            continue
        calculate = form.fields[field_id].node.get("calculate")
        if isinstance(calculate, dict) and collect_refs(calculate) & hidden:
            hidden.add(field_id)
    return frozenset(hidden)


def _relevance_uncertain_fields(
    form: CompiledForm, hidden: Collection[str]
) -> frozenset[str]:
    """Field ids whose presence in the export rests on an unreadable answer."""
    unreadable = set(hidden)
    uncertain: set[str] = set()
    for field_id, compiled in form.fields.items():
        deps: set[str] = set()
        for node in [compiled.node] + [
            form.containers[a] for a in compiled.ancestors if a in form.containers
        ]:
            relevant = node.get("relevant")
            if isinstance(relevant, dict):
                collect_refs(relevant, deps)
        if deps & unreadable:
            uncertain.add(field_id)
    return frozenset(uncertain)
