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

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ulid import new_ulid
from app.modules.entities.models import (
    Dataset,
    DatasetRecord,
    DatasetVersion,
    FormVersionDataset,
)

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
from app.modules.entities.schemas import DeployedDatasetVersion


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
                # The file's own order, kept. A choice list is offered in the
                # order its author wrote it, and nothing else here can carry
                # that: `id` is a ULID and a loop of them is not ordered.
                ordinal=index,
            )
            for index, (row, (key, digest)) in enumerate(zip(rows, hashed, strict=True))
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


# ---------------------------------------------------------------------------
# Delivery (sync §5, `scope=datasets`)
# ---------------------------------------------------------------------------
#
# A device is told about dataset versions the same way it is told about form
# versions: a **complete statement** of what its environment expects it to
# hold, not a stream of changes. That is what lets it notice a version being
# superseded, which no stream of additions could say.
#
# The set is derived from the pinning table rather than from the datasets a
# project happens to own. A device gets exactly the dataset versions the form
# versions deployed to it were published against — which is the pinning doing
# its job at the far end: the same guarantee that lets an answer be explained
# later is what decides which rows travel.


async def deployed_dataset_versions_for_device(
    session: AsyncSession, device_id: str
) -> list[DeployedDatasetVersion] | None:
    """The dataset manifest for one device (sync §5, `scope=datasets`).

    Derived from `form_version_dataset`: every dataset version pinned by a form
    version this device's environment deploys. Nothing else — a project's other
    datasets are not this device's business, and a dataset nothing references
    is a 38,000-row transfer for no question anybody will be asked.

    `None` when the device is unknown or revoked, exactly as the form manifest
    answers, and distinct from `[]`. That distinction is load-bearing at the
    other end: `[]` means "your forms reference no datasets" and `None` means
    "no answer", and a client that collapsed them would treat a failed sync as
    proof there was nothing to hold (break 28, one level down).
    """
    from app.modules.forms.service import deployed_versions_for_device

    deployed = await deployed_versions_for_device(session, device_id)
    if deployed is None:
        return None
    if not deployed:
        return []

    from app.modules.forms.models import FormVersion

    rows = await session.execute(
        select(
            FormVersionDataset.form_version_id,
            FormVersionDataset.dataset_key,
            DatasetVersion.id,
            DatasetVersion.version,
            DatasetVersion.row_count,
            DatasetVersion.checksum,
        )
        .join(DatasetVersion, DatasetVersion.id == FormVersionDataset.dataset_version_id)
        .where(
            FormVersionDataset.form_version_id.in_([v.form_version_id for v in deployed])
        )
        .order_by(FormVersionDataset.dataset_key, FormVersionDataset.form_version_id)
    )

    # Which columns each deployed form version filters on. Read from the IR
    # once per form version rather than per manifest entry: a form with five
    # lists would otherwise compile itself five times.
    irs = {
        row[0]: row[1]
        for row in await session.execute(
            select(FormVersion.id, FormVersion.ir).where(
                FormVersion.id.in_([v.form_version_id for v in deployed])
            )
        )
    }

    return [
        DeployedDatasetVersion(
            form_version_id=form_version_id,
            dataset_key=dataset_key,
            dataset_version_id=dataset_version_id,
            version=version,
            row_count=row_count,
            checksum=checksum,
            filter_columns=sorted(
                selector_columns(irs.get(form_version_id) or {}, dataset_key)
            ),
        )
        for form_version_id, dataset_key, dataset_version_id, version, row_count, checksum
        in rows
    ]


def selector_columns(ir: dict[str, Any], dataset_key: str) -> set[str]:
    """The columns a form version's filters *narrow on* for one dataset (§3.2).

    The selector's keys, and nothing else — not the label columns, not the value
    column, not the residual's. Those are read, and reading is what the row
    itself is for; narrowing is what an index is for, and indexing more than
    that is what a device pays for.

    It cost a measurement to learn: indexing every column made 8 x 38,000 =
    304,000 entries, a 7x slower first sync and a **105x slower delta**, because
    a delta copies the index across to the new version. One column is 38,000.
    """
    from app.modules.form_engine.datasets import compile_choices

    found: set[str] = set()

    def walk(nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            choices = node.get("choices")
            if isinstance(choices, dict) and choices.get("dataset") == dataset_key:
                query = compile_choices(choices)
                if query is not None:
                    found.update(query.selector)
            walk(node.get("children", []) or [])

    walk(ir.get("children", []) or [])
    # The value column too: membership (§6.3) is a lookup on it, and it is asked
    # on every recalculation of an answered question.
    for node in _questions(ir):
        choices = node.get("choices") or {}
        if choices.get("dataset") == dataset_key and choices.get("valueColumn"):
            found.add(str(choices["valueColumn"]))
    return found


def _questions(ir: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def walk(nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            out.append(node)
            walk(node.get("children", []) or [])

    walk(ir.get("children", []) or [])
    return out


async def dataset_rows_page(
    session: AsyncSession,
    *,
    dataset_version_id: str,
    cursor: str | None,
    limit: int,
) -> tuple[list[dict[str, Any]], str | None] | None:
    """One page of a dataset version's rows, and the cursor for the next.

    Paged because the first sync is the hard case and cannot be one response:
    38,000 villages is megabytes, on a connection that drops, and a transfer
    that cannot resume is a transfer that never finishes. The cursor is the last
    row's id, so resuming re-reads nothing and the walk is stable — a published
    version is immutable (§3.1), so the ordering cannot shift under a paused
    device.

    None when the version does not exist. `[]` with no cursor is a real answer
    only for a version with no rows, which `publish_dataset_version` refuses to
    create; it is here because a caller must not have to tell those apart.
    """
    exists = (
        await session.execute(
            select(DatasetVersion.id).where(DatasetVersion.id == dataset_version_id)
        )
    ).scalar_one_or_none()
    if exists is None:
        return None

    statement = (
        select(DatasetRecord.ordinal, DatasetRecord.data)
        .where(DatasetRecord.dataset_version_id == dataset_version_id)
        .order_by(DatasetRecord.ordinal)
        .limit(limit + 1)
    )
    if cursor:
        # The cursor is an ordinal, so a resumed page is an index range rather
        # than a sort. Anything unparseable starts from the beginning rather
        # than failing: a device that garbled its cursor should re-transfer,
        # not stop.
        try:
            statement = statement.where(DatasetRecord.ordinal > int(cursor))
        except ValueError:
            pass

    found = list(await session.execute(statement))
    has_more = len(found) > limit
    page = found[:limit]
    next_cursor = str(page[-1][0]) if (has_more and page) else None
    return [dict(data) for _, data in page], next_cursor


async def dataset_rows_for(
    session: AsyncSession, submission_id: str, dataset_key: str
) -> list[dict[str, Any]] | None:
    """The rows one submission's form version pinned `dataset_key` to.

    **The caller does not choose a version, and that is the point.** The IR
    names a dataset by key (§3) and a key is not a version; resolving one at
    read time would let a submission be explained against whatever list is
    newest, which is break 40's mistake with villages instead of choices.

    This is `forms.service.compiled_form_for_submission` one level down, and it
    is written the same way for the same reason: there is deliberately **no**
    `version` parameter and no sibling function that takes one. The client's
    `DatasetStore.rowsFor` has the same shape.

    None when the submission is unknown, or its form version pins no such key —
    both the honest answer rather than a fallback to some other version.
    """
    found = await dataset_rows_for_submissions(session, [submission_id], dataset_key)
    return found.get(submission_id)


async def dataset_rows_for_submissions(
    session: AsyncSession, submission_ids: Sequence[str], dataset_key: str
) -> dict[str, list[dict[str, Any]]]:
    """`dataset_rows_for` for many submissions, without asking many times.

    Export resolves a village code to a village name for every submission in a
    run, and the submissions are on whatever form version each was collected
    under — so the pins differ within one export and the answer has to be per
    submission. The batching is in **how** the question is asked, never in what
    is asked: still no version parameter, still no overload that takes one, and
    a submission whose version pins nothing is absent from the result rather
    than falling back to the newest list.

    Rows are fetched once per distinct pinned version and the same list object
    is handed to every submission pinned to it. A village list is 38,000 rows;
    copying it per submission is the difference between an export that runs and
    one that does not.
    """
    from app.modules.submissions.models import Submission

    if not submission_ids:
        return {}

    pins = (
        await session.execute(
            select(Submission.id, FormVersionDataset.dataset_version_id)
            .join(
                FormVersionDataset,
                FormVersionDataset.form_version_id == Submission.form_version_id,
            )
            .where(
                Submission.id.in_(list(submission_ids)),
                FormVersionDataset.dataset_key == dataset_key,
            )
        )
    ).all()
    if not pins:
        return {}

    rows_of: dict[str, list[dict[str, Any]]] = {}
    for version_id in {version_id for _, version_id in pins}:
        records = (
            (
                await session.execute(
                    select(DatasetRecord.data)
                    .where(DatasetRecord.dataset_version_id == version_id)
                    .order_by(DatasetRecord.ordinal)
                )
            )
            .scalars()
            .all()
        )
        rows_of[version_id] = [dict(record) for record in records]

    return {submission_id: rows_of[version_id] for submission_id, version_id in pins}


# ---------------------------------------------------------------------------
# Incremental delivery (item 4 part 5)
# ---------------------------------------------------------------------------


class DeltaRefused(Exception):
    """The diff cannot be computed, and a full transfer is not the answer.

    **This class is the guard.** The tempting behaviour when a device asks for a
    diff the server cannot produce is to send the whole list instead — it always
    works, and the device ends up correct. It is also silent, and it papers over
    the only evidence that something is wrong: a device asking to go from a
    version this dataset never had, or for a list its form was not published
    against, is a device whose state nobody understands, and re-sending 38,000
    rows makes that state *look* fine.

    So a mismatch refuses, loudly, with a reason. "No changes" and "I could not
    ask" must never be the same silence — which is the whole failure mode of a
    delta mechanism and the reason this is built with delivery rather than after
    it.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def columns_read_by(ir: dict[str, Any], dataset_key: str) -> set[str]:
    """The columns a form version actually reads from one dataset (§3.2).

    Value column, every label column, and every `$row.` the filter names.
    Nothing else — and that is the entire point of stage two: a dataset carries
    columns no form references (the UCL village list has eight and the form
    reads four), and an edit to one of those must not cost a 38,000-row list a
    transfer over a field connection for a change no enumerator can see.

    Derived from the IR by the same `compile_choices` the engine uses, rather
    than by a second walk written here. A projection computed one way on the
    server and another way in the engine would ship deltas nobody needs, or
    worse, skip ones somebody does.
    """
    from app.modules.form_engine.datasets import ROW_PREFIX, compile_choices

    found: set[str] = set()

    def walk(nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            choices = node.get("choices")
            if isinstance(choices, dict) and choices.get("dataset") == dataset_key:
                query = compile_choices(choices)
                if query is not None:
                    found.add(query.value_column)
                    found.update(query.label_columns.values())
                    # The selector's KEYS are columns; its values are
                    # expressions over answers and read nothing from the row.
                    found.update(query.selector)
                    if query.residual is not None:
                        # `collect_refs` drops `$row.` deliberately — they are
                        # columns, not fields — so the residual's columns are
                        # picked out here instead.
                        found.update(
                            r[len(ROW_PREFIX):] for r in _row_refs(query.residual)
                        )
            walk(node.get("children", []) or [])

    walk(ir.get("children", []) or [])
    return found


def _row_refs(expr: Any) -> set[str]:
    from app.modules.form_engine.datasets import ROW_PREFIX

    found: set[str] = set()
    if isinstance(expr, dict):
        if expr.get("op") == "ref" and str(expr.get("path", "")).startswith(ROW_PREFIX):
            found.add(str(expr["path"]))
        for arg in expr.get("args") or []:
            found |= _row_refs(arg)
    return found


@dataclass
class DatasetDelta:
    """What changed between two versions of one dataset, for one form version."""

    dataset_version_id: str
    from_dataset_version_id: str
    #: Rows whose projection onto the columns this form reads is different, or
    #: which are new. Whole rows, not just the changed columns: a device stores
    #: whole rows because another form version may read different ones.
    changed: list[dict[str, Any]] = field(default_factory=list)
    #: Keys that are gone. **Explicit**, never inferred from absence —
    #: inferring it needs the whole set present to compare against, which is
    #: the thing being avoided. A form manifest can be a complete statement
    #: because it is 300 bytes; a 38,000-row dataset cannot.
    deleted: list[str] = field(default_factory=list)
    next_cursor: str | None = None
    #: The columns the projection was taken over — reported so a device (and a
    #: person reading a trace) can see *why* a row did or did not travel.
    columns: list[str] = field(default_factory=list)


async def dataset_delta(
    session: AsyncSession,
    *,
    form_version_id: str,
    dataset_key: str,
    from_dataset_version_id: str,
    cursor: str | None,
    limit: int,
) -> DatasetDelta:
    """The diff a device on `from` needs to reach what `form_version_id` pins.

    Two stages, and the second is the one that matters (docs/project-conventions.md, item 4):

    1. `dataset_record.row_hash` answers "did anything about this row change",
       cheaply. It covers the **whole** row.
    2. That is deliberately not the same question as "must this device be sent
       anything". The projection onto the columns this form version actually
       reads is what decides, so an edit to a column no form references costs
       nobody a transfer.

    Refuses rather than falling back to a full transfer — see [DeltaRefused].
    A device holding nothing does not come here at all: it has no `from`, and
    the paged rows endpoint is the first-sync path.
    """
    to_version = (
        await session.execute(
            select(FormVersionDataset.dataset_version_id).where(
                FormVersionDataset.form_version_id == form_version_id,
                FormVersionDataset.dataset_key == dataset_key,
            )
        )
    ).scalar_one_or_none()
    if to_version is None:
        raise DeltaRefused(
            f"form version {form_version_id} was not published against any "
            f"`{dataset_key}`. A device asking for one is a device whose state "
            "does not match this server's, and sending it a list would hide that "
            "rather than fix it."
        )

    rows = (
        await session.execute(
            select(DatasetVersion.id, DatasetVersion.dataset_id, DatasetVersion.version).where(
                DatasetVersion.id.in_([to_version, from_dataset_version_id])
            )
        )
    ).all()
    found = {row[0]: row for row in rows}
    if from_dataset_version_id not in found:
        raise DeltaRefused(
            f"this device says it holds dataset version {from_dataset_version_id}, "
            "which this server has never published. Something about that device's "
            "state is wrong, and a full transfer would make it look right."
        )
    if found[from_dataset_version_id][1] != found[to_version][1]:
        raise DeltaRefused(
            f"dataset version {from_dataset_version_id} belongs to a different "
            f"dataset than `{dataset_key}`. These two lists have no diff — one is "
            "not a later version of the other."
        )

    from app.modules.forms.models import FormVersion

    ir = (
        await session.execute(
            select(FormVersion.ir).where(FormVersion.id == form_version_id)
        )
    ).scalar_one_or_none()
    columns = sorted(columns_read_by(ir or {}, dataset_key))

    def projection(data: dict[str, Any]) -> str:
        return row_hash({c: data.get(c) for c in columns})

    before = {
        key: projection(data)
        for key, data in await session.execute(
            select(DatasetRecord.record_key, DatasetRecord.data).where(
                DatasetRecord.dataset_version_id == from_dataset_version_id
            )
        )
    }

    # Two phases in one cursor: the changed rows in publication order, then the
    # deleted keys. Both are bounded, and paging only one of them would leave
    # the other unbounded — a version that dropped 30,000 villages is exactly
    # the case a delta is for.
    phase, position = ("c", "") if not cursor else (cursor[:1], cursor[2:])

    changed: list[dict[str, Any]] = []
    if phase == "c":
        statement = (
            select(DatasetRecord.ordinal, DatasetRecord.record_key, DatasetRecord.data)
            .where(DatasetRecord.dataset_version_id == to_version)
            .order_by(DatasetRecord.ordinal)
        )
        if position:
            statement = statement.where(DatasetRecord.ordinal > int(position))
        last_ordinal: int | None = None
        for ordinal, key, data in await session.execute(statement):
            if before.get(key) != projection(dict(data)):
                changed.append(dict(data))
            last_ordinal = ordinal
            if len(changed) >= limit:
                return DatasetDelta(
                    dataset_version_id=to_version,
                    from_dataset_version_id=from_dataset_version_id,
                    changed=changed,
                    next_cursor=f"c:{last_ordinal}",
                    columns=columns,
                )
        phase, position = "d", ""

    present = set(
        (
            await session.execute(
                select(DatasetRecord.record_key).where(
                    DatasetRecord.dataset_version_id == to_version
                )
            )
        ).scalars()
    )
    gone = sorted(key for key in before if key not in present)
    if position:
        gone = [key for key in gone if key > position]
    page = gone[:limit]
    return DatasetDelta(
        dataset_version_id=to_version,
        from_dataset_version_id=from_dataset_version_id,
        changed=changed,
        deleted=page,
        next_cursor=f"d:{page[-1]}" if len(gone) > limit else None,
        columns=columns,
    )
