"""Resumable media upload (specs/sync-protocol-v0.1.md §9).

The three calls the sync protocol specifies, and nothing more:

    POST /media/upload-sessions                   -> { uploadId, chunkSize, ... }
    PUT  /media/upload-sessions/{uploadId}/chunks/{n}
    POST /media/upload-sessions/{uploadId}/complete -> { mediaId, hash }

There is no "session status" call because the first one already is: opening a
session for a part-uploaded file returns the chunk indexes the server holds, and
the client sends the rest. A second way to ask the same question is a second
thing that can disagree with the first.

The chunk body is `application/octet-stream` — the one request body in this API
that is not a Pydantic model, because it is 4 MiB of bytes. Base64 in a JSON
envelope would cost a third more on every chunk, on exactly the connections
this exists for.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.modules.media import service
from app.modules.media.schemas import (
    MediaChunkResponse,
    MediaCompleteRequest,
    MediaCompleteResponse,
    MediaUploadError,
    MediaUploadErrorResponse,
    MediaUploadSessionRequest,
    MediaUploadSessionResponse,
)

router = APIRouter()

_ERRORS: dict[int | str, dict[str, Any]] = {
    403: {"model": MediaUploadErrorResponse},
    404: {"model": MediaUploadErrorResponse},
    409: {"model": MediaUploadErrorResponse},
    410: {"model": MediaUploadErrorResponse},
}


def _refuse(error: service.MediaError) -> HTTPException:
    """The refusal as it goes on the wire.

    Built from the declared model rather than a bare dict, so the body a client
    receives and the body the contract promises have one author.
    """
    return HTTPException(
        status_code=error.status_code,
        detail=MediaUploadError(reason=error.reason, message=error.message).model_dump(),
    )


@router.post(
    "/upload-sessions",
    response_model=MediaUploadSessionResponse,
    response_model_by_alias=True,
    responses=_ERRORS,
)
async def open_upload_session(
    request: MediaUploadSessionRequest, session: Annotated[AsyncSession, Depends(get_db)]
) -> MediaUploadSessionResponse:
    """Open, or resume, the upload of one file.

    Idempotent on `mediaId`. `receivedChunks` is the whole of resumption: the
    client skips those indexes and sends the rest, so an upload interrupted at
    90% costs 10% to finish rather than starting over — which on a 2G link is
    the difference between a photograph that arrives and one that never does.

    An encrypted file must arrive with its media key wrapped to at least one
    active project key (envelope §6). Refused otherwise: ciphertext nobody can
    open looks exactly like ciphertext somebody can, and this is the last moment
    the mistake is recoverable.

    Also 422 for a domain refusal (`unwrapped_media_key`, `unknown_recipient`)
    with a `{"detail": {"reason", "message"}}` body — the same collision with
    FastAPI's request-validation 422 that `POST /forms/compile` has, and
    documented here rather than declared for the same reason: only one body
    shape can be declared under one status.
    """
    async with session.begin():
        try:
            return await service.open_session(session, request)
        except service.MediaError as error:
            raise _refuse(error) from error


@router.put(
    "/upload-sessions/{upload_id}/chunks/{chunk_index}",
    response_model=MediaChunkResponse,
    response_model_by_alias=True,
    responses=_ERRORS,
)
async def put_chunk(
    session: Annotated[AsyncSession, Depends(get_db)],
    upload_id: Annotated[str, Path(min_length=1, max_length=64)],
    chunk_index: Annotated[int, Path(ge=0)],
    data: Annotated[bytes, Body(media_type="application/octet-stream")],
) -> MediaChunkResponse:
    """Store one 4 MiB chunk of ciphertext.

    Every chunk but the last is exactly 4 MiB, and that is fixed rather than
    negotiated (envelope §6): the nonce for chunk *n* is derived from
    `(mediaId, n)`, so two clients that disagreed about where the boundaries
    fall would encrypt different plaintext under the same nonce — the one
    failure AES-GCM does not survive.

    Idempotent. Re-sending a stored chunk succeeds: a client that lost the
    response cannot tell "stored" from "lost in transit", and making the retry
    safe is cheaper than making the client careful.

    Also 422 (`chunk_out_of_range`, `chunk_size_mismatch`) with the
    `{"detail": {"reason", "message"}}` body — see the note on
    `POST /upload-sessions`.
    """
    async with session.begin():
        try:
            return await service.put_chunk(session, upload_id, chunk_index, data)
        except service.MediaError as error:
            raise _refuse(error) from error


@router.post(
    "/upload-sessions/{upload_id}/complete",
    response_model=MediaCompleteResponse,
    response_model_by_alias=True,
    responses=_ERRORS,
)
async def complete_upload(
    session: Annotated[AsyncSession, Depends(get_db)],
    upload_id: Annotated[str, Path(min_length=1, max_length=64)],
    request: MediaCompleteRequest,
) -> MediaCompleteResponse:
    """Seal the upload: every chunk present, and the hash is what we stored.

    `hash` in the response is the server's own SHA-256 over the stored bytes,
    not an echo of the request — echoing would make the check a formality. Those
    bytes are CIPHERTEXT for an encrypted file, and the server has no key for
    them; hashing plaintext would let it confirm that two submissions contain
    the same photograph, which is the inference the mode exists to prevent
    (envelope §6).

    Also 422 (`hash_mismatch`) with the `{"detail": {"reason", "message"}}`
    body — see the note on `POST /upload-sessions`.
    """
    async with session.begin():
        try:
            return await service.complete(session, upload_id, request)
        except service.MediaError as error:
            raise _refuse(error) from error
