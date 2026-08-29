"""Wire types for the forms read API, plus version publishing.

Enough for a console to name a form and populate a filter, and to publish a new
immutable version through the same gate every other caller uses. The rest of
form authoring — CRUD, deployment — still lands later with its own schemas.
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
