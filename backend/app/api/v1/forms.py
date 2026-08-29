"""Form listing, compilation, validation and publishing endpoints.

Compiling and publishing run the same gate (`service.check_publishable`), so
what the builder is told about a form is what publishing will actually do with
it. Deployment to environments is still to come.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.modules.form_engine.expression import CompileError
from app.modules.form_engine.runtime import CompiledForm, FormInstance
from app.modules.forms import service
from app.modules.forms.schemas import (
    FormListResponse,
    PublishVersionRequest,
    PublishVersionResponse,
)

router = APIRouter()


class CompileRequest(BaseModel):
    form: dict[str, Any]


class CompileResponse(BaseModel):
    formId: str
    version: int
    fieldCount: int
    evaluationOrder: list[str]
    warnings: list[str]


class EvaluateRequest(BaseModel):
    form: dict[str, Any]
    answers: dict[str, Any] = {}


@router.get("", response_model=FormListResponse, response_model_by_alias=True)
async def list_forms(
    session: Annotated[AsyncSession, Depends(get_db)],
    include_archived: Annotated[bool, Query(alias="includeArchived")] = False,
) -> FormListResponse:
    """Every form and its version numbers — enough to name and filter by one."""
    async with session.begin():
        return await service.list_forms(session, include_archived=include_archived)


@router.post("/compile", response_model=CompileResponse)
async def compile_form(request: CompileRequest) -> CompileResponse:
    """Compile a Form IR document and report what would block publishing it.

    Runs every Form IR §10 error check, sensitivity propagation included, so a
    builder learns about a leak while editing rather than at publish time.
    """
    try:
        compiled = service.check_publishable(request.form)
    except CompileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except service.PublishRefused as exc:
        raise HTTPException(status_code=422, detail=exc.violations) from exc
    return CompileResponse(
        formId=compiled.form_id,
        version=compiled.version,
        fieldCount=len(compiled.fields),
        evaluationOrder=compiled.topo_order,
        warnings=compiled.warnings,
    )


@router.post("/evaluate")
async def evaluate_form(request: EvaluateRequest) -> dict[str, Any]:
    """Server-side evaluation of a form state.

    NOTE: this is the reference implementation. Decision O-2 (JVM engine
    sidecar vs Python port) determines whether this stays the production path.
    """
    try:
        compiled = CompiledForm(request.form)
        instance = FormInstance(compiled)
        instance.set_many(request.answers)
    except CompileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "valid": instance.is_valid,
        "fields": instance.snapshot(),
        "answers": instance.answers(),
    }


@router.post(
    "/versions",
    response_model=PublishVersionResponse,
    response_model_by_alias=True,
    status_code=201,
)
async def publish_version(
    request: PublishVersionRequest, session: Annotated[AsyncSession, Depends(get_db)]
) -> PublishVersionResponse:
    """Publish an immutable form version.

    Refuses anything Form IR §10 calls an error, including a sensitivity leak —
    a field that is not `sensitive` reading one that is, which would let a
    derived value disclose an encrypted answer (encryption envelope §5.2). The
    422 body lists every violation, so a form author fixes them in one pass.

    Idempotent by content: re-publishing identical IR returns the existing row.
    Re-publishing a version number with different content is refused, because a
    device in the field has that exact IR compiled into submissions it has not
    synced yet.
    """
    async with session.begin():
        try:
            return await service.publish_version(
                session,
                project_id=request.project_id,
                ir=request.form,
                title=request.title,
                published_by=request.published_by,
            )
        except CompileError as exc:
            raise HTTPException(status_code=422, detail=[str(exc)]) from exc
        except service.PublishRefused as exc:
            raise HTTPException(status_code=422, detail=exc.violations) from exc
