"""Wire types for the export endpoint.

The bundle itself is a zip and has no Pydantic shape; what does have one is the
one way the request can be refused with something to branch on.

The envelope is deliberate. FastAPI wraps an `HTTPException`'s `detail` in
`{"detail": ...}` before it reaches the wire, so an error model has to *be* that
envelope — declaring the payload inside it publishes a contract for a body the
server has never returned, which is what `POST /devices` used to do (break 13).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: The tabular shapes an export comes in. A named alias rather than a plain
#: assignment, so the console gets `ExportShape` **and** an `EXPORT_SHAPES`
#: array to render a picker from (docs/project-conventions.md, "The API contract").
type ExportShape = Literal["long", "wide"]

#: The file formats. `csv` and `xlsx` are what every customer needs; `dta` and
#: `sav` are Stata and SPSS.
type ExportFormat = Literal["csv", "xlsx", "dta", "sav"]


class ExportTooLarge(BaseModel):
    """More submissions than one synchronous export will do.

    Carries the numbers rather than only prose, because the useful thing a
    console can do with this is say how much to narrow by.
    """

    model_config = ConfigDict(populate_by_name=True)

    found: int = Field(description="submissions the filter selected")
    limit: int = Field(description="the most this endpoint will export at once")
    # For a person reading a log; says what to do about it. Never parsed.
    message: str


class ExportTooLargeResponse(BaseModel):
    """413 from GET /exports/{formId}."""

    detail: ExportTooLarge


class ExportValueTooLong(BaseModel):
    """A value will not fit the format that was asked for.

    Names the formats that *do* hold it, because that is what a caller acts on:
    an SPSS user with one very long answer needs a different flag, not a
    truncated file and not a 500.
    """

    model_config = ConfigDict(populate_by_name=True)

    column: str = Field(description="the column in the file, as `storedAs` names it")
    found: int = Field(description="the value's length in UTF-8 bytes")
    limit: int = Field(description="the most this format's strings hold, in bytes")
    format: ExportFormat
    message: str


class ExportValueTooLongResponse(BaseModel):
    """409 from GET /exports/{formId}."""

    detail: ExportValueTooLong
