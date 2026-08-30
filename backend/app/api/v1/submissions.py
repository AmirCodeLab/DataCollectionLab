"""Submission read endpoints — the console's view of the op log.

Public API, same as every other route here: the console has no private
endpoints (docs/project-conventions.md rule 9). Read-only; a submission changes only by ops
arriving through /sync/push.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.schemas import MessageError
from app.modules.media import service as media_service
from app.modules.media.schemas import SubmissionMediaResponse
from app.modules.submissions import service
from app.modules.submissions.schemas import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    SubmissionDetail,
    SubmissionKeysResponse,
    SubmissionListResponse,
    SubmissionStatus,
)

router = APIRouter()


@router.get("", response_model=SubmissionListResponse, response_model_by_alias=True)
async def list_submissions(
    session: Annotated[AsyncSession, Depends(get_db)],
    form_id: Annotated[str | None, Query(alias="formId")] = None,
    status: Annotated[SubmissionStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SubmissionListResponse:
    """One page of submissions, newest arrival first.

    `formId` is the wire form key an op carries, not the form row id, so the
    same value filters here and identifies a form in a pushed op. An unknown
    `status` is a 422 rather than an empty page — a typo should say so.
    """
    async with session.begin():
        return await service.list_submissions(
            session, form_id=form_id, status=status, limit=limit, offset=offset
        )


@router.get(
    "/{submission_id}",
    response_model=SubmissionDetail,
    response_model_by_alias=True,
    responses={404: {"model": MessageError}},
)
async def get_submission(
    session: Annotated[AsyncSession, Depends(get_db)],
    submission_id: Annotated[str, Path(min_length=1, max_length=64)],
) -> SubmissionDetail:
    """Folded current state plus the raw op log in (counter, deviceId) order."""
    async with session.begin():
        detail = await service.get_submission(session, submission_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="submission not found")
    return detail


@router.get(
    "/{submission_id}/keys",
    response_model=SubmissionKeysResponse,
    response_model_by_alias=True,
    responses={404: {"model": MessageError}},
)
async def get_submission_keys(
    session: Annotated[AsyncSession, Depends(get_db)],
    submission_id: Annotated[str, Path(min_length=1, max_length=64)],
) -> SubmissionKeysResponse:
    """The wrapped content keys a key holder needs to decrypt this submission.

    Wrapped copies only, exactly as they were uploaded. Decryption happens in
    the browser or the desktop app with a private key the server has never held
    (encryption envelope §7) — the console is not a key holder.
    """
    async with session.begin():
        keys = await service.get_submission_keys(session, submission_id)
    if keys is None:
        raise HTTPException(status_code=404, detail="submission not found")
    return keys


@router.get(
    "/{submission_id}/media",
    response_model=SubmissionMediaResponse,
    response_model_by_alias=True,
    responses={404: {"model": MessageError}},
)
async def get_submission_media(
    session: Annotated[AsyncSession, Depends(get_db)],
    submission_id: Annotated[str, Path(min_length=1, max_length=64)],
) -> SubmissionMediaResponse:
    """Every file this submission references, and whether each has paired up.

    Media never travels inside the op stream (sync §9): the op carries a
    `mediaId` and the file arrives separately, in either order. So a submission
    can be complete in every answer and still be waiting for three photographs,
    and this is where that shows. `resolved` is true only when both halves are
    here — the file is `complete` and an op referencing it has arrived — and
    `pendingCount` is how many are not, so the console can say "still uploading"
    instead of rendering a submission that looks finished and is not.

    For an encrypted file the wrapped media keys come back too, exactly as they
    were uploaded. The server has never held a private key that opens one, and
    handing them out is what makes decryption possible at all (envelope §7).
    """
    async with session.begin():
        found = await media_service.submission_media(session, submission_id)
    if found is None:
        raise HTTPException(status_code=404, detail="submission not found")
    return found
