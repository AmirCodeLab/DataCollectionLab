"""The shape of an export: which columns exist, in which order, and why.

A plan is computed from compiled forms and nothing else — no answers — so the
same form always exports the same columns whether one submission was collected
under it or ten thousand, and an empty export still tells a customer what the
file will look like.

**Several versions, one plan.** Submissions of a form sit on whatever version
they were collected under (§9), and the versions disagree about which fields
exist. Exporting them as separate files would leave a customer joining them by
hand; exporting them as one file with the newest version's columns would drop
answers collected under an older one. So the plan is the union, in document
order, oldest version first with later additions appended — and every column
records the versions that define it, because a blank cell for a field that did
not exist yet is not the same fact as a blank cell for a question nobody
answered. The parent table carries `form_version` on every row so the
distinction is available in the data as well as in the manifest.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from app.modules.form_engine.runtime import CompiledForm

from .cells import CHOICE_TYPES, COMPONENTS

type ColumnSource = Literal["meta", "field", "label", "count"]

#: Metadata columns on the parent table, in order. They are claimed *after*
#: every field name, so a form with a question called `status` keeps the column
#: it named and the metadata column is the one that moves. The form author's
#: identifiers are what analysis code is written against; ours are not.
META_COLUMNS: tuple[tuple[str, str], ...] = (
    ("submission_id", "Submission id"),
    ("form_id", "Form"),
    ("form_version", "Form version"),
    ("submission_status", "Status"),
    ("device_id", "Origin device"),
    ("created_by", "Created by"),
    ("started_at", "Started at"),
    ("finalized_at", "Finalized at"),
    ("received_at", "Received at"),
)

#: The key of every repeat row, and the whole of point 2. `submission_id` plus
#: `instance_id` is stable across exports; `instance_index` is where the row
#: currently sits and is for sorting, never for joining.
REPEAT_KEY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("submission_id", "Submission id"),
    ("instance_id", "Instance id"),
    ("instance_index", "Position in the list"),
)

LABEL_SUFFIX = "_label"
COUNT_SUFFIX = "_count"


@dataclass(frozen=True)
class Column:
    """One column, and everything the manifest and the reader need about it."""

    name: str
    source: ColumnSource
    #: The Form IR field this column comes from, for `field` and `label`; the
    #: repeat id for `count`; None for metadata.
    field_id: str | None = None
    data_type: str | None = None
    #: For a decomposed value: which part of it. See `cells.COMPONENTS`.
    component: str | None = None
    label: str | None = None
    repeat: str | None = None
    #: Form versions in which this column's field exists. Empty for metadata,
    #: which every version has.
    versions: tuple[int, ...] = ()
    #: 1-based instance slot, for a wide export's flattened repeat columns.
    #: Recorded so the file says what it is; it is still a position, and the
    #: manifest still says not to join on one.
    position: int | None = None


@dataclass(frozen=True)
class ColumnPlan:
    parent: tuple[Column, ...] = ()
    repeats: Mapping[str, tuple[Column, ...]] = field(default_factory=dict)
    versions: tuple[int, ...] = ()
    #: Field ids whose choice list is dataset-backed, by dataset key. The
    #: service resolves these through the form version's pins (§3.2) and
    #: nothing else may: a label resolved any other way is last month's name.
    dataset_fields: Mapping[str, str] = field(default_factory=dict)

    def repeat_ids(self) -> tuple[str, ...]:
        return tuple(self.repeats)


class _Names:
    """Hands out column names, data first.

    A form is allowed a question called `submission_id` or `village_label`, and
    when it has one the derived column is what gets a suffix. Refusing to
    export would be worse, and renaming the author's column would break the
    analysis that names it.
    """

    def __init__(self, reserved: Sequence[str]) -> None:
        self._taken = set(reserved)

    def claim(self, wanted: str, *, own: bool = False) -> str:
        if own:
            self._taken.add(wanted)
            return wanted
        name, serial = wanted, 1
        while name in self._taken:
            serial += 1
            name = f"{wanted}_{serial}"
        self._taken.add(name)
        return name


def build_plan(
    forms: Sequence[CompiledForm],
    *,
    language: str | None = None,
) -> ColumnPlan:
    """Columns for every version in `forms`, oldest first."""
    ordered = sorted(forms, key=lambda f: f.version)
    reserved = {fid for form in ordered for fid in form.fields}

    parent_names = _Names(sorted(reserved))
    repeat_names: dict[str, _Names] = {}

    parent: list[Column] = []
    repeats: dict[str, list[Column]] = {}
    seen: dict[tuple[str | None, str, str | None, str], Column] = {}
    versions: dict[tuple[str | None, str, str | None, str], list[int]] = {}
    dataset_fields: dict[str, str] = {}
    repeat_versions: dict[str, list[int]] = {}

    def emit(column: Column, repeat: str | None) -> None:
        key = (repeat, column.field_id or column.name, column.component, column.source)
        if key in seen:
            versions[key].extend(column.versions)
            return
        seen[key] = column
        versions[key] = list(column.versions)
        (repeats[repeat] if repeat is not None else parent).append(column)

    for form in ordered:
        for field_id in form.order:
            compiled = form.fields.get(field_id)
            if compiled is None:
                continue
            repeat = compiled.repeat
            if repeat is not None:
                if repeat not in repeats:
                    repeats[repeat] = []
                    repeat_names[repeat] = _Names(sorted(reserved))
                repeat_versions.setdefault(repeat, []).append(form.version)
            names = parent_names if repeat is None else repeat_names[repeat]

            label = _label_of(compiled.node, form, language)
            query = compiled.choice_query
            if query is not None:
                dataset_fields[field_id] = query.dataset

            for column in _columns_for(
                field_id, compiled.data_type, label, repeat, form.version
            ):
                # A bare field column already owns its name — it *is* the field
                # id, reserved before any derived name was handed out.
                own = column.source == "field" and column.component is None
                emit(_renamed(column, names.claim(column.name, own=own)), repeat)

    # Counts belong to the parent row: a roster of three is a fact about the
    # household, and it is what makes "did every instance arrive" answerable
    # from the parent file alone.
    for repeat_id in repeats:
        emit(
            Column(
                name=parent_names.claim(f"{repeat_id}{COUNT_SUFFIX}"),
                source="count",
                field_id=repeat_id,
                data_type="integer",
                label=f"Number of {repeat_id}",
                versions=tuple(sorted(set(repeat_versions.get(repeat_id, [])))),
            ),
            None,
        )

    meta = [
        Column(name=parent_names.claim(name), source="meta", field_id=name, label=title)
        for name, title in META_COLUMNS
    ]
    keys: dict[str, list[Column]] = {
        repeat_id: [
            Column(
                name=repeat_names[repeat_id].claim(name),
                source="meta",
                field_id=name,
                label=title,
                repeat=repeat_id,
            )
            for name, title in REPEAT_KEY_COLUMNS
        ]
        for repeat_id in repeats
    }

    def finalise(columns: list[Column]) -> tuple[Column, ...]:
        return tuple(
            _versioned(column, versions.get(_key_of(column), []))
            for column in columns
        )

    return ColumnPlan(
        parent=tuple(meta) + finalise(parent),
        repeats={
            repeat_id: tuple(keys[repeat_id]) + finalise(columns)
            for repeat_id, columns in repeats.items()
        },
        versions=tuple(form.version for form in ordered),
        dataset_fields=dataset_fields,
    )


def _key_of(column: Column) -> tuple[str | None, str, str | None, str]:
    return (column.repeat, column.field_id or column.name, column.component, column.source)


def _versioned(column: Column, found: Sequence[int]) -> Column:
    if column.source == "meta":
        return column
    return _replace(column, versions=tuple(sorted(set(found))))


def _columns_for(
    field_id: str,
    data_type: str,
    label: str | None,
    repeat: str | None,
    version: int,
) -> list[Column]:
    """The columns one question contributes.

    A `note` contributes none — it has no value (§2.1), and a column of blanks
    is a column somebody has to ask about.
    """
    if data_type == "note":
        return []

    def column(name: str, source: ColumnSource, component: str | None = None) -> Column:
        return Column(
            name=name,
            source=source,
            field_id=field_id,
            data_type=data_type,
            component=component,
            label=label,
            repeat=repeat,
            versions=(version,),
        )

    if data_type in COMPONENTS:
        return [
            column(f"{field_id}_{part}", "field", part) for part in COMPONENTS[data_type]
        ]

    columns = [column(field_id, "field")]
    if data_type in CHOICE_TYPES:
        # The code alone is not analysable — `V000023` with no name beside it
        # is what item 5 says an export must never be — and the name has to
        # come from the version the form was published against (§3.2).
        columns.append(column(f"{field_id}{LABEL_SUFFIX}", "label"))
    return columns


def _label_of(
    node: Mapping[str, object], form: CompiledForm, language: str | None
) -> str | None:
    labels = node.get("label")
    if not isinstance(labels, dict):
        return None
    wanted = language or str(form.ir.get("defaultLanguage") or "")
    found = labels.get(wanted)
    if found is None and labels:
        found = labels.get(str(form.ir.get("defaultLanguage") or ""))
    if found is None and labels:
        found = next(iter(labels.values()))
    return None if found is None else str(found)


def _renamed(column: Column, name: str) -> Column:
    return column if name == column.name else _replace(column, name=name)


def _replace(column: Column, **changes: object) -> Column:
    return dataclasses.replace(column, **changes)  # type: ignore[arg-type]
