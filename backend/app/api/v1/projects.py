"""Projects and their encryption recipient keys (envelope §4.1, §4.3).

The keypair is generated in the browser and the private half is downloaded by
the user; only the public key is ever sent here. There is deliberately no
endpoint that generates a keypair server-side — the server would hold the
private key at the moment of creation, and `project_e2e` would be a promise the
architecture could not keep.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.schemas import MessageError
from app.modules.media import service as media_service
from app.modules.media.schemas import MediaPolicyResponse, MediaPolicyUpdate
from app.modules.projects import service
from app.modules.projects.schemas import (
    ProjectKeyCreate,
    ProjectKeyDetail,
    ProjectKeyError,
    ProjectKeyErrorResponse,
    ProjectKeyListResponse,
    ProjectListResponse,
)

router = APIRouter()

# 404, 409 and 422 from the key endpoints all carry the same reasoned body.
# 422 is shared with FastAPI's own request-validation failure, which has a
# different shape; only one of the two can be declared under one status, and
# the framework's is the one a client meets first (see app/api/schemas.py).
_KEY_ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": ProjectKeyErrorResponse},
    409: {"model": ProjectKeyErrorResponse},
}


@router.get("", response_model=ProjectListResponse, response_model_by_alias=True)
async def list_projects(
    session: Annotated[AsyncSession, Depends(get_db)],
    include_archived: Annotated[bool, Query(alias="includeArchived")] = False,
) -> ProjectListResponse:
    """Every project, its security mode, and how many recipient keys it has.

    The key count is the operational fact: a project in an encrypting mode with
    zero active keys cannot receive data at all, because its devices refuse to
    push rather than send answers in the clear.
    """
    async with session.begin():
        return await service.list_projects(session, include_archived=include_archived)


@router.get(
    "/{project_id}/keys",
    response_model=ProjectKeyListResponse,
    response_model_by_alias=True,
    responses={404: {"model": MessageError}},
)
async def list_project_keys(
    session: Annotated[AsyncSession, Depends(get_db)],
    project_id: Annotated[str, Path(min_length=1, max_length=64)],
    include_revoked: Annotated[bool, Query(alias="includeRevoked")] = False,
) -> ProjectKeyListResponse:
    """The project's recipient keys — public halves only.

    Nothing here is secret. Every byte is useless without a private key the
    server has never held, which is what makes the mode worth having.
    """
    async with session.begin():
        keys = await service.list_project_keys(
            session, project_id, include_revoked=include_revoked
        )
    if keys is None:
        raise HTTPException(status_code=404, detail="project not found")
    return keys


@router.post(
    "/{project_id}/keys",
    response_model=ProjectKeyDetail,
    response_model_by_alias=True,
    status_code=201,
    responses=_KEY_ERRORS,
)
async def add_project_key(
    request: ProjectKeyCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
    project_id: Annotated[str, Path(min_length=1, max_length=64)],
) -> ProjectKeyDetail:
    """Register a public key as a recipient for this project's submissions.

    Accepts a raw 32-byte X25519 public key, a role and a label, and nothing
    else: the request model forbids unknown fields, so a client that sends a
    private key under any name gets a 422 naming the field rather than a 201 and
    a secret sitting in a request log.

    Refuses a small-order point, which would make every wrap openable by anyone
    while looking like redundancy, and refuses a public key the project already
    holds, because a second copy of one key is not a second recipient (§4.3).
    """
    async with session.begin():
        try:
            return await service.add_project_key(session, project_id, request)
        except service.KeyRegistrationError as error:
            raise HTTPException(
                status_code=error.status_code,
                # Built from the declared model, not a bare dict, so the body
                # on the wire and the body in the contract have one author.
                detail=ProjectKeyError(
                    reason=error.reason, message=error.message
                ).model_dump(),
            ) from error


@router.post(
    "/{project_id}/keys/{key_id}/revoke",
    response_model=ProjectKeyDetail,
    response_model_by_alias=True,
    responses=_KEY_ERRORS,
)
async def revoke_project_key(
    session: Annotated[AsyncSession, Depends(get_db)],
    project_id: Annotated[str, Path(min_length=1, max_length=64)],
    key_id: Annotated[str, Path(min_length=1, max_length=64)],
) -> ProjectKeyDetail:
    """Retire a recipient key (encryption envelope §8).

    A POST rather than a DELETE, because nothing is deleted. The row stays and
    the wraps that name it stay: submissions collected while this key was active
    are still encrypted to it and always will be, and the console needs the row
    to say whose private key opens them. What changes is the future — no new
    submission is wrapped to it, and devices stop being offered it.

    Refuses to retire the last active recipient of an encrypting project, which
    would stop collection in the field without telling anyone. Idempotent: a
    second revoke returns the first one's timestamp rather than moving it.
    """
    async with session.begin():
        try:
            return await service.revoke_project_key(session, project_id, key_id)
        except service.KeyRegistrationError as error:
            raise HTTPException(
                status_code=error.status_code,
                # Built from the declared model, not a bare dict, so the body
                # on the wire and the body in the contract have one author.
                detail=ProjectKeyError(
                    reason=error.reason, message=error.message
                ).model_dump(),
            ) from error


@router.get(
    "/{project_id}/media-policy",
    response_model=MediaPolicyResponse,
    response_model_by_alias=True,
    responses={404: {"model": MessageError}},
)
async def get_media_policy(
    session: Annotated[AsyncSession, Depends(get_db)],
    project_id: Annotated[str, Path(min_length=1, max_length=64)],
) -> MediaPolicyResponse:
    """This project's capture settings. Devices read them from
    `GET /devices/{deviceId}/media-policy`; this is the console's view of the
    same three numbers."""
    async with session.begin():
        policy = await media_service.project_media_policy(session, project_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="project not found")
    return policy


@router.patch(
    "/{project_id}/media-policy",
    response_model=MediaPolicyResponse,
    response_model_by_alias=True,
    responses={404: {"model": MessageError}},
)
async def set_media_policy(
    session: Annotated[AsyncSession, Depends(get_db)],
    project_id: Annotated[str, Path(min_length=1, max_length=64)],
    update: MediaPolicyUpdate,
) -> MediaPolicyResponse:
    """Change the capture settings. Omitted fields are left alone.

    Takes effect on each device at its next sync, and is not retroactive — nor
    meant to be. A photograph already captured at 1600px is the evidence that
    exists; re-compressing history would be inventing a different one.

    Lowering `gpsMaxAccuracyM` tightens what devices will accept from then on.
    Points already collected under the old threshold keep the accuracy they were
    recorded with, which is why the reading is stored beside every point rather
    than being checked and discarded.
    """
    async with session.begin():
        policy = await media_service.update_media_policy(session, project_id, update)
    if policy is None:
        raise HTTPException(status_code=404, detail="project not found")
    return policy
