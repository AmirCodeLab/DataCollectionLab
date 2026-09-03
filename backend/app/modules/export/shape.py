"""Projections into tables — the parent row, and the rows beneath it.

Two shapes, and the difference between them is the whole of point 2.

**Long** is the default and the one to analyse. The parent table holds one row
per submission and no repeat data at all; each repeat gets its own table, one
row per instance, keyed by `submission_id` **and the stable `instance_id`**.
That key is what makes yesterday's export and today's joinable: §2.3 resolves a
position against the *current* ordered list and deleting an instance does not
renumber storage, so a row keyed `members[1]` is a different person before and
after a delete and a join across two exports is silently wrong. The stable id
is in the op log already; nothing had to be invented to key on it.

**Wide** is one row per submission with the repeats flattened into
`members_1_name`, `members_2_name`, … It is what people expect and ask for, and
it is positional by construction — so it is offered, and the manifest says on
its face that its repeat columns are not stable across exports and that the
long tables are what to join on. Offering it without saying that would be
worse than not offering it.

`instance_index` exists in the long tables for the same reason: a household's
members have an order and somebody will want to sort by it. It is a column to
sort on and never one to join on, which is what its manifest entry says.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from app.modules.form_engine.projection import ExportProjection

from .cells import ENCRYPTED, LABEL_SEPARATOR, Cell, render
from .plan import Column, ColumnPlan, _Names

type Shape = Literal["long", "wide"]

#: field id -> choice code -> label, in the export language. For an inline
#: list this comes from the IR; for a dataset-backed one it comes through the
#: form version's pins and no other way (§3.2).
type ChoiceLabels = Mapping[str, Mapping[str, str]]


@dataclass(frozen=True)
class SubmissionRecord:
    """One submission, already projected, with its own version's names.

    `labels` is on the record and not on the export for a reason that is the
    whole of break 42: a dataset pin belongs to a form version, so two
    submissions of one form can legitimately disagree about what `V000023` is
    called. One lookup shared across the export would give every row the newest
    version's names — a file in which a code collected last season is explained
    by a village list published after it.
    """

    submission_id: str
    form_key: str
    form_version: int
    status: str
    device_id: str | None
    created_by: str | None
    started_at: datetime | None
    finalized_at: datetime | None
    received_at: datetime | None
    projection: ExportProjection
    #: field id -> choice code -> name, from **this submission's** version.
    labels: ChoiceLabels = field(default_factory=dict)


@dataclass(frozen=True)
class Table:
    name: str
    kind: Literal["submissions", "repeat"]
    columns: tuple[Column, ...]
    rows: tuple[tuple[Cell, ...], ...]
    repeat_id: str | None = None


_META: Mapping[str, Callable[[SubmissionRecord], Cell]] = {
    "submission_id": lambda r: r.submission_id,
    "form_id": lambda r: r.form_key,
    "form_version": lambda r: r.form_version,
    "submission_status": lambda r: r.status,
    "device_id": lambda r: r.device_id,
    "created_by": lambda r: r.created_by,
    "started_at": lambda r: _stamp(r.started_at),
    "finalized_at": lambda r: _stamp(r.finalized_at),
    "received_at": lambda r: _stamp(r.received_at),
}


def build_tables(
    plan: ColumnPlan,
    records: Sequence[SubmissionRecord],
    *,
    shape: Shape = "long",
    base_name: str,
) -> tuple[Table, ...]:
    if shape == "wide":
        return (_wide_table(plan, records, name=base_name),)
    return (
        Table(
            name=base_name,
            kind="submissions",
            columns=plan.parent,
            rows=tuple(_parent_row(plan.parent, record) for record in records),
        ),
        *(
            Table(
                name=f"{base_name}-{repeat_id}",
                kind="repeat",
                repeat_id=repeat_id,
                columns=columns,
                rows=tuple(_repeat_rows(columns, repeat_id, records)),
            )
            for repeat_id, columns in plan.repeats.items()
        ),
    )


def _parent_row(columns: Sequence[Column], record: SubmissionRecord) -> tuple[Cell, ...]:
    projection = record.projection
    return tuple(
        _cell(column, "", projection.top, projection, record.labels)
        if column.source in ("field", "label")
        else _meta_or_count(column, record)
        for column in columns
    )


def _repeat_rows(
    columns: Sequence[Column],
    repeat_id: str,
    records: Sequence[SubmissionRecord],
) -> list[tuple[Cell, ...]]:
    rows: list[tuple[Cell, ...]] = []
    for record in records:
        for row in record.projection.repeats.get(repeat_id, ()):
            key: Mapping[str, Cell] = {
                "submission_id": record.submission_id,
                "instance_id": row.instance_id,
                "instance_index": row.index,
            }
            rows.append(
                tuple(
                    key.get(column.field_id or "")
                    if column.source == "meta"
                    else _cell(
                        column,
                        f"{repeat_id}[{row.instance_id}]",
                        row.cells,
                        record.projection,
                        record.labels,
                    )
                    for column in columns
                )
            )
    return rows


def _wide_table(
    plan: ColumnPlan, records: Sequence[SubmissionRecord], *, name: str
) -> Table:
    """Every repeat flattened onto the parent row, bounded by what arrived."""
    widest = {
        repeat_id: max(
            (len(r.projection.repeats.get(repeat_id, ())) for r in records), default=0
        )
        for repeat_id in plan.repeats
    }
    names = _Names([column.name for column in plan.parent])

    columns = list(plan.parent)
    flattened: list[tuple[str, int, Column]] = []
    for repeat_id, repeat_columns in plan.repeats.items():
        for position in range(1, widest[repeat_id] + 1):
            for column in repeat_columns:
                if column.source == "meta":
                    continue
                wide = dataclasses.replace(
                    column,
                    name=names.claim(f"{repeat_id}_{position}_{column.name}"),
                    position=position,
                )
                flattened.append((repeat_id, position - 1, wide))
                columns.append(wide)

    rows = []
    for record in records:
        row = list(_parent_row(plan.parent, record))
        for repeat_id, index, column in flattened:
            instances = record.projection.repeats.get(repeat_id, ())
            if index >= len(instances):
                row.append(None)
                continue
            instance = instances[index]
            row.append(
                _cell(
                    column,
                    f"{repeat_id}[{instance.instance_id}]",
                    instance.cells,
                    record.projection,
                    record.labels,
                )
            )
        rows.append(tuple(row))

    return Table(name=name, kind="submissions", columns=tuple(columns), rows=tuple(rows))


def _meta_or_count(column: Column, record: SubmissionRecord) -> Cell:
    if column.source == "meta":
        read = _META.get(column.field_id or "")
        return None if read is None else read(record)
    instances = record.projection.repeats.get(column.field_id or "")
    return None if instances is None else len(instances)


def _cell(
    column: Column,
    prefix: str,
    cells: Mapping[str, Any],
    projection: ExportProjection,
    labels: ChoiceLabels,
) -> Cell:
    """One value cell. `prefix` is `""` at the top level, `members[i3]` inside."""
    field_id = column.field_id or ""
    path = f"{prefix}.{field_id}" if prefix else field_id

    if path in projection.unreadable:
        # Every column the value decomposes into carries the token, not only the
        # first: an `ENCRYPTED` latitude beside an empty longitude would read as
        # a half-answered point rather than as one nobody here can read.
        return ENCRYPTED
    if field_id not in cells:
        return None

    value = cells[field_id]
    if column.source == "label":
        return _label(value, column.data_type or "", labels.get(field_id, {}))
    return render(value, column.data_type or "text", column.component)


def _label(value: Any, data_type: str, lookup: Mapping[str, str]) -> Cell:
    """The name a code stands for, or the code itself when nothing names it.

    A code with no label should not happen — §6.3 validates membership against
    the same list this lookup is built from — so it means data collected before
    that was enforced, or against a list the pin no longer reaches. Echoing the
    code is the readable answer: the column beside it is populated, so a blank
    here would be the one thing it must not be mistaken for, an absence.
    """
    if value is None:
        return None
    if data_type == "select_multiple":
        if not isinstance(value, list) or not value:
            return None
        return LABEL_SEPARATOR.join(lookup.get(str(code), str(code)) for code in value)
    return lookup.get(str(value), str(value))


def _stamp(moment: datetime | None) -> Cell:
    return None if moment is None else moment.isoformat()

