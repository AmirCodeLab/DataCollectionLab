"""Device registration endpoint (specs/sync-protocol-v0.1.md §4)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.modules.projects import service
from app.modules.projects.schemas import DeviceRegisterRequest, DeviceRegisterResponse

router = APIRouter()


@router.post("", response_model=DeviceRegisterResponse, response_model_by_alias=True)
async def register(
    request: DeviceRegisterRequest, session: Annotated[AsyncSession, Depends(get_db)]
) -> DeviceRegisterResponse:
    """Register this device so its pushed ops are authorized.

    Idempotent: an already-known device gets 200 `already_registered`, so a
    client may re-register freely. A revoked device gets 403 and stays out.
    """
    async with session.begin():
        try:
            return await service.register_device(session, request)
        except service.RegistrationError as error:
            raise HTTPException(status_code=error.status_code, detail=error.reason) from error
