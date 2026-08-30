"""Wire types for the forms read API, compilation, evaluation and publishing.

Enough for a console to name a form and populate a filter, and to publish a new
immutable version through the same gate every other caller uses. The rest of
form authoring — CRUD, deployment — still lands later with its own schemas.

The compile and evaluate models live here rather than beside the routes so that
every wire type in the backend is in a `schemas.py` and the OpenAPI document
has one place it can be traced back to.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FormSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    # The stable key an op carries as `formId` on the wire (sync §2), not the
    # database id — that is what a submission filter matches on.
    form_id: str = Field(serialization_alias="formId")
    title: str
    versions: list[int]
    archived_at: datetime | None = Field(serialization_alias="archivedAt")


class FormListResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    forms: list[FormSummary]


class CompileRequest(BaseModel):
    """A Form IR document to compile. Its own formId and version are authoritative."""

    model_config = ConfigDict(populate_by_name=True)

    form: dict[str, Any]


class CompileResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    form_id: str = Field(serialization_alias="formId")
    version: int
    field_count: int = Field(serialization_alias="fieldCount")
    # Topological, ties broken by document order — the order recalculation runs
    # in, and the reason two engines agree on the result (Form IR §7).
    evaluation_order: list[str] = Field(serialization_alias="evaluationOrder")
    # Warnings do not block a publish (Form IR §10).
    warnings: list[str]


class EvaluateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    form: dict[str, Any]
    answers: dict[str, Any] = {}


class FieldSnapshot(BaseModel):
    """One field after recalculation — `FieldState.to_dict()` in the engine.

    Written out rather than left as a free-form object because this is the
    shape a form builder renders: `relevant` and `valid` decide whether a
    question is on screen and whether it is in error, and a client that has to
    guess at them is reimplementing the engine to read its output.
    """

    model_config = ConfigDict(populate_by_name=True)

    path: str
    # Null coerces to true here and false for `required`/`readOnly` — the
    # boundary rule in Form IR §4.4. By this point the coercion has happened,
    # so all four are plain booleans.
    relevant: bool
    required: bool
    read_only: bool = Field(serialization_alias="readOnly")
    # A non-relevant field retains its value; export is what drops it (§4.4).
    value: Any
    valid: bool
    errors: list[str]


class EvaluateResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    valid: bool
    # Every field, keyed by path — including the non-relevant ones.
    fields: dict[str, FieldSnapshot]
    # Relevant fields only: this is the export projection (Form IR §4.4).
    answers: dict[str, Any]


class PublishVersionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    # Explicit, never inferred. A form published into the wrong project is a
    # form collecting data under the wrong security mode and the wrong keys.
    project_id: str = Field(alias="projectId", min_length=1, max_length=64)
    # The full Form IR document. Its own formId and version are authoritative;
    # nothing here can override what the document says it is.
    form: dict[str, Any]
    title: str | None = None
    published_by: str | None = Field(default=None, alias="publishedBy")


class PublishVersionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    form_id: str = Field(serialization_alias="formId")
    version: int
    ir_checksum: str = Field(serialization_alias="irChecksum")
    published_at: datetime | None = Field(serialization_alias="publishedAt")
    # False when this exact IR was already published under this version number
    # and the call was a no-op.
    created: bool
    # Warnings do not block a publish (Form IR §10); they are returned so the
    # console can show what shipped anyway.
    warnings: list[str]
