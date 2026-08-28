"""Sync endpoints (specs/sync-protocol-v0.1.md §4, §5).

Push and pull for the operation log. Media travels through its own upload
sessions, never inside the op stream (spec §9) — not implemented yet.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.modules.sync import service
from app.modules.sync.schemas import PullResponse, PushRequest, PushResponse

router = APIRouter()


@router.post("/push", response_model=PushResponse, response_model_by_alias=True)
async def push(
    request: PushRequest, session: Annotated[AsyncSession, Depends(get_db)]
) -> PushResponse:
    """Accept a batch of operations.

    Everything — op inserts, tombstones, state folds, outbox events — commits
    in one transaction. Replay is idempotent: an op the server already has is
    reported accepted without being written again.
    """
    async with session.begin():
        return await service.push(session, request.device_id, request.ops)


@router.get("/pull", response_model=PullResponse, response_model_by_alias=True)
async def pull(
    session: Annotated[AsyncSession, Depends(get_db)],
    cursor: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=service.MAX_PULL_LIMIT)] = service.DEFAULT_PULL_LIMIT,
    scope: Annotated[str | None, Query()] = None,
) -> PullResponse:
    """Resume the op and tombstone streams from a cursor.

    `scope` (spec §5: assignments, forms, datasets) selects additional
    resource streams; only the submission stream exists yet, so it is
    accepted and currently ignored.
    """
    del scope
    async with session.begin():
        return await service.pull(session, cursor=cursor, limit=limit)
