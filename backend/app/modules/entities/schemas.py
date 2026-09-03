"""Wire types for publishing a dataset version.

A dataset arrives as a **file**, not as JSON. The console has the CSV in hand
— it just uploaded it to `POST /forms/import` — and a 38,000-row village list
re-encoded as a JSON array would be several megabytes of body on a call that
already has the bytes. Multipart keeps it the size the file is, and keeps one
parser for the format on the server side rather than one here and one in the
browser.

The refusal is a **409**, not a 422. docs/project-conventions.md: 422 already belongs to
FastAPI's own request-validation failure, three endpoints already collide with
it, and only one body shape can be declared under one status. A dataset whose
keys are unusable, or a version number already published with different
content, is a conflict with what the server holds and what it will accept — so
it gets its own code and its own declared body, and a client can branch on it.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PublishDatasetResponse(BaseModel):
    """One immutable dataset version (Form IR §3, sync §5)."""

    model_config = ConfigDict(populate_by_name=True)

    dataset_id: str = Field(serialization_alias="datasetId")
    #: What a form version pins to, and what a device names when it says which
    #: version of the list it is holding.
    dataset_version_id: str = Field(serialization_alias="datasetVersionId")
    #: The key the Form IR uses — `choices.dataset` (§3).
    dataset_key: str = Field(serialization_alias="datasetKey")
    version: int
    row_count: int = Field(serialization_alias="rowCount")
    #: Content address over (key, row hash) pairs. Two servers given the same
    #: rows produce the same string, which is what makes a delta meaningful.
    checksum: str
    #: False when this exact content was already published — the caller
    #: re-uploaded an unchanged file — and the existing version is returned.
    #: Distinguished because "nothing changed" and "a new version exists" lead
    #: to different next steps, and collapsing them is how a stale dataset goes
    #: unnoticed (item 4 part 5).
    created: bool
    #: Findings that did not stop the publish: keys differing only by case or
    #: whitespace, rows padded, a non-UTF-8 file. Never merged away silently.
    warnings: list[str]
    published_at: datetime | None = Field(serialization_alias="publishedAt")


class DatasetRefusedError(BaseModel):
    """The 409 body: every reason, not the first one.

    A list rather than a string for the same reason the publish endpoint's is:
    whoever is fixing the file needs every problem in one pass, and a refusal
    that names one duplicate key at a time is a refusal somebody meets four
    times.
    """

    model_config = ConfigDict(populate_by_name=True)

    detail: list[str]
