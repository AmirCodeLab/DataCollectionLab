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
from app.modules.entities.schemas import DatasetRowsPage

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
