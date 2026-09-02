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

import hashlib
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ulid import new_ulid
from app.modules.crypto.envelope import canonical_json
from app.modules.entities.models import Dataset, DatasetRecord, DatasetVersion


class DatasetRefused(Exception):
    """The dataset cannot be published. `reasons` says exactly why."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def row_hash(data: dict[str, Any]) -> str:
    """SHA-256 over the row's canonical JSON.

    `canonical_json` is the envelope's (§5.1) — sorted keys, no spaces, UTF-8,
    no NaN — and it is reused rather than replaced because it already has a
    conformance vector proving two implementations agree on it. A second
    serialisation invented here would be a second thing to keep in step, and
    the symptom of getting it wrong is every row looking changed.
    """
    return "sha256:" + hashlib.sha256(canonical_json(data)).hexdigest()


def version_checksum(rows: list[tuple[str, str]]) -> str:
    """A whole version's content address, from its (key, row_hash) pairs.

    Sorted by key so two servers that inserted the same rows in different
    orders agree. This is what "is this the same dataset" means, and what a
    device compares to know whether it is behind.
    """
    digest = hashlib.sha256()
    for key, digest_of_row in sorted(rows):
        digest.update(key.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(digest_of_row.encode("utf-8"))
        digest.update(b"\x00")
    return "sha256:" + digest.hexdigest()


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

    keys: list[str] = []
    duplicates: dict[str, int] = {}
    missing = 0
    for row in rows:
        raw = row.get(key_column)
        key = "" if raw is None else str(raw).strip()
        if not key:
            missing += 1
            continue
        if key in duplicates:
            duplicates[key] += 1
        else:
            duplicates[key] = 1
        keys.append(key)

    problems: list[str] = []
    if missing:
        problems.append(
            f"{missing} row(s) have no value in the key column `{key_column}`. "
            "A row with no identity cannot be selected, referred to, or deleted "
            "in a later version."
        )
    repeated = sorted(k for k, n in duplicates.items() if n > 1)
    if repeated:
        extra = len(repeated) - 5
        shown = ", ".join(repeated[:5]) + (f" (+{extra} more)" if extra > 0 else "")
        problems.append(
            f"{len(repeated)} key(s) in `{key_column}` appear more than once: {shown}. "
            "Keys identify rows across versions, so a repeated one makes it "
            "impossible to say which row a later change refers to."
        )
    if problems:
        raise DatasetRefused(problems)

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

    hashed = [(str(row[key_column]).strip(), row_hash(row)) for row in rows]
    checksum = version_checksum(hashed)

    if version is None:
        highest = (
            await session.execute(
                select(DatasetVersion.version)
                .where(DatasetVersion.dataset_id == dataset.id)
                .order_by(DatasetVersion.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        version = (highest or 0) + 1

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
    )
