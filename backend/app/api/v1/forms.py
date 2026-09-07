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
from app.modules.form_engine.reachability import never_shown_questions
from app.modules.form_engine.runtime import CompiledForm, FormInstance
from app.modules.form_engine.screens import FormScreen, build_screen_plan
from app.modules.forms import service
from app.modules.forms.expression_text import RenderError, render
from app.modules.forms.expression_text import parse as parse_expression
from app.modules.forms.models import FormDraft
from app.modules.forms.schemas import (
    CompileRequest,
    CompileResponse,
    CreateFormRequest,
    DraftDocument,
    EvaluateRequest,
    EvaluateResponse,
    ExpressionRequest,
    ExpressionResponse,
    FieldSnapshot,
    FormListResponse,
    FormSummary,
    FormVersionDocument,
    ImportCoverage,
    ImportDataset,
    ImportDiagnostic,
    ImportFormResponse,
    ImportInstrumentation,
    ImportSummary,
    PaletteResponse,
    PaletteType,
    PublishVersionRequest,
    PublishVersionResponse,
    SaveDraftRequest,
    ScreenSummary,
    TestCase,
)
from app.modules.forms.xlsform import datatypes
from app.modules.forms.xlsform.datatypes import SpecsUnavailable
from app.modules.forms.xlsform.expressions import ExpressionError
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


@router.post(
    "",
    response_model=FormSummary,
    response_model_by_alias=True,
    status_code=201,
    responses={409: {"model": MessageError}},
)
async def create_form(
    request: CreateFormRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> FormSummary:
    """A form with nothing published yet, so the builder has somewhere to start.

    Creates the `form` row and **no version**. A draft is saved against it
    with `PUT /forms/{id}/draft`, and a version comes only from
    `POST /forms/versions`, exactly as for an imported form.
    """
    async with session.begin():
        try:
            return await service.create_form(
                session,
                project_id=request.project_id,
                form_key=request.form_id,
                title=request.title,
            )
        except service.FormExists as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/{form_id}/draft",
    response_model=DraftDocument,
    response_model_by_alias=True,
    responses={404: {"model": MessageError}},
)
async def get_draft(
    form_id: Annotated[str, Path(min_length=1, max_length=64)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> DraftDocument:
    """The unpublished IR for a form, if anything is being edited."""
    async with session.begin():
        draft = await service.get_draft(session, form_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="no draft for this form")
        return _draft(draft)


@router.put(
    "/{form_id}/draft",
    response_model=DraftDocument,
    response_model_by_alias=True,
    responses={409: {"model": MessageError}},
)
async def save_draft(
    form_id: Annotated[str, Path(min_length=1, max_length=64)],
    request: SaveDraftRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> DraftDocument:
    """Create or replace a form's draft.

    **Saving does not publish and cannot.** A draft has no version number and
    no checksum to carry into `form_version`; publishing is
    `POST /forms/versions`, which compiles and runs every §10 check. Form IR
    §2.3 is the reason there is one route to a published version and not two.

    The IR is not validated here. A draft is allowed to be a form that does not
    compile — that is most of what editing one is — and
    `POST /forms/compile` is how an author finds out without the draft refusing
    to hold their work meanwhile.
    """
    async with session.begin():
        try:
            draft = await service.save_draft(
                session,
                form_id=form_id,
                ir=request.ir,
                expected_revision=request.expected_revision,
                updated_by=request.updated_by,
                test_cases=(
                    None
                    if request.test_cases is None
                    else [case.model_dump(by_alias=True) for case in request.test_cases]
                ),
            )
        except service.DraftConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _draft(draft)


def _draft(draft: FormDraft) -> DraftDocument:
    return DraftDocument(
        form_id=draft.form_id,
        ir=draft.ir,
        revision=draft.revision,
        updated_at=draft.updated_at,
        updated_by=draft.updated_by,
        test_cases=[TestCase.model_validate(case) for case in draft.test_cases],
    )


@router.post(
    "/expressions",
    response_model=ExpressionResponse,
    response_model_by_alias=True,
)
async def expressions(request: ExpressionRequest) -> ExpressionResponse:
    """Surface text to a §4.1 AST, or an AST back to text (Appendix A).

    One implementation, server-side, and that is the decision rather than a
    convenience. §2.1 of the builder scope says no form logic lives in the
    builder, and a parser in the console is form logic in the builder — a
    second thing that decides what an expression means, in a second language,
    which is the shape this repository keeps paying for.

    **This is not a conformance surface.** Both engines consume AST and neither
    parses text, so there is nothing here for a vector to compare between two
    implementations: only one exists by construction. What replaces a vector is
    a round trip — `parse(render(node)) == node` over every expression in the
    corpus, in `tests/test_expression_text.py`.

    A bad expression is a 200 carrying `error` and `offset`, not a 422. The
    code field asks on every pause in typing, and most of what it sends is
    half-written by definition; an error status for "the author has not
    finished the sentence" would make the normal case look like a failure.
    """
    if request.expression is not None:
        try:
            return ExpressionResponse(
                expression=request.expression, text=render(request.expression)
            )
        except RenderError as exc:
            return ExpressionResponse(expression=request.expression, error=str(exc))

    if request.text is None:
        return ExpressionResponse(error="send either `text` or `expression`")

    try:
        node = parse_expression(
            request.text, self_path=request.self_path, row_scope=request.row_scope
        )
    except ExpressionError as exc:
        return ExpressionResponse(error=str(exc), offset=exc.offset)
    # Rendered back as well, so the field can show the canonical form of what
    # it just read — the same string the next load would produce.
    try:
        text = render(node)
    except RenderError:
        text = None
    return ExpressionResponse(expression=node, text=text)


@router.get("/palette", response_model=PaletteResponse, response_model_by_alias=True)
async def palette() -> PaletteResponse:
    """Every dataType the IR defines, and whether a client can present it.

    Served from `specs/collectable-types-v0.1.json` and the Form IR spec's §2.1
    table, so a console never carries its own copy. A hand-written palette is
    the drift the registry exists to prevent, and it fails in the direction
    that hurts: a type the console offers and no client can render is defect 7,
    published.
    """
    try:
        collectable = datatypes.collectable_types()
        all_types = datatypes.spec_data_types()
        notes = datatypes.collectable_types_notes()
        sources = datatypes.collectable_choice_sources()
        version = datatypes.collectable_types_version()
    except SpecsUnavailable as exc:
        # The specs directory is a deployment fact, not a request fact.
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return PaletteResponse(
        version=version,
        types=[
            PaletteType(
                data_type=name,
                status="collectable" if name in collectable else "in_spec_only",
                note=notes.get(name),
            )
            for name in sorted(all_types)
        ],
        choice_sources=[
            PaletteType(
                data_type=kind,
                status="collectable" if kind in sources else "in_spec_only",
                note=notes.get(f"{kind} choices"),
            )
            for kind in sorted({"inline", "dataset"} | set(sources))
        ],
    )


def _screen(screen: FormScreen) -> ScreenSummary:
    """A plan screen as the console reads it.

    The plan comes from `build_screen_plan`, the same function both engines
    implement and the vectors compare — never rebuilt here. §11.1's partition
    is one thing or it is three.
    """
    return ScreenSummary(
        index=screen.index,
        kind=screen.kind,
        question_ids=list(screen.question_ids),
        repeat_id=screen.repeat_id,
        group_id=screen.group_id,
        section_id=screen.section_id,
    )


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
    plan = build_screen_plan(request.form)
    return CompileResponse(
        form_id=compiled.form_id,
        version=compiled.version,
        field_count=len(compiled.fields),
        evaluation_order=compiled.topo_order,
        warnings=compiled.warnings,
        never_shown=never_shown_questions(request.form),
        screens=[_screen(s) for s in plan.screens],
        instance_plans={
            repeat_id: [_screen(s) for s in screens]
            for repeat_id, screens in plan.instance_plans.items()
        },
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
