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


class DeployedDatasetVersion(BaseModel):
    """One entry of a device's dataset manifest (sync §5, `scope=datasets`).

    Deliberately not the rows. A village list is megabytes and a manifest
    travels on every sync; the rows are fetched once per version from
    `GET /datasets/versions/{id}/rows`, the same split that keeps a form
    manifest to a few hundred bytes.

    `formVersionId` is on every entry rather than implied, because the pin is
    per form version: two versions of a form can be deployed at once — an
    enumerator holding a v2 draft the morning v3 lands — and they may name
    different versions of the same list. A manifest keyed only by dataset would
    have to choose between them, which is the choice §3.2 exists to remove.
    """

    model_config = ConfigDict(populate_by_name=True)

    form_version_id: str = Field(serialization_alias="formVersionId")
    #: The Form IR key — what `choices.dataset` names in that form version.
    dataset_key: str = Field(serialization_alias="datasetKey")
    #: What the device must hold for that form version to be answerable.
    dataset_version_id: str = Field(serialization_alias="datasetVersionId")
    version: int
    row_count: int = Field(serialization_alias="rowCount")
    #: The content address. What a device compares to decide it already holds
    #: this exact list, so a version whose content drifted cannot pass for it.
    checksum: str
    #: The columns this form version's choice filters narrow on — what a device
    #: should index (Form IR §3.2).
    #:
    #: The server sends them because the server is what knows: the filter is in
    #: the IR, and which columns it selects on is decided by `compile_choices`,
    #: the same function the engine uses. A device indexing every column instead
    #: paid for it — 8 columns times 38,000 villages is 304,000 index entries,
    #: which on a Pixel 6 Pro turned a 137 ms delta into 14.4 seconds.
    filter_columns: list[str] = Field(
        default_factory=list, serialization_alias="filterColumns"
    )


class DatasetRowsPage(BaseModel):
    """One page of a dataset version's rows (sync §5).

    Paged because the first sync is the hard case and cannot be one response:
    a transfer that cannot resume is a transfer that never finishes on the
    connections this product exists for.

    A published version is immutable, so this page can be cached forever and a
    device that paused for a day resumes into the same ordering it left.
    """

    model_config = ConfigDict(populate_by_name=True)

    dataset_version_id: str = Field(serialization_alias="datasetVersionId")
    #: Rows as published: every value a string, because a CSV holds nothing
    #: else and §3.1 makes the key the cell's value exactly.
    rows: list[dict[str, str]]
    #: Pass back as `cursor` for the next page. Null on the last page — which
    #: is how a device knows it has the whole list and not most of it.
    next_cursor: str | None = Field(serialization_alias="nextCursor")
    has_more: bool = Field(serialization_alias="hasMore")


class DatasetDeltaPage(BaseModel):
    """What changed between two dataset versions, for one form version.

    The path that decides field usability. First sync is a one-off at
    enrolment; this is what happens every week for the life of the project, on
    whatever connection there is.
    """

    model_config = ConfigDict(populate_by_name=True)

    dataset_version_id: str = Field(serialization_alias="datasetVersionId")
    #: Echoed so a device can see the server agreed about where it was starting
    #: from, rather than inferring it from a page that happens to apply.
    from_dataset_version_id: str = Field(serialization_alias="fromDatasetVersionId")
    #: Whole rows, not just the changed columns: a device stores whole rows
    #: because another form version may read different ones.
    changed: list[dict[str, str]]
    #: Keys that are gone. Explicit, never inferred from absence — inferring it
    #: needs the whole set present to compare against, which is the thing a
    #: delta exists to avoid sending.
    deleted: list[str]
    #: The columns the projection was taken over. Reported so that *why* a row
    #: did or did not travel is answerable from the response rather than from
    #: reading the server.
    columns: list[str]
    next_cursor: str | None = Field(serialization_alias="nextCursor")
    has_more: bool = Field(serialization_alias="hasMore")
