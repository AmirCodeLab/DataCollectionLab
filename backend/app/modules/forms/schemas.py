"""Wire types for the forms read API.

Enough for a console to name a form and populate a filter. Form authoring —
CRUD, publishing, deployment — is Phase 1 and lands with its own schemas.
"""

from datetime import datetime

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
