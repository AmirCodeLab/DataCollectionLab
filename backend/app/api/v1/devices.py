"""Device registration endpoint (specs/sync-protocol-v0.1.md §4)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.schemas import MessageError
from app.modules.media import service as media_service
from app.modules.media.schemas import MediaPolicyResponse
from app.modules.projects import service
from app.modules.projects.schemas import (
    DeviceCryptoError,
    DeviceCryptoErrorResponse,
    DeviceCryptoResponse,
    DeviceRegisterError,
    DeviceRegisterErrorResponse,
    DeviceRegisterRequest,
    DeviceRegisterResponse,
)

router = APIRouter()


@router.post(
    "",
    response_model=DeviceRegisterResponse,
    response_model_by_alias=True,
    responses={
        403: {"model": DeviceRegisterErrorResponse},
        409: {"model": DeviceRegisterErrorResponse},
    },
)
async def register(
    request: DeviceRegisterRequest, session: Annotated[AsyncSession, Depends(get_db)]
) -> DeviceRegisterResponse:
    """Register this device so its pushed ops are authorized.

    Idempotent: an already-known device gets 200 `already_registered`, so a
    client may re-register freely. A revoked device gets 403 and stays out.

    Failures carry a machine-readable `reason` (`project_not_found`,
    `project_ambiguous`, `project_mismatch`, `device_revoked`) beside a message
    saying what to do about it, so a client can report something better than
    the status code.
    """
    async with session.begin():
        try:
            return await service.register_device(session, request)
        except service.RegistrationError as error:
            raise HTTPException(
                status_code=error.status_code,
                detail=DeviceRegisterError(
                    reason=error.reason, message=error.message
                ).model_dump(),
            ) from error


@router.get(
    "/{device_id}/crypto",
    response_model=DeviceCryptoResponse,
    response_model_by_alias=True,
    responses={
        404: {"model": MessageError},
        409: {"model": DeviceCryptoErrorResponse},
    },
)
async def crypto_config(
    session: Annotated[AsyncSession, Depends(get_db)],
    device_id: Annotated[str, Path(min_length=1, max_length=64)],
) -> DeviceCryptoResponse:
    """The security mode and public project keys this device wraps content keys to.

    Clients call this on every sync, not once at registration: key rotation
    (encryption envelope §8) adds recipients, and a submission wrapped to a
    stale set is data whose intended recovery holder cannot open it.

    Public keys only. Nothing here is secret — every byte is useless without a
    private key the server has never held.

    409 `test_only_key` when the project holds a recipient whose private half is
    published (scripts/dev_project_key.py) outside a development environment.
    The device then holds its data locally rather than encrypting it to a key
    everyone has, which is the same choice it makes when a project has no keys
    at all.
    """
    async with session.begin():
        try:
            config = await service.device_crypto(session, device_id)
        except service.RecipientSetError as error:
            raise HTTPException(
                status_code=error.status_code,
                # Built from the declared model, not a bare dict: the body on
                # the wire and the body in the contract then have one author.
                detail=DeviceCryptoError(
                    reason=error.reason, message=error.message
                ).model_dump(),
            ) from error
    if config is None:
        raise HTTPException(status_code=404, detail="device not found")
    return config


@router.get(
    "/{device_id}/media-policy",
    response_model=MediaPolicyResponse,
    response_model_by_alias=True,
    responses={404: {"model": MessageError}},
)
async def media_policy(
    session: Annotated[AsyncSession, Depends(get_db)],
    device_id: Annotated[str, Path(min_length=1, max_length=64)],
) -> MediaPolicyResponse:
    """The capture settings this device must apply, and the chunk size.

    Fetched every sync and cached locally, for the same reason as the crypto
    config: a device may go two weeks without a server and has to keep capturing
    to the project's settings throughout.

    Two of the three are compression, which trades evidentiary quality against
    bandwidth — only the study knows which side it is on. The third,
    `gpsMaxAccuracyM`, is a refusal threshold rather than a preference: a phone
    indoors will report a two-kilometre "fix" with exactly the authority of a
    good one, and nothing downstream can tell them apart afterwards. The client
    refuses a worse fix rather than storing it quietly.

    404 when the device is unknown or revoked — a device the server will not
    accept data from has no business learning a project's settings either.
    """
    async with session.begin():
        policy = await media_service.device_media_policy(session, device_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="device not found")
    return policy
