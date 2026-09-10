"""Supervisor monitoring (item 5).

Four reads, one permission, and no writes. Every figure is a count over the
same table its list route reads, on this request's connection under this
request's principal — so a supervisor's dashboard and a supervisor's list are
the same answer, and neither can quietly summarise rows the other hides.

`submission.view` gates all of them: it is the permission a supervisor already
holds and the one that already means "may see work". Nothing here widens what
a person may see; it only counts it.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import Identity, access
from app.api.deps import get_db
from app.modules.monitoring import service
from app.modules.monitoring.schemas import (
    AreaListResponse,
    DeviceListResponse,
    EnumeratorListResponse,
    Overview,
)

router = APIRouter()

VIEW = access(permission="submission.view")


@router.get("/overview", response_model=Overview, response_model_by_alias=True)
async def overview(
    session: Annotated[AsyncSession, Depends(get_db)],
    identity: Annotated[Identity, Depends(VIEW)],
    project_id: Annotated[str, Query(alias="projectId", min_length=1, max_length=64)],
) -> Overview:
    """The figures, each carrying whose scope produced it.

    `flagsOutstanding` is null when no quality rule exists for the project.
    That is not an error and not a zero: nothing can raise a flag yet (item 6
    brings the evaluator), and a zero would be an empty table rendered as a
    measurement.
    """
    async with session.begin():
        return await service.overview(session, project_id, identity.principal)


@router.get(
    "/enumerators", response_model=EnumeratorListResponse, response_model_by_alias=True
)
async def enumerators(
    session: Annotated[AsyncSession, Depends(get_db)],
    identity: Annotated[Identity, Depends(VIEW)],
    project_id: Annotated[str, Query(alias="projectId", min_length=1, max_length=64)],
) -> EnumeratorListResponse:
    """Progress per person, over the people this principal may see."""
    async with session.begin():
        return await service.enumerators(session, project_id)


@router.get("/areas", response_model=AreaListResponse, response_model_by_alias=True)
async def areas(
    session: Annotated[AsyncSession, Depends(get_db)],
    identity: Annotated[Identity, Depends(VIEW)],
    project_id: Annotated[str, Query(alias="projectId", min_length=1, max_length=64)],
) -> AreaListResponse:
    """Progress grouped by the sample's area column.

    A supervisor's row for an area is their slice of it, and the response says
    which column "area" meant so nobody has to guess.
    """
    async with session.begin():
        return await service.areas(session, project_id)


@router.get("/devices", response_model=DeviceListResponse, response_model_by_alias=True)
async def devices(
    session: Annotated[AsyncSession, Depends(get_db)],
    identity: Annotated[Identity, Depends(VIEW)],
    project_id: Annotated[str, Query(alias="projectId", min_length=1, max_length=64)],
) -> DeviceListResponse:
    """The handsets in scope, with each one's last sync and last reported backlog.

    `reportedPendingOps` is the device's own count and `reportedAt` is when it
    said so. They travel together because they mean nothing apart: "3 pending"
    is a claim with no date on it, and a supervisor reads it at four in the
    afternoon as though it were now.
    """
    async with session.begin():
        return await service.devices(session, project_id)
