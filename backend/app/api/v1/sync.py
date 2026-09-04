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
    """Accept a batch of operations, and the content keys they are encrypted to.

    Everything — content keys, op inserts, tombstones, state folds, outbox
    events — commits in one transaction, so a key and the first ops it encrypts
    arrive together or not at all. Replay is idempotent: an op the server
    already has is reported accepted without being written again.
    """
    async with session.begin():
        return await service.push(session, request.device_id, request.ops, request.keys)


@router.get("/pull", response_model=PullResponse, response_model_by_alias=True)
async def pull(
    session: Annotated[AsyncSession, Depends(get_db)],
    cursor: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=service.MAX_PULL_LIMIT)] = service.DEFAULT_PULL_LIMIT,
    scope: Annotated[str | None, Query()] = None,
    device_id: Annotated[str | None, Query(alias="deviceId", max_length=64)] = None,
) -> PullResponse:
    """Resume the op and tombstone streams from a cursor, and optionally list
    the form versions this device should be running.

    `scope` is the comma-separated list of spec §5: `assignments`, `forms`,
    `datasets`. `assignments` is accepted and ignored, so a newer client asking
    for all three still works against this server rather than failing on an
    unknown word.

    `scope=datasets` returns the dataset versions the form versions deployed to
    this device were **published against** (`form_version_dataset`), not the
    datasets its project happens to own. The pinning that lets an answer be
    explained later is the same thing that decides which rows travel. Like the
    form manifest it names versions and checksums, never rows: those are fetched
    once per version, paged, from `GET /datasets/versions/{id}/rows`.

    `datasets` is **null** when nothing was asked or the device is unknown, and
    `[]` when the answer is genuinely "none" — a device must be able to tell an
    unanswered question from an answer, or it will delete a village list because
    it synced against an older server.

    `scope=forms` needs `deviceId`, because deployment is per environment
    (`form_deployment`): a device is told about the versions deployed to its own
    environment, never everything the project has published. The manifest names
    versions and their checksums, not their IR — the documents are fetched one
    at a time from `GET /forms/versions/{formVersionId}`, so a device that
    already holds a version spends nothing re-reading it.

    Unlike the op stream, the manifest is a complete statement rather than a
    delta: it is how a device notices a version has been *withdrawn*, which no
    stream of additions could tell it.
    """
    wanted = {part.strip() for part in (scope or "").split(",") if part.strip()}
    async with session.begin():
        return await service.pull(
            session,
            cursor=cursor,
            limit=limit,
            device_id=device_id,
            want_forms="forms" in wanted,
            want_datasets="datasets" in wanted,
        )
