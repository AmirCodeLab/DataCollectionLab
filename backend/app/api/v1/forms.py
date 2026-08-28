"""Form compilation and validation endpoints.

Phase 0 scope: compile a Form IR document and report errors and warnings.
CRUD, versioning and publishing arrive in Phase 1.
"""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.modules.form_engine.expression import CompileError
from app.modules.form_engine.runtime import CompiledForm, FormInstance

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
