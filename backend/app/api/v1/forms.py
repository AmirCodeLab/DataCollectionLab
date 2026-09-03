"""Form listing, compilation, validation and publishing endpoints.

Compiling and publishing run the same gate (`service.check_publishable`), so
what the builder is told about a form is what publishing will actually do with
it.

Publishing and deploying are separate: publishing stores an immutable version,
deploying says an environment should run it, and only the second reaches a
device. `POST /versions` can do both in one call; retiring a deployment has no
endpoint yet (docs/known-defects.md).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Path, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.schemas import MessageError
from app.modules.form_engine.expression import CompileError
from app.modules.form_engine.runtime import CompiledForm, FormInstance
from app.modules.forms import service
from app.modules.forms.schemas import (
    CompileRequest,
    CompileResponse,
    EvaluateRequest,
    EvaluateResponse,
    FieldSnapshot,
    FormListResponse,
    FormVersionDocument,
    ImportCoverage,
    ImportDataset,
    ImportDiagnostic,
    ImportFormResponse,
    ImportInstrumentation,
    ImportSummary,
    PublishVersionRequest,
    PublishVersionResponse,
)
from app.modules.forms.xlsform.datatypes import SpecsUnavailable
from app.modules.forms.xlsform.importer import CoverageHole, ImportFailed, import_workbook
from app.modules.forms.xlsform.report import render_markdown

router = APIRouter()


@router.get("", response_model=FormListResponse, response_model_by_alias=True)
async def list_forms(
    session: Annotated[AsyncSession, Depends(get_db)],
    include_archived: Annotated[bool, Query(alias="includeArchived")] = False,
) -> FormListResponse:
    """Every form and its version numbers — enough to name and filter by one."""
    async with session.begin():
        return await service.list_forms(session, include_archived=include_archived)


@router.post("/compile", response_model=CompileResponse, response_model_by_alias=True)
async def compile_form(request: CompileRequest) -> CompileResponse:
    """Compile a Form IR document and report what would block publishing it.

    Runs every Form IR §10 error check, sensitivity propagation included, so a
    builder learns about a leak while editing rather than at publish time.

    A form that does not compile, or that §10 refuses, is a 422 whose `detail`
    lists the violations — a different body from the 422 FastAPI returns when
    the request itself does not match the schema. Only the second is described
    below; see the note in `app/api/schemas.py` about why.
    """
    try:
        compiled = service.check_publishable(request.form)
    except CompileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except service.PublishRefused as exc:
        raise HTTPException(status_code=422, detail=exc.violations) from exc
    return CompileResponse(
        form_id=compiled.form_id,
        version=compiled.version,
        field_count=len(compiled.fields),
        evaluation_order=compiled.topo_order,
        warnings=compiled.warnings,
    )



@router.post(
    "/import",
    response_model=ImportFormResponse,
    response_model_by_alias=True,
    responses={400: {"model": MessageError}, 500: {"model": MessageError}},
    description=(
        "Import an XLSForm .xlsx and return the Form IR with a full account of "
        "everything that did not survive.\n\n"
        "The form is returned even when it cannot be published — an author needs "
        "every problem in one pass, not one per round trip. `publishable` is "
        "false when any diagnostic is an error; publishing is refused "
        "server-side as well, so the flag is for greying a button rather than "
        "being the gate.\n\n"
        "`datasets` carries the companion CSVs a `select_one_from_file` names "
        "(Form IR §3). They ship beside the workbook rather than inside it, so "
        "they have to be uploaded alongside: a form imported without them "
        "reports each missing file by name, because a question whose list did "
        "not arrive has no options at all and looks exactly like one that "
        "does. Send every CSV you have — a file nothing refers to is reported "
        "too, which is how a rename on one side of the pair gets noticed.\n\n"
        "Nothing is stored. This endpoint answers 'what would this become?'; "
        "POST /projects/{projectId}/datasets and POST /forms/versions are what "
        "commit it."
    ),
)
async def import_xlsform(
    file: Annotated[UploadFile, File(description="An XLSForm .xlsx workbook")],
    datasets: Annotated[
        list[UploadFile],
        File(description="Companion .csv files named by select_one_from_file rows"),
    ] = [],  # noqa: B006  - FastAPI reads the default to make the field optional
) -> ImportFormResponse:
    """Turn a spreadsheet and its companion files into a form, and say what was
    lost doing it."""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="the uploaded file is empty")

    companions: dict[str, bytes] = {}
    for companion in datasets:
        name = (companion.filename or "").strip()
        if not name:
            # A part with no filename cannot be matched against a survey row,
            # and guessing which one it is would be worse than refusing.
            raise HTTPException(
                status_code=400,
                detail="a companion file was uploaded with no filename, so there is "
                "no way to tell which `select_one_from_file` row it answers",
            )
        if name in companions:
            raise HTTPException(
                status_code=400,
                detail=f"`{name}` was uploaded more than once; only one of them can "
                "be the list this form means",
            )
        companions[name] = await companion.read()

    try:
        result = import_workbook(data, companions=companions)
    except ImportFailed as failure:
        # Not a diagnostic: a diagnostic is something *about* a form, and this
        # is the absence of one. There is no row to point at.
        raise HTTPException(status_code=400, detail=str(failure)) from failure
    except SpecsUnavailable as failure:
        # The importer cannot say which question types a device can collect, so
        # it refuses rather than guessing — both defaults are a lie an author
        # would act on. See xlsform/datatypes.py.
        raise HTTPException(status_code=500, detail=str(failure)) from failure
    except CoverageHole as failure:
        # A cell produced nothing and was never reported. That is an importer
        # bug, and returning a form that quietly lost something is the exact
        # failure the coverage ledger exists to prevent.
        raise HTTPException(status_code=500, detail=str(failure)) from failure

    counts = {
        severity: sum(1 for d in result.diagnostics if d.severity == severity)
        for severity in ("error", "warning", "info")
    }
    return ImportFormResponse(
        publishable=result.publishable,
        form=result.form,
        summary=ImportSummary(
            questions=result.questions,
            nodes=result.nodes,
            survey_rows=result.survey_rows,
            languages=result.languages,
            errors=counts["error"],
            warnings=counts["warning"],
            notes=counts["info"],
        ),
        diagnostics=[
            ImportDiagnostic(
                severity=d.severity,
                code=d.code,
                message=d.message,
                sheet=d.ref.sheet if d.ref else None,
                row=d.ref.row if d.ref else None,
                column=d.ref.column if d.ref else None,
                cell_value=d.cell_value,
                node_id=d.node_id,
                remedy=d.remedy,
            )
            for d in result.diagnostics
        ],
        coverage=ImportCoverage(**result.coverage),
        datasets=[
            ImportDataset(
                key=d.key,
                file_name=d.file_name,
                row_count=d.row_count,
                columns=d.columns,
                value_column=d.value_column,
                label_columns=d.label_columns,
                columns_used=d.columns_used,
                used_by=d.used_by,
                checksum=d.checksum,
                encoding=d.encoding,
            )
            for d in result.datasets
        ],
        instrumentation=ImportInstrumentation(
            unsupported_functions=result.instrumentation.unsupported_functions,
            unsupported_types=result.instrumentation.unsupported_types,
            uncollectable_types=result.instrumentation.uncollectable_types,
        ),
        report_markdown=render_markdown(
            result, source_name=file.filename or "workbook.xlsx", form_id=result.form["formId"]
        ),
    )


@router.post("/evaluate", response_model=EvaluateResponse, response_model_by_alias=True)
async def evaluate_form(request: EvaluateRequest) -> EvaluateResponse:
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
    return EvaluateResponse(
        valid=instance.is_valid,
        # Field by field rather than relaying `snapshot()` as an opaque dict.
        # The engine's `to_dict` is its own business and may grow fields for
        # its own reasons; what this endpoint promises is the seven below, and
        # writing them out is what makes that a promise rather than a habit.
        fields={
            path: FieldSnapshot(
                path=state["path"],
                relevant=state["relevant"],
                required=state["required"],
                read_only=state["readOnly"],
                value=state["value"],
                valid=state["valid"],
                errors=state["errors"],
            )
            for path, state in instance.snapshot().items()
        },
        answers=instance.answers(),
    )


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

    `deployTo` deploys the version to the named environments in the same call.
    Publishing without it is legitimate — the version exists and nothing runs
    it — but it reaches no device, so the response reports `deployments` either
    way rather than letting "published" be read as "on the phones".

    `datasets` pins each `choices.dataset` key (Form IR §3) to the dataset
    version this form was published against, from
    `POST /projects/{projectId}/datasets`. Every key the form names must be
    pinned and no key it does not name may be: an unpinned key would have to
    resolve at read time, against whatever is newest, which is the same mistake
    as validating a v1 answer against v2's choice list.
    """
    async with session.begin():
        try:
            return await service.publish_version(
                session,
                project_id=request.project_id,
                ir=request.form,
                title=request.title,
                published_by=request.published_by,
                deploy_to=request.deploy_to,
                import_record=request.import_record,
                datasets=request.datasets,
            )
        except CompileError as exc:
            raise HTTPException(status_code=422, detail=[str(exc)]) from exc
        except service.PublishRefused as exc:
            raise HTTPException(status_code=422, detail=exc.violations) from exc


@router.get(
    "/versions/{form_version_id}",
    response_model=FormVersionDocument,
    response_model_by_alias=True,
    responses={404: {"model": MessageError}},
)
async def get_form_version(
    session: Annotated[AsyncSession, Depends(get_db)],
    form_version_id: Annotated[str, Path(min_length=1, max_length=64)],
) -> FormVersionDocument:
    """One published version and its Form IR.

    The second half of form delivery (sync §5). `GET /sync/pull?scope=forms`
    tells a device which versions its environment runs and what they hash to;
    this hands over a document the device does not already hold. Splitting the
    two is what keeps a sync cheap: the manifest is a few hundred bytes and
    travels on every pull, the IR is tens of kilobytes and travels once.

    A published version is immutable (specs/erd-v0.1.md §4), so the response for
    a given id can never change and a client may cache it forever.
    """
    async with session.begin():
        document = await service.get_form_version(session, form_version_id)
    if document is None:
        raise HTTPException(status_code=404, detail="form version not found")
    return document
