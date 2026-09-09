"""Wire types for the sample, cases and assignment (item 2, analysis §7).

A case is what the asker may see: the policies of 012_cases.sql decide, on the
asker's principal, and these shapes carry the answer. The `holder` fields are
the live assignments — the one row that names who holds a case, and the only
thing reassignment changes.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

type CaseStatus = Literal["open", "closed", "withdrawn"]


class CaseHolder(BaseModel):
    """The live assignment at one level."""

    model_config = ConfigDict(populate_by_name=True)

    team_id: str | None = Field(serialization_alias="teamId")
    team_name: str | None = Field(serialization_alias="teamName")
    user_id: str | None = Field(serialization_alias="userId")
    user_name: str | None = Field(serialization_alias="userName")
    assigned_at: str | None = Field(serialization_alias="assignedAt")


class Case(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    project_id: str = Field(serialization_alias="projectId")
    dataset_key: str | None = Field(serialization_alias="datasetKey")
    case_key: str | None = Field(serialization_alias="caseKey")
    status: CaseStatus
    priority: int
    due_at: str | None = Field(serialization_alias="dueAt")
    #: The sample row the case came from, as the newest version of its
    #: dataset holds it; `{}` for a case with no sample.
    data: dict[str, Any]
    holder: CaseHolder
    #: How much has been collected against it: submissions the asker may see.
    submissions: int


class CaseListResponse(BaseModel):
    cases: list[Case]


class AssignRequest(BaseModel):
    """Exactly one of the two: a team, or a person."""

    model_config = ConfigDict(populate_by_name=True)

    team_id: str | None = Field(default=None, alias="teamId")
    user_id: str | None = Field(default=None, alias="userId")


class BulkAssignRequest(AssignRequest):
    case_ids: list[str] = Field(alias="caseIds", min_length=1, max_length=5000)


class BulkAssignResponse(BaseModel):
    assigned: int


class SampleUploadResponse(BaseModel):
    """What one upload did: the dataset version it published (idempotent by
    content) and the cases it made, reopened and withdrew."""

    model_config = ConfigDict(populate_by_name=True)

    dataset_key: str = Field(serialization_alias="datasetKey")
    dataset_version_id: str = Field(serialization_alias="datasetVersionId")
    version: int
    row_count: int = Field(serialization_alias="rowCount")
    created_version: bool = Field(serialization_alias="createdVersion")
    key_columns: list[str] = Field(serialization_alias="keyColumns")
    cases_created: int = Field(serialization_alias="casesCreated")
    cases_reopened: int = Field(serialization_alias="casesReopened")
    cases_withdrawn: int = Field(serialization_alias="casesWithdrawn")
    warnings: list[str]


#: Why a request was refused. `outside_your_authority` is the database's
#: refusal — a case, team or person outside the asker's scope, or a person
#: not under the case's team; `bad_key_row` names a sample row with no
#: identity in a key column.
type CaseFailure = Literal["outside_your_authority", "not_found", "bad_key_row", "bad_request"]


class CaseError(BaseModel):
    reason: CaseFailure
    message: str


class CaseErrorResponse(BaseModel):
    detail: CaseError


class AssignedCase(BaseModel):
    """One entry of the assignment statement a device pulls (sync §5,
    `scope=assignments`): a case held by the device's person, with the sample
    row behind it so a roster can be preloaded and a settlement shown."""

    model_config = ConfigDict(populate_by_name=True)

    case_id: str = Field(serialization_alias="caseId")
    case_key: str | None = Field(serialization_alias="caseKey")
    dataset_key: str | None = Field(serialization_alias="datasetKey")
    status: CaseStatus
    priority: int
    due_at: str | None = Field(serialization_alias="dueAt")
    data: dict[str, Any]
