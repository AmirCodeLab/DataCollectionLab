"""Reading a bundle back into submissions — the other half of the round trip.

docs/project-conventions.md item 5 asks for two invariants rather than a list of cases, and this
module exists to make the first one checkable: *export, re-import, compare
against the source submission*. It reads the **files**, using the manifest as
the schema, so what is compared has genuinely been through CSV quoting or an
xlsx cell — not through an in-memory structure that happens to be sitting there.

It reads the **long** shape only, and that is a statement rather than an
omission. A wide export flattens instances onto positional columns and there is
no instance id anywhere in the file, so instance identity cannot come back out
of one. That is the whole reason the manifest tells a reader to join on the
long shape, and a readback that quietly invented ids for wide rows would hide
the very property the shape does not have.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .cells import Cell, parse
from .manifest import ColumnManifest, Manifest
from .writers import SHEET_NAME_LIMIT, Bundle, read_csv, read_xlsx


@dataclass(frozen=True)
class ReadInstance:
    instance_id: str
    index: int
    cells: Mapping[str, Any]


@dataclass(frozen=True)
class ReadSubmission:
    submission_id: str
    form_version: int | None
    top: Mapping[str, Any] = field(default_factory=dict)
    repeats: Mapping[str, tuple[ReadInstance, ...]] = field(default_factory=dict)


class NotRoundTrippable(Exception):
    """Raised for a wide bundle. See the module docstring — it is not a defect."""


def read_bundle(bundle: Bundle) -> dict[str, ReadSubmission]:
    """Every submission the files describe, keyed by submission id."""
    manifest = bundle.manifest
    if manifest.shape != "long":
        raise NotRoundTrippable(
            f"a {manifest.shape} export has no instance ids in it; only the long "
            "shape can be read back into submissions"
        )

    sheets = _sheets(bundle)
    submissions: dict[str, ReadSubmission] = {}
    repeats: dict[str, dict[str, list[ReadInstance]]] = {}

    for table in manifest.tables:
        # An .xlsx sheet name is capped at 31 characters, so a long table
        # name is truncated in the workbook and not in the manifest.
        header, rows = sheets.get(
            table.name, sheets.get(table.name[:SHEET_NAME_LIMIT], ((), ()))
        )
        if not header:
            continue
        at = {name: index for index, name in enumerate(header)}
        for row in rows:
            read = _read_row(table.columns, at, row)
            submission_id = str(read.key.get("submission_id") or "")
            if not submission_id:
                continue
            if table.kind == "repeat" and table.repeat_id is not None:
                index = read.key.get("instance_index")
                repeats.setdefault(submission_id, {}).setdefault(
                    table.repeat_id, []
                ).append(
                    ReadInstance(
                        instance_id=str(read.key.get("instance_id") or ""),
                        index=int(index) if index is not None else 0,
                        cells=read.cells,
                    )
                )
            else:
                version = read.key.get("form_version")
                submissions[submission_id] = ReadSubmission(
                    submission_id=submission_id,
                    form_version=None if version is None else int(version),
                    top=read.cells,
                )

    return {
        submission_id: ReadSubmission(
            submission_id=submission_id,
            form_version=submission.form_version,
            top=submission.top,
            repeats={
                repeat_id: tuple(sorted(instances, key=lambda i: i.index))
                for repeat_id, instances in repeats.get(submission_id, {}).items()
            },
        )
        for submission_id, submission in submissions.items()
    }


@dataclass(frozen=True)
class _Row:
    key: Mapping[str, Any]
    cells: Mapping[str, Any]


def _read_row(
    columns: Sequence[ColumnManifest], at: Mapping[str, int], row: Sequence[Cell]
) -> _Row:
    key: dict[str, Any] = {}
    cells: dict[str, Any] = {}
    parts: dict[str, dict[str, Any]] = {}

    for column in columns:
        index = at.get(column.column)
        if index is None or index >= len(row):
            continue
        cell = row[index]
        if column.source == "meta":
            key[column.path or column.column] = None if cell == "" else cell
            continue
        # A label column is derived from the code column beside it; reading it
        # back would be reading the same answer twice, and the second reading
        # cannot be checked against anything.
        if column.source != "field" or column.path is None:
            continue
        value = parse(cell, column.data_type or "text", column.component)
        if column.component is None:
            cells[column.path] = value
        else:
            parts.setdefault(column.path, {})[column.component] = value

    for path, components in parts.items():
        # A structured value none of whose parts arrived is an unanswered
        # question, not a point at the origin.
        cells[path] = None if all(v is None for v in components.values()) else components
        if any(v == "ENCRYPTED" for v in components.values()):
            cells[path] = "ENCRYPTED"

    return _Row(key=key, cells=cells)


def _sheets(bundle: Bundle) -> Mapping[str, tuple[tuple[str, ...], tuple[tuple[Cell, ...], ...]]]:
    found: dict[str, tuple[tuple[str, ...], tuple[tuple[Cell, ...], ...]]] = {}
    for name, content in bundle.files:
        if name.endswith(".csv"):
            header, rows = read_csv(content)
            found[name[: -len(".csv")]] = (header, rows)
        elif name.endswith(".xlsx"):
            found.update(read_xlsx(content))
    return found


def unreadable_columns(manifest: Manifest) -> frozenset[str]:
    """Every column that can carry the token, so a comparison can allow for it."""
    return frozenset(
        column.column
        for table in manifest.tables
        for column in table.columns
        if column.unreadable is not None
    )
