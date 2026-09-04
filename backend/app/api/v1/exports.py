"""Downloading an export.

The console has no private endpoints (docs/project-conventions.md rule 9), so the route the
console will use is this one, and `scripts/export_submissions.py` runs the same
exporter in the same process for a self-hosted install.

**The response is a zip, and it is the one 2xx body in this API that is not
JSON.** `test_openapi_contract.py::test_every_success_response_names_a_schema`
requires a `$ref` under `application/json` for every success response, and it is
right to: a route whose body FastAPI had to infer publishes an object with no
fields, which type-checks in the console and describes nothing. The exemption
this route needs is the narrow one the request side already has for
`application/octet-stream` — a stream of bytes has no fields to name — and it is
written the same way: **one media type, declared binary, or it fails.** A route
that quietly stopped declaring a model still fails, because JSON plus a binary
type is refused outright.

A bundle is several files — a parent table, one per repeat, and the manifest —
so it is always a zip, even when it holds one table. One shape, no branch on
how many repeats a form happens to have.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.schemas import MessageError
from app.modules.export import service
from app.modules.export.schemas import (
    ExportFormat,
    ExportShape,
    ExportTooLargeResponse,
    ExportValueTooLongResponse,
)
from app.modules.export.service import DEFAULT_LIMIT, ExportTooLarge
from app.modules.export.statistical import ValueTooLong
from app.modules.submissions.schemas import SubmissionStatus

router = APIRouter()

#: The whole of the exemption: one media type, a stream of bytes, no fields.
ZIP_BODY = {
    "description": "The export bundle.",
    "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
}


class ZipResponse(Response):
    """The runtime response: a zip, with the Content-Type to match."""

    media_type = "application/zip"


@router.get(
    "/{form_id}",
    # The **base** `Response`, whose `media_type` is None, and not `ZipResponse`.
    # FastAPI documents every `responses` entry under the route class's media
    # type, so declaring `ZipResponse` here would publish the 404 and the 413 as
    # `application/zip` too — bodies this server has never sent, which is break
    # 13's mistake by another road. With no media type on the class, the 200 is
    # only what `ZIP_BODY` declares and the refusals fall back to JSON, which is
    # what they actually are.
    response_class=Response,
    responses={
        200: ZIP_BODY,
        404: {"model": MessageError},
        409: {"model": ExportValueTooLongResponse},
        # An explicit description, where the 404 and 409 take FastAPI's
        # default. FastAPI fills a missing one from `http.HTTPStatus(code)
        # .phrase`, which is the standard library's table and therefore the
        # interpreter's: CPython renamed 413 from "Request Entity Too Large"
        # to "Content Too Large" in 3.13, so the same app emitted a different
        # contract on either side of that line and the byte check failed for a
        # reason no diff of this repository could explain. Saying it here ties
        # the document to the app instead. See docs/known-breaks.md break 72.
        413: {
            "model": ExportTooLargeResponse,
            "description": "The filter selected more than one request will export.",
        },
    },
)
async def export_form(
    session: Annotated[AsyncSession, Depends(get_db)],
    form_id: Annotated[str, Path(min_length=1, max_length=200)],
    fmt: Annotated[ExportFormat, Query(alias="format")] = "csv",
    shape: Annotated[ExportShape, Query()] = "long",
    language: Annotated[str | None, Query(max_length=35)] = None,
    project_id: Annotated[str | None, Query(alias="projectId", max_length=64)] = None,
    environment_id: Annotated[
        str | None, Query(alias="environmentId", max_length=64)
    ] = None,
    status: Annotated[SubmissionStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=DEFAULT_LIMIT)] = DEFAULT_LIMIT,
) -> Response:
    """One form's submissions as a zip of tables plus a manifest.

    `formId` is the wire form key an op carries, the same value that filters
    `GET /submissions`, not the form row id.

    Each submission is read through the form version it was collected under and
    its codes named through that version's dataset pins, so an export spanning
    two versions is correct about both — there is no parameter here that selects
    a version, and that is deliberate (Form IR §9, §3.2).

    **Read the manifest before writing an analysis against the columns.** It
    names every column that can carry the `ENCRYPTED` token and which project
    keys open it, every column shortened to fit Stata's 32 characters, and every
    column stored as text that would otherwise be numeric.

    **413 means the filter selected more than this endpoint will do in one
    request**, and the fix is to narrow it by status or environment. It is a
    distinct code rather than a 422 because 422 belongs to the framework and
    means the request did not match the schema; this request matched it and
    asked for too much.

    **409 means this form's data will not fit the format asked for** — in
    practice, an answer longer than SPSS's 32,767-byte maximum for a `sav`. The
    body names the column and the formats that do hold it. It is a refusal
    rather than a truncated file: shortening an answer to fit would be silent
    data loss, and writing it anyway produces a file SPSS may not open.
    """
    async with session.begin():
        try:
            bundle = await service.export_form(
                session,
                form_key=form_id,
                project_id=project_id,
                environment_id=environment_id,
                status=status,
                language=language,
                shape=shape,
                fmt=fmt,
                limit=limit,
            )
        except ValueTooLong as refused:
            raise HTTPException(
                status_code=409,
                detail={
                    "column": refused.column,
                    "found": refused.found,
                    "limit": refused.limit,
                    "format": refused.format,
                    "message": str(refused),
                },
            ) from refused
        except ExportTooLarge as refused:
            raise HTTPException(
                status_code=413,
                detail={
                    "found": refused.found,
                    "limit": refused.limit,
                    "message": str(refused),
                },
            ) from refused

    if bundle is None:
        raise HTTPException(status_code=404, detail="form not found")

    name = f"{form_id}-{shape}-{fmt}.zip"
    return ZipResponse(
        content=bundle.to_zip(),
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
