"""Form listing, compilation and validation endpoints.

Phase 0 scope: list the published forms, and compile a Form IR document
reporting errors and warnings. CRUD, versioning and publishing arrive in
Phase 1.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.modules.form_engine.expression import CompileError
from app.modules.form_engine.runtime import CompiledForm, FormInstance
from app.modules.forms import service
from app.modules.forms.schemas import FormListResponse

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
    try:
        compiled = CompiledForm(request.form)
    except CompileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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
