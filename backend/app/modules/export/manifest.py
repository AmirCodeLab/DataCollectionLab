"""The manifest — what this export contains, and what it declines to contain.

docs/project-conventions.md item 5: *"An export that is partly encrypted and does not say so is
worse than one that fails."* A file where some cells are unreadable and nothing
records which ones is a file somebody will analyse anyway.

So every column is described here: the field it came from, its type, the form
versions that define it, whether it can carry the `ENCRYPTED` token and why,
and — for the columns that can — **which project key ids open it**. That last
one is the practical question. "This column is encrypted" tells a customer they
have a problem; "this column is wrapped to key `pk_3f2a`" tells them who to ask.

The manifest is also what makes the export *re-readable*: `readback` uses the
column list and its types to turn cells back into values, which is how the
round-trip invariant is checked at all. It is a description that has to be
correct rather than one that only has to look right.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from .cells import ENCRYPTED
from .plan import Column, ColumnPlan
from .shape import Shape, SubmissionRecord, Table

type Unreadable = Literal["encrypted", "computed_from_encrypted"]

WIDE_POSITION_NOTE = (
    "This export is the wide shape: repeat instances are flattened into "
    "positional columns (members_1_name, members_2_name, ...). A position is "
    "not a stable identity — Form IR §2.3 resolves it against the current "
    "ordered list, and deleting an instance does not renumber storage — so "
    "position 1 can mean a different person in this file and the next one. "
    "Join on the long shape's (submission_id, instance_id) instead."
)

ENCRYPTED_NOTE = (
    f"A cell reading {ENCRYPTED!r} is a value this server cannot read, not an "
    "answer and not a blank. Columns where it can appear are listed with an "
    "`unreadable` reason below; a cell with that text in any other column is "
    "somebody's answer."
)

INSTANCE_KEY_NOTE = (
    "Repeat rows are keyed by (submission_id, instance_id). `instance_index` "
    "is the position in the current ordered list: sort by it, never join on it."
)


@dataclass(frozen=True)
class ColumnManifest:
    column: str
    source: str
    label: str | None
    path: str | None
    data_type: str | None
    component: str | None
    versions: tuple[int, ...]
    repeat: str | None
    position: int | None
    unreadable: Unreadable | None
    #: Project key ids whose private half opens this column's values. Empty when
    #: the column is readable; empty *and* unreadable is its own finding — a
    #: value wrapped to nobody, which no key holder can ever open.
    openable_by: tuple[str, ...]
    relevance_uncertain: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "source": self.source,
            "label": self.label,
            "path": self.path,
            "dataType": self.data_type,
            "component": self.component,
            "versions": list(self.versions),
            "repeat": self.repeat,
            "position": self.position,
            "unreadable": self.unreadable,
            "openableBy": list(self.openable_by),
            "relevanceUncertain": self.relevance_uncertain,
        }


@dataclass(frozen=True)
class TableManifest:
    name: str
    kind: str
    repeat_id: str | None
    row_count: int
    columns: tuple[ColumnManifest, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "repeatId": self.repeat_id,
            "rowCount": self.row_count,
            "columns": [column.as_dict() for column in self.columns],
        }


@dataclass(frozen=True)
class Manifest:
    form_id: str
    form_title: str | None
    form_versions: tuple[int, ...]
    language: str | None
    shape: Shape
    exported_at: datetime
    submission_count: int
    tables: tuple[TableManifest, ...]
    notes: tuple[str, ...] = ()
    #: Value paths found in storage that no version of this form has a field
    #: for, with the submissions they came from. Not an error and not silent:
    #: it is the answer to "what did not survive a form edit".
    unmapped: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "formId": self.form_id,
            "formTitle": self.form_title,
            "formVersions": list(self.form_versions),
            "language": self.language,
            "shape": self.shape,
            "exportedAt": self.exported_at.isoformat(),
            "submissionCount": self.submission_count,
            "encryptedToken": ENCRYPTED,
            "notes": list(self.notes),
            "unmapped": {path: list(ids) for path, ids in sorted(self.unmapped.items())},
            "tables": [table.as_dict() for table in self.tables],
        }


def build_manifest(
    plan: ColumnPlan,
    tables: Sequence[Table],
    records: Sequence[SubmissionRecord],
    *,
    form_id: str,
    form_title: str | None,
    language: str | None,
    shape: Shape,
    ciphertext_fields: Mapping[str, Sequence[str]],
    exported_at: datetime | None = None,
) -> Manifest:
    """Describe what was written.

    `ciphertext_fields` maps a field id whose value arrived as ciphertext to the
    project key ids that open it. A field marked unreadable that is *not* in it
    was computed from one that is — `sum` over three encrypted incomes is 0, and
    0 in a CSV is a number rather than a gap somebody can see.
    """
    unreadable_fields: set[str] = set()
    uncertain_fields: set[str] = set()
    unmapped: dict[str, list[str]] = {}
    for record in records:
        unreadable_fields |= {_field_of(p) for p in record.projection.unreadable}
        uncertain_fields |= {_field_of(p) for p in record.projection.relevance_uncertain}
        for path in record.projection.unmapped:
            unmapped.setdefault(path, []).append(record.submission_id)

    def describe(column: Column) -> ColumnManifest:
        field_id = column.field_id if column.source in ("field", "label") else None
        reason: Unreadable | None = None
        if field_id is not None and field_id in unreadable_fields:
            reason = "encrypted" if field_id in ciphertext_fields else "computed_from_encrypted"
        return ColumnManifest(
            column=column.name,
            source=column.source,
            label=column.label,
            path=field_id,
            data_type=column.data_type,
            component=column.component,
            versions=column.versions,
            repeat=column.repeat,
            position=column.position,
            unreadable=reason,
            openable_by=tuple(ciphertext_fields.get(field_id or "", ())),
            relevance_uncertain=field_id is not None and field_id in uncertain_fields,
        )

    notes = [ENCRYPTED_NOTE]
    notes.append(WIDE_POSITION_NOTE if shape == "wide" else INSTANCE_KEY_NOTE)

    return Manifest(
        form_id=form_id,
        form_title=form_title,
        form_versions=plan.versions,
        language=language,
        shape=shape,
        exported_at=exported_at or datetime.now(UTC),
        submission_count=len(records),
        tables=tuple(
            TableManifest(
                name=table.name,
                kind=table.kind,
                repeat_id=table.repeat_id,
                row_count=len(table.rows),
                columns=tuple(describe(column) for column in table.columns),
            )
            for table in tables
        ),
        notes=tuple(notes),
        unmapped={path: tuple(sorted(ids)) for path, ids in unmapped.items()},
    )


def _field_of(path: str) -> str:
    return path.split("].", 1)[1] if "]." in path else path
