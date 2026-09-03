"""Wire types for the forms read API, compilation, evaluation and publishing.

Enough for a console to name a form and populate a filter, to publish a new
immutable version through the same gate every other caller uses, and to tell a
device which versions its environment has deployed. The rest of form authoring —
CRUD, retiring a deployment — still lands later with its own schemas.

The compile and evaluate models live here rather than beside the routes so that
every wire type in the backend is in a `schemas.py` and the OpenAPI document
has one place it can be traced back to.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Mirrors environment_kind_check in migrations/schema/001_initial.sql. A named
# PEP 695 alias rather than a plain assignment, so the OpenAPI document states
# the closed set once and every field refs it (see submissions/schemas.py).
type EnvironmentKind = Literal["development", "staging", "production"]


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


# --- XLSForm import -------------------------------------------------------
#
# The diagnostic carries its location as separate fields rather than baked into
# the message. A console links to a row, a report groups by sheet, a test
# asserts on a code, and a person reads the sentence — a string that says
# "row 14, column relevant: ..." serves exactly one of those and has to be
# parsed to serve the rest.

type DiagnosticSeverity = Literal["error", "warning", "info"]


class ImportDiagnostic(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    severity: DiagnosticSeverity
    #: Stable and machine-readable. The wording of `message` may improve; this
    #: is what a console groups on and what a roadmap is counted from.
    code: str
    message: str
    #: Where, in the terms the author sees in their spreadsheet. `row` is
    #: 1-based and counts the header, so it is the number in Excel's margin.
    sheet: str | None = None
    row: int | None = None
    column: str | None = None
    # `alias`, not `serialization_alias`, and that is load-bearing here rather
    # than a style choice. This model is the only one in the API used as both a
    # request field (ImportRecord) and a response field (ImportFormResponse).
    # With a serialization-only alias the two directions have different
    # schemas, so Pydantic emits `ImportDiagnostic-Input` and
    # `-Output` — and a hyphen is not a legal TypeScript identifier, so the
    # generated console types did not compile. One alias for both directions
    # keeps it one schema.
    #: What was actually in the cell, so the reader need not go and look.
    cell_value: str | None = Field(default=None, alias="cellValue")
    #: Where this would have landed in the form, when that is known.
    node_id: str | None = Field(default=None, alias="nodeId")
    remedy: str | None = None


class ImportCoverage(BaseModel):
    """Proof that nothing was dropped in silence.

    Every non-empty cell in the workbook either produced part of the form or is
    named by a diagnostic above. A cell in neither fails the import outright
    rather than reaching this response — see the coverage ledger.

    It cannot tell you the workbook had anything in it. An empty sheet has no
    cells to account for, so `cells: 0` satisfies the check perfectly; that is
    why a form with no questions is refused at publish rather than merely noted.
    """

    model_config = ConfigDict(populate_by_name=True)

    cells: int
    consumed: int
    reported: int


class ImportInstrumentation(BaseModel):
    """What this form needed that the platform does not have.

    Separate from the diagnostics because it answers a different question: a
    diagnostic tells one author about one form, and this says which XPath
    functions and question types real forms reach for. That is the priority
    order for what to build next, and counting it beats guessing it.
    """

    model_config = ConfigDict(populate_by_name=True)

    unsupported_functions: dict[str, int] = Field(
        default_factory=dict, serialization_alias="unsupportedFunctions"
    )
    unsupported_types: dict[str, int] = Field(
        default_factory=dict, serialization_alias="unsupportedTypes"
    )
    uncollectable_types: dict[str, int] = Field(
        default_factory=dict, serialization_alias="uncollectableTypes"
    )


class ImportDataset(BaseModel):
    """One companion CSV, read — what it is and what the form does with it.

    Deliberately without the rows. This is the answer to "what would this
    become?", and a village list would make the response several megabytes on
    an endpoint whose whole point is to be cheap enough to call on every edit.
    The caller already has the file; `POST /projects/{id}/datasets` is where
    the bytes go.
    """

    model_config = ConfigDict(populate_by_name=True)

    #: The Form IR dataset key (§3) — what `choices.dataset` names, and what a
    #: pin at publish is keyed on.
    key: str
    #: As the survey sheet spelled it, so an author can match it to a file.
    file_name: str = Field(serialization_alias="fileName")
    row_count: int = Field(serialization_alias="rowCount")
    columns: list[str]
    #: The column a stored answer comes from, and therefore the record key.
    value_column: str = Field(serialization_alias="valueColumn")
    #: Language tag -> column. Empty when the file has no label column.
    label_columns: dict[str, str] = Field(
        default_factory=dict, serialization_alias="labelColumns"
    )
    #: The columns the form actually reads — value, labels, filters. What a
    #: delta is computed over (item 4 part 5), and the number that says whether
    #: an edit to this file will cost a device a download.
    columns_used: list[str] = Field(default_factory=list, serialization_alias="columnsUsed")
    #: Question ids that choose from it.
    used_by: list[str] = Field(default_factory=list, serialization_alias="usedBy")
    #: The checksum this content would publish under. Lets a console tell
    #: "already published" from "a new version" without a round trip.
    checksum: str
    #: `utf-8` unless the file needed the Windows-1252 fallback, which is
    #: reported rather than applied quietly — mojibake has no other symptom.
    encoding: str


class ImportSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    questions: int
    nodes: int
    survey_rows: int = Field(serialization_alias="surveyRows")
    languages: list[str]
    errors: int
    warnings: int
    notes: int


class ImportFormResponse(BaseModel):
    """The IR, and everything that did not survive the trip.

    The form is returned even when it cannot be published, deliberately: an
    author needs every problem in one pass rather than one per round trip, and
    a form they can look at is how they find the next one.
    """

    model_config = ConfigDict(populate_by_name=True)

    #: False when any diagnostic is an error. Publishing is refused server-side
    #: as well — this flag is for a console to grey a button, not the gate.
    publishable: bool
    form: dict[str, Any]
    summary: ImportSummary
    diagnostics: list[ImportDiagnostic]
    coverage: ImportCoverage
    instrumentation: ImportInstrumentation
    #: The companion CSVs this form needs (Form IR §3), in the order the survey
    #: sheet first referred to them. Empty for a form that uses none — which is
    #: not the same as a form whose files were not attached: that reports a
    #: `companion_file_missing` error per file, by name.
    datasets: list[ImportDataset] = Field(default_factory=list)
    #: The whole report as Markdown, ready to be written to a file and sent to
    #: the person who wrote the spreadsheet.
    report_markdown: str = Field(serialization_alias="reportMarkdown")


class ImportRecord(BaseModel):
    """How a version got here, stored with it and never recomputed.

    Sent by whoever imported the spreadsheet and published the result, so the
    question "why does this form not have the question I put in row 40?" is
    answerable six months later from the database rather than from an email
    somebody may still have.

    Optional on a publish: a form written as IR by hand was not imported, and
    recording nothing is the honest answer for it. Half a record is refused by
    the database (`form_version_import_complete_check`), because a partial one
    looks like a whole one.
    """

    model_config = ConfigDict(populate_by_name=True)

    # `alias`, like every other request model here. `serialization_alias` sets
    # the name a response is written with and leaves validation reading the
    # field name, so this arrived over the wire wanting `source_name` while the
    # rest of the API takes camelCase. The contract check could not see it: the
    # document was generated from the model and so agreed with it, and both
    # were wrong together. Caught by actually posting to the endpoint.
    source_name: str = Field(alias="sourceName")
    #: SHA-256 of the uploaded bytes. Answers "is this the same spreadsheet?"
    #: without keeping the spreadsheet.
    source_sha256: str = Field(alias="sourceSha256")
    #: Which importer produced it. The same warning means something different
    #: before and after a fix, and without this the two cannot be told apart.
    importer_version: str = Field(alias="importerVersion")
    diagnostics: list[ImportDiagnostic]


class DatasetPin(BaseModel):
    """One dataset version a form version is published against.

    The IR names a dataset by **key** — `"dataset": "districts"` (§3) — and a
    key is not a version. Resolving it at read time would let a draft opened
    against form v1 see whatever `districts` happens to be newest, which is the
    same mistake as validating a v1 answer against v2's choice list.

    So it is resolved once, here, at publish, and pinned in
    `form_version_dataset`. A form version is immutable and so is its view of
    its reference data.
    """

    model_config = ConfigDict(populate_by_name=True)

    key: str = Field(min_length=1, max_length=200)
    dataset_version_id: str = Field(alias="datasetVersionId", min_length=1, max_length=64)


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
    # Publishing and deploying are separate acts, and this is the shorthand for
    # doing both in one call — which is what a single-environment install
    # actually wants. An empty list publishes without deploying: the version
    # exists, and no device is told about it.
    deploy_to: list[EnvironmentKind] = Field(default_factory=list, alias="deployTo")
    # Present when this version came from a spreadsheet. Stored verbatim on the
    # row so "how was this imported and what did not survive" is answerable
    # from the database rather than from an emailed report.
    import_record: ImportRecord | None = Field(default=None, alias="importRecord")
    # Which dataset version each `choices.dataset` key resolves to. Required
    # for every key the IR names and refused for any key it does not: a pin
    # that nothing references is a claim about this form that is not true, and
    # a missing pin is a choice list that would resolve to whatever is newest.
    datasets: list[DatasetPin] = Field(default_factory=list)


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
    # Every environment this version is deployed to now — what `deployTo` asked
    # for, plus anything it was already deployed to. Reported because a publish
    # on its own reaches no device: a version nothing has deployed appears in no
    # manifest (sync §5), and "published" reads like "shipped" when it is not.
    deployments: list[EnvironmentKind]
    # What this version's choice lists resolve to, for as long as it exists.
    # Echoed for the same reason `deployments` is: the pinning is the whole
    # guarantee that an answer can be explained later, and a caller should be
    # able to see it happened rather than assume it.
    datasets: list[DatasetPin] = Field(default_factory=list)


class DeployedFormVersion(BaseModel):
    """One entry in a device's form manifest (sync §5, `scope=forms`).

    Deliberately not the IR. A 52-question form is tens of kilobytes, and a
    device re-syncs on whatever connection it has; sending every document on
    every pull would spend exactly the bandwidth this protocol exists to
    conserve. The manifest says what exists and what it hashes to, and the
    device fetches only the versions it does not already hold — the same shape
    resumable upload uses, where the server states what it has and the client
    sends the rest.
    """

    model_config = ConfigDict(populate_by_name=True)

    # The globally unique row id, and what GET /forms/versions/{id} takes.
    # `formId` and `version` identify a version only within one project.
    form_version_id: str = Field(serialization_alias="formVersionId")
    form_id: str = Field(serialization_alias="formId")
    version: int
    title: str
    # What the device compares against to decide whether it already holds this
    # exact document, so a version whose content drifted cannot pass for the one
    # already on the phone.
    ir_checksum: str = Field(serialization_alias="irChecksum")
    deployed_at: datetime = Field(serialization_alias="deployedAt")


class FormVersionDocument(BaseModel):
    """One published version and its Form IR (sync §5).

    What a device fetches once the manifest names a version it does not hold.
    Immutable: the id addresses a row that can never be rewritten
    (specs/erd-v0.1.md §4), so a client may cache it forever.
    """

    model_config = ConfigDict(populate_by_name=True)

    form_version_id: str = Field(serialization_alias="formVersionId")
    form_id: str = Field(serialization_alias="formId")
    version: int
    title: str
    ir_checksum: str = Field(serialization_alias="irChecksum")
    published_at: datetime | None = Field(serialization_alias="publishedAt")
    # The Form IR document itself, exactly as it was published.
    form: dict[str, Any]
