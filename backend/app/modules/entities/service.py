"""Publishing dataset versions, and the deltas devices are sent.

A dataset is reference data a form chooses from — villages, species, a facility
register. `dataset`, `dataset_version` and `dataset_record` have existed since
migration 0001 and nothing has ever written to them; this is what does.

## Immutable, for the same reason a form version is

A published dataset version never changes. A submission is validated against
the form version it was collected under (Form IR §9), a form version is pinned
to the dataset versions it was published against (`form_version_dataset`), and
if a dataset version could be edited underneath that pinning the whole chain
would be a lie: an answer would be checked against a list nobody could
reconstruct. Republishing a version number with different content is refused,
exactly as `forms.service.publish_version` refuses it.

## Two hashes, doing different jobs

`dataset_record.row_hash` is SHA-256 over `canonical_json(data)` — the
encryption envelope's serialisation (§5.1), reused rather than reinvented,
because two servers must produce identical bytes for the same row or every
delta is spurious. It covers the **whole** row and answers one cheap question:
did anything about this row change.

That is deliberately not the same question as "must this device be sent
anything". A dataset carries columns no form references — the UCL village list
has more than the form uses — and an edit to one of those changes the row hash.
Shipping a delta for it would cost a 50k-row list a transfer over a field
connection for a change no enumerator can see. So the delta compares the
**projection** onto the columns a device's forms actually reference, and the
row hash is only the cheap first pass that says which rows are worth projecting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ulid import new_ulid
from app.modules.entities.models import Dataset, DatasetRecord, DatasetVersion

# The rules themselves live in `rows.py` so the XLSForm importer can apply the
# same ones at import time, in the report, before anybody uploads anything. Two
# copies would be two answers to "is this key usable", and the one an author saw
# would be whichever code path they happened to reach. Re-exported because they
# are part of this module's surface and callers already import them from here.
from app.modules.entities.rows import (  # noqa: F401  (re-export)
    KeyReport,
    check_keys,
    content_address,
    row_hash,
    version_checksum,
)


class DatasetRefused(Exception):
    """The dataset cannot be published. `reasons` says exactly why."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


@dataclass
class PublishedDataset:
    dataset_id: str
    dataset_version_id: str
    dataset_key: str
    version: int
    row_count: int
    checksum: str
    #: False when this exact content was already published under this number.
    created: bool = True
    warnings: list[str] = field(default_factory=list)
    published_at: datetime | None = None


async def publish_dataset_version(
    session: AsyncSession,
    *,
    project_id: str,
    dataset_key: str,
    rows: list[dict[str, Any]],
    key_column: str,
    name: str | None = None,
    version: int | None = None,
) -> PublishedDataset:
    """Store one immutable version of a dataset.

    `key_column` names the column holding each row's identity — the value a
    form's `valueColumn` will select on. It is what `record_key` is, and it is
    what a delta names when a row is deleted, so it must be present and unique
    or the dataset cannot be diffed at all.

    Idempotent by content: republishing a version whose checksum already matches
    returns the stored row untouched. Republishing a number with *different*
    content is refused — a form version pinned to it would otherwise have its
    choice list changed underneath it.
    """
    if not rows:
        raise DatasetRefused(
            [
                f"the dataset `{dataset_key}` has no rows. An empty reference list "
                "offers nothing to choose from, and is almost always a file that "
                "failed to parse rather than a deliberate one."
            ]
        )

    # The key rules are `rows.check_keys` and not a copy of them, so that the
    # import report an author reads before uploading says exactly what this
    # refuses. Its docstring is where the §3.1 exactness argument lives.
    keys = check_keys(rows, key_column)
    if keys.refused:
        raise DatasetRefused(keys.problems)
    warnings = list(keys.warnings)

    dataset = (
        await session.execute(
            select(Dataset).where(
                Dataset.project_id == project_id, Dataset.dataset_key == dataset_key
            )
        )
    ).scalar_one_or_none()
    if dataset is None:
        dataset = Dataset(
            id=new_ulid(),
            project_id=project_id,
            dataset_key=dataset_key,
            name=name or dataset_key,
        )
        session.add(dataset)
        await session.flush()

    hashed = [(str(row[key_column]), row_hash(row)) for row in rows]
    checksum = version_checksum(hashed)

    if version is None:
        newest = (
            await session.execute(
                select(DatasetVersion)
                .where(DatasetVersion.dataset_id == dataset.id)
                .order_by(DatasetVersion.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        # Idempotent by content when the caller did not name a number.
        #
        # Without this, uploading the same CSV twice publishes two identical
        # versions and the form pins to the second — which is not wrong so much
        # as untrue: nothing about the reference data changed, and a device
        # holding v1 would be told it is behind and re-fetch 50k identical rows.
        # The console flow makes this the common case rather than the odd one,
        # because pressing Publish re-sends the companion files every time.
        if newest is not None and newest.checksum == content_address(rows, key_column):
            return PublishedDataset(
                dataset_id=dataset.id,
                dataset_version_id=newest.id,
                dataset_key=dataset_key,
                version=newest.version,
                row_count=newest.row_count,
                checksum=newest.checksum,
                created=False,
                warnings=warnings,
                published_at=newest.published_at,
            )
        version = (newest.version if newest else 0) + 1

    existing = (
        await session.execute(
            select(DatasetVersion).where(
                DatasetVersion.dataset_id == dataset.id, DatasetVersion.version == version
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.checksum == checksum:
            # Same number, same content: the caller is re-running a seed or
            # retrying an upload. Nothing to do and nothing wrong.
            return PublishedDataset(
                dataset_id=dataset.id,
                dataset_version_id=existing.id,
                dataset_key=dataset_key,
                version=version,
                row_count=existing.row_count,
                checksum=checksum,
                created=False,
                warnings=warnings,
                published_at=existing.published_at,
            )
        raise DatasetRefused(
            [
                f"`{dataset_key}` version {version} is already published with different "
                "content. Published versions are immutable: a form version pinned to "
                "this one would have its choice list changed underneath it, and answers "
                "already collected against it could no longer be explained. Publish a "
                "new version instead."
            ]
        )

    dataset_version = DatasetVersion(
        id=new_ulid(),
        dataset_id=dataset.id,
        version=version,
        row_count=len(rows),
        checksum=checksum,
        # A version row that exists is a version that is published: nothing
        # here writes a draft. The column is nullable because migration 0001
        # left room for one, and leaving it NULL would make "published" a thing
        # only the absence of a timestamp records.
        published_at=func.now(),
    )
    session.add(dataset_version)
    await session.flush()

    session.add_all(
        [
            DatasetRecord(
                id=new_ulid(),
                dataset_version_id=dataset_version.id,
                record_key=key,
                data=row,
                row_hash=digest,
            )
            for row, (key, digest) in zip(rows, hashed, strict=True)
        ]
    )
    await session.flush()

    return PublishedDataset(
        dataset_id=dataset.id,
        dataset_version_id=dataset_version.id,
        dataset_key=dataset_key,
        version=version,
        row_count=len(rows),
        checksum=checksum,
        warnings=warnings,
        # func.now() is unresolved until the transaction commits; report the
        # publish time rather than issue a round trip to read it back — the same
        # as forms.service.publish_version.
        published_at=datetime.now(tz=UTC),
    )
