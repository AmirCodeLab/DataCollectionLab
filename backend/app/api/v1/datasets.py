"""Dataset versions and their rows (sync §5, Form IR §3).

The second half of dataset delivery. `GET /sync/pull?scope=datasets` tells a
device which dataset versions the forms deployed to it were published against
and what they hash to; this hands over the rows for a version it does not hold.

Splitting the two is what keeps a sync cheap, and at this size it is not a
nicety: the UCL village list is 38,000 rows against a manifest entry of about a
hundred bytes, and the manifest travels on every pull while the rows travel
once. It is the same shape as the form manifest and as resumable media upload —
the server states what exists, the device asks only for what it lacks.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.schemas import MessageError
from app.modules.entities import service
from app.modules.entities.schemas import (
    DatasetDeltaPage,
    DatasetRefusedError,
    DatasetRowsPage,
)

router = APIRouter()

#: A page big enough that 38,000 rows is a manageable number of requests and
#: small enough to survive a field connection. The first sync is the hard case:
#: a transfer that cannot resume is a transfer that never finishes.
DEFAULT_ROW_LIMIT = 2_000
MAX_ROW_LIMIT = 10_000


@router.get(
    "/versions/{dataset_version_id}/rows",
    response_model=DatasetRowsPage,
    response_model_by_alias=True,
    responses={404: {"model": MessageError}},
)
async def dataset_rows(
    session: Annotated[AsyncSession, Depends(get_db)],
    dataset_version_id: Annotated[str, Path(min_length=1, max_length=64)],
    cursor: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_ROW_LIMIT)] = DEFAULT_ROW_LIMIT,
) -> DatasetRowsPage:
    """One page of a dataset version's rows, resumably.

    `cursor` is the `nextCursor` of the previous page and nothing else — not a
    row number, not an offset. A published dataset version is immutable (§3.1),
    so the ordering cannot shift under a device that paused for a day, and a
    resumed transfer re-reads nothing.

    `nextCursor` is null on the last page. That is how a device knows it has the
    **whole** list rather than most of one, which matters more here than
    anywhere else in this API: a village list that stopped two thirds of the way
    through is a list an enumerator can search, scroll and choose from, and
    nothing about it looks wrong.

    Immutable, so a response may be cached forever.
    """
    async with session.begin():
        page = await service.dataset_rows_page(
            session,
            dataset_version_id=dataset_version_id,
            cursor=cursor,
            limit=limit,
        )
    if page is None:
        raise HTTPException(status_code=404, detail="dataset version not found")

    rows, next_cursor = page
    return DatasetRowsPage(
        dataset_version_id=dataset_version_id,
        rows=[{str(k): str(v) for k, v in row.items()} for row in rows],
        next_cursor=next_cursor,
        has_more=next_cursor is not None,
    )


@router.get(
    "/versions/{dataset_version_id}/delta",
    response_model=DatasetDeltaPage,
    response_model_by_alias=True,
    responses={409: {"model": DatasetRefusedError}},
    description=(
        "What changed between the version a device holds and the one a form "
        "version was published against.\n\n"
        "This is the path that decides whether the feature is usable in a "
        "village. First sync is a one-off at enrolment; this is what happens "
        "every week for the life of the project.\n\n"
        "**Two stages.** `dataset_record.row_hash` answers 'did anything about "
        "this row change', cheaply, over the whole row. That is deliberately "
        "not the same question as 'must this device be sent anything': a "
        "dataset carries columns no form references — the UCL village list has "
        "eight and the form reads four — and an edit to one of those must not "
        "cost a 38,000-row list a transfer. So what decides is the projection "
        "onto the columns this form version actually reads, and `columns` "
        "reports which those were.\n\n"
        "**Deletions are explicit.** Inferring them from absence needs the "
        "whole set present to compare against, which is the thing being "
        "avoided.\n\n"
        "**A mismatch is a 409, never a full transfer.** A device asking to "
        "come from a version this server never published, or for a list its "
        "form was not published against, is a device whose state nobody "
        "understands — and re-sending the whole list would make that state look "
        "fine. 'No changes' and 'I could not ask' must not be the same silence."
    ),
)
async def dataset_delta(
    session: Annotated[AsyncSession, Depends(get_db)],
    dataset_version_id: Annotated[str, Path(min_length=1, max_length=64)],
    form_version_id: Annotated[str, Query(alias="formVersionId", max_length=64)],
    dataset_key: Annotated[str, Query(alias="datasetKey", max_length=200)],
    limit: Annotated[int, Query(ge=1, le=MAX_ROW_LIMIT)] = DEFAULT_ROW_LIMIT,
    cursor: Annotated[str | None, Query(max_length=256)] = None,
) -> DatasetDeltaPage:
    """The diff, paged. `dataset_version_id` is what the device holds now."""
    async with session.begin():
        try:
            delta = await service.dataset_delta(
                session,
                form_version_id=form_version_id,
                dataset_key=dataset_key,
                from_dataset_version_id=dataset_version_id,
                cursor=cursor,
                limit=limit,
            )
        except service.DeltaRefused as refusal:
            raise HTTPException(status_code=409, detail=[refusal.reason]) from refusal

    return DatasetDeltaPage(
        dataset_version_id=delta.dataset_version_id,
        from_dataset_version_id=delta.from_dataset_version_id,
        changed=[{str(k): str(v) for k, v in row.items()} for row in delta.changed],
        deleted=delta.deleted,
        columns=delta.columns,
        next_cursor=delta.next_cursor,
        has_more=delta.next_cursor is not None,
    )
