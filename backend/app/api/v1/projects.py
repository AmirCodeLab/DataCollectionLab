"""Projects and their encryption recipient keys (envelope §4.1, §4.3).

The keypair is generated in the browser and the private half is downloaded by
the user; only the public key is ever sent here. There is deliberately no
endpoint that generates a keypair server-side — the server would hold the
private key at the moment of creation, and `project_e2e` would be a promise the
architecture could not keep.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.modules.projects import service
from app.modules.projects.schemas import (
    ProjectKeyCreate,
    ProjectKeyDetail,
    ProjectKeyListResponse,
    ProjectListResponse,
)

router = APIRouter()


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
                detail={"reason": error.reason, "message": error.message},
            ) from error
