"""XLSForm workbook -> Form IR document, with everything that did not survive.

The orchestration. `workbook.py` accounts for the cells, `expressions.py`
compiles the XPath, `datatypes.py` says what a phone can collect; this walks the
survey sheet and decides what each row becomes.

## The invariant that makes silence impossible

At the end, [CoverageLedger.residue] must be empty: every non-empty cell either
produced IR or has a diagnostic naming it. If anything is in neither, the import
raises rather than returning — a hole reaches a developer as a crash instead of
reaching an author as a form that quietly lost a question.

That is why every branch below either calls `ledger.consume(ref)` or reports a
diagnostic against `ref`. A new column handler that forgets both does not
produce a subtly wrong import; it produces a failing one, on the first form that
uses that column. See `test_xlsform_coverage.py`.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from app.modules.entities.rows import check_keys, content_address

from . import datatypes
from .datasets import (
    DEFAULT_LABEL_COLUMN,
    DEFAULT_VALUE_COLUMN,
    CompanionCsv,
    CsvUnreadable,
    read_companion_csv,
)
from .diagnostics import Diagnostic, DiagnosticLog, Instrumentation
from .expressions import ExpressionError, substitutions, translate
from .expressions import references as expr_references
from .workbook import (
    CHOICES_SHEET,
    SETTINGS_SHEET,
    SURVEY_SHEET,
    Cell,
    CellRef,
    CoverageLedger,
    Row,
    Workbook,
    WorkbookError,
    read,
)

# XLSForm type -> IR dataType, for the ones that mean the same thing.
#
# Both spellings of several types are here on purpose: `int` and `integer`,
# `string` and `text` are all in real files, and the ODK "widgets" sample uses
# the short forms throughout. A type this map does not know is reported, never
# guessed at.
_SIMPLE_TYPES = {
    "text": "text",
    "string": "text",
    "int": "integer",
    "integer": "integer",
    "decimal": "decimal",
    "date": "date",
    "time": "time",
    "datetime": "datetime",
    "dateTime": "datetime",
    "geopoint": "geopoint",
    "geotrace": "geotrace",
    "geoshape": "geoshape",
    "image": "image",
    "photo": "image",
    "audio": "audio",
    "video": "video",
    "file": "file",
    "barcode": "barcode",
    "note": "note",
    "signature": "signature",
    "draw": "drawing",
}

#: Types that carry no answer and exist only to record device metadata. They
#: are dropped deliberately, with an info diagnostic, because the IR records
#: this in `_metadata` (§4.2) rather than as questions.
_METADATA_TYPES = {
    "start", "end", "today", "deviceid", "subscriberid", "simserial",
    "phonenumber", "username", "email", "audit", "start-geopoint",
}

#: Columns whose meaning we know and deliberately do not carry into the IR.
#: Separated from unknown columns because "we ignored your appearance hint" and
#: "we did not recognise this column at all" are different things to be told.
_KNOWN_IGNORED_COLUMNS = {
    "appearance": "the IR carries `appearance` but no client reads it yet",
    "choice_filter": (
        "a choice filter over an inline list needs the filter columns carried "
        "into the IR, which Form IR §3 defines only for dataset-backed lists"
    ),
    "parameters": "widget parameters are not implemented",
    "trigger": "recalculation triggers are inferred from the dependency graph (§5.1)",
    "instance_name": "instance naming is not implemented",
    "body::accuracythreshold": "GPS accuracy is a project setting, not a form one",
    "autoplay": "media autoplay is not implemented",
    "image": "question media is not imported",
    "audio": "question media is not imported",
    "video": "question media is not imported",
    "rows": "textarea sizing is a display hint the IR does not carry",
    "read_only": "handled as `readonly`",
}

#: Real XLSForm types the Form IR can express and this platform has not built.
#:
#: These are **our** gap, not the author's. Telling somebody to check the
#: spelling of a correctly spelled word is the same defect as a connect-timeout
#: message asserting something is at the address: a conclusion the evidence does
#: not support.
#:
#: `select_one_from_file` used to be in here and is not any more — it reads its
#: companion CSV into a dataset (Form IR §3, item 4 part 2). What is *still* not
#: built is anything that resolves such a list, which is a different statement
#: and belongs where every other "no client can present this" lives: the
#: collectable registry, checked per question rather than per type.
_NOT_YET_IMPLEMENTED = {
    "select_one_external": (
        "the external itemsets.csv mechanism (a single file holding every "
        "list; Form IR §3 has one dataset per list instead)"
    ),
    "select_multiple_external": (
        "the external itemsets.csv mechanism (a single file holding every "
        "list; Form IR §3 has one dataset per list instead)"
    ),
    "xml-external": "external instance data",
}

#: Real XLSForm types the Form IR has no way to express. The author has to
#: rewrite; waiting for us will not help, because there is nothing planned.
_NOT_IN_THE_IR = {
    "trigger": "an acknowledgement widget rather than a question",
    "acknowledge": "an acknowledgement widget rather than a question",
    "rank": "ordered ranking of choices",
    "range": "a slider over a numeric range",
    "osm": "OpenStreetMap feature capture",
}

_SELECT_ONE = re.compile(r"^select_one\s+(\S+)", re.IGNORECASE)
_SELECT_MULTI = re.compile(r"^select_multiple\s+(\S+)", re.IGNORECASE)
# `\s+` and not a single space on purpose: the UCL form writes
# `select_one_from_file  UCL_districts.csv` with two of them, and a form is not
# refused over a spacebar.
_SELECT_ONE_FROM_FILE = re.compile(r"^select_one_from_file\s+(\S+)", re.IGNORECASE)
_SELECT_MULTI_FROM_FILE = re.compile(r"^select_multiple_from_file\s+(\S+)", re.IGNORECASE)
# The legacy long spellings, which the ODK "widgets" sample still uses.
_SELECT_ONE_LONG = re.compile(r"^select\s+one\s+(?:from\s+)?(\S+)", re.IGNORECASE)
_SELECT_MULTI_LONG = re.compile(
    r"^select\s+(?:all\s+that\s+apply|multiple)\s+(?:from\s+)?(\S+)", re.IGNORECASE
)

_LANGUAGE_COLUMN = re.compile(r"^(?P<base>[a-z_:]+?)::(?P<language>.+)$")

#: Form IR §2.4. Stricter than XLSForm, which happily takes camelCase.
_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def normalise_id(name: str) -> str:
    """An XLSForm name as a Form IR id (§2.4: `^[a-z][a-z0-9_]*$`).

    XLSForm names are looser than IR ids — `numberAsString` is in the ODK
    sample form and is not a legal id. Refusing the form over a capital letter
    would be a spelling test rather than a check, so the name is normalised and
    the rename is **reported**: the id is what an export column is called, so
    an author matching their spreadsheet against a data file has to be told
    that `numberAsString` became `numberasstring`.

    Collisions are not resolved here. Two names that normalise to one are an
    error, because the alternative is inventing a suffix and silently
    scrambling which answers belong to which question.
    """
    slug = re.sub(r"[^a-z0-9_]+", "_", name.strip().lower()).strip("_")
    if not slug:
        return ""
    if not slug[0].isalpha():
        slug = f"q_{slug}"
    return slug


@dataclass
class ImportedDataset:
    """One companion CSV, read, and what the form does with it.

    Carries the rows because the caller is the one that publishes them: the
    import endpoint is stateless by design ("what would this become?") and
    `POST /projects/{id}/datasets` is what commits. The report only ever prints
    counts and column names, never the data.
    """

    #: The Form IR dataset key (§3) — what `choices.dataset` names.
    key: str
    #: As the survey sheet spelled it, which is what the author has on disk.
    file_name: str
    columns: list[str]
    rows: list[dict[str, str]]
    #: The column a stored answer comes from, and therefore the record key.
    value_column: str
    #: Language tag -> column. Empty when the file has no label column at all.
    label_columns: dict[str, str] = field(default_factory=dict)
    #: Question ids that select from it.
    used_by: list[str] = field(default_factory=list)
    #: Columns the form actually reads: value, labels, and anything a filter
    #: names. What a delta must be computed over (item 4 part 5) and what the
    #: report prints, because "38 columns, 4 of them used" is the fact that
    #: decides whether an edit costs a device a transfer.
    columns_used: list[str] = field(default_factory=list)
    #: The checksum this content would publish under. Same function the server
    #: uses, so a caller can tell "already published" from "new version"
    #: without a round trip.
    checksum: str = ""
    encoding: str = "utf-8"
    #: Findings about the file that did not stop it being read.
    warnings: list[str] = field(default_factory=list)

    @property
    def row_count(self) -> int:
        return len(self.rows)


@dataclass
class ImportResult:
    form: dict[str, Any]
    diagnostics: list[Diagnostic]
    instrumentation: Instrumentation
    coverage: dict[str, int]
    #: Rows in the survey sheet that carried anything, and nodes produced.
    survey_rows: int = 0
    nodes: int = 0
    #: Question nodes specifically — what an enumerator will actually be asked.
    questions: int = 0
    #: False when any diagnostic is an error. The IR is still returned — the
    #: author needs every problem in one pass — but it must not be published.
    publishable: bool = True
    languages: list[str] = field(default_factory=list)
    #: The companion CSVs this form needs, read. In the order the survey sheet
    #: first referred to them, so a report reads down the form.
    datasets: list[ImportedDataset] = field(default_factory=list)


class ImportFailed(Exception):
    """The workbook could not be read at all."""


class CoverageHole(AssertionError):
    """A cell produced nothing and was never reported.

    Deliberately an AssertionError and deliberately not catchable as an import
    diagnostic: this is a bug in the importer, not a problem with the form, and
    the only safe response is to stop. Returning a form that silently lost a
    cell is the exact failure this module is built to make impossible.
    """


def _language_of(column: str) -> tuple[str, str | None]:
    """Split `label::English (en)` into (`label`, `en`).

    XLSForm writes the language as a display name, optionally with an IETF tag
    in brackets. The tag is what the IR wants (§7); when there is no tag the
    display name is slugged, because a form whose only language column is
    `label::Swahili` still needs a key and losing the string entirely would be
    worse than an imperfect one.
    """
    match = _LANGUAGE_COLUMN.match(column)
    if not match:
        return column, None
    base = match.group("base")
    language = match.group("language").strip()
    tagged = re.search(r"\(([A-Za-z-]{2,})\)\s*$", language)
    if tagged:
        return base, tagged.group(1).lower()
    return base, re.sub(r"[^a-z0-9]+", "_", language.lower()).strip("_") or None


class _Importer:
    def __init__(self, ledger: CoverageLedger, companions: dict[str, bytes] | None = None) -> None:
        self.ledger = ledger
        #: The files supplied beside the workbook, by the name they were
        #: supplied under. Matched case-insensitively — a survey sheet saying
        #: `UCL_villages.csv` and a file named `ucl_villages.csv` is a Windows
        #: author and a Linux server, not a different file.
        self.companions = {name.strip(): data for name, data in (companions or {}).items()}
        self._companions_folded = {name.casefold(): name for name in self.companions}
        #: file name (as the survey sheet spells it) -> what it became.
        self.datasets: dict[str, ImportedDataset] = {}
        #: Dataset key -> the first file that claimed it, for collision checks.
        self.dataset_key_owner: dict[str, str] = {}
        #: File name -> the key of the diagnostic that explained why it cannot
        #: be used. One explanation per file however many questions name it —
        #: `species_names.csv` is named four times by the UCL form — and every
        #: question after the first is reported as a knock-on pointing here.
        self.unreadable_files: dict[str, str] = {}
        self.log = DiagnosticLog(ledger)
        self.instrumentation = Instrumentation()
        self.choice_lists: dict[str, list[dict[str, Any]]] = {}
        self.used_choice_lists: set[str] = set()
        self.languages: set[str] = set()
        self.default_language: str | None = None
        self.question_ids: set[str] = set()
        #: XLSForm name -> IR id, for rewriting references once every question
        #: has been seen. Built during the survey walk; applied after it.
        self.renames: dict[str, str] = {}
        #: Cells holding an expression, so references can be checked and
        #: rewritten once the full set of ids is known.
        self.expression_cells: list[tuple[dict[str, Any], str, CellRef, str, str]] = []
        #: Question name -> the key of the diagnostic that dropped it, so a
        #: reference to it can be reported under its cause rather than as a
        #: problem of its own.
        self.dropped_questions: dict[str, str] = {}
        #: Choice list -> rows defining it, and which questions used it.
        self.choice_list_rows: dict[str, list[CellRef]] = {}
        self.choice_list_users: dict[str, list[str]] = {}
        #: Node id -> the survey row it came from, for diagnostics that only
        #: know a node.
        self.node_rows: dict[str, int] = {}
        #: Interpolated labels, so an unresolvable `${name}` is reported against
        #: **the label's own cell** rather than the question's type cell. An
        #: author with the file open is looking at the sentence, not the row.
        self.label_arg_cells: list[tuple[str, str, CellRef, str, list[str]]] = []

    # -- settings ------------------------------------------------------------

    def read_settings(self, workbook: Workbook) -> dict[str, str]:
        sheet = workbook.sheet(SETTINGS_SHEET)
        values: dict[str, str] = {}
        if sheet is None:
            return values
        for row in sheet.rows:
            if row.is_empty:
                continue
            for column, cell in row.cells.items():
                if column in ("form_title", "form_id", "version", "default_language"):
                    values[column] = cell.value
                    self.ledger.consume(cell.ref)
                elif column in ("style", "instance_name", "allow_choice_duplicates"):
                    self.log.info(
                        "setting_ignored",
                        f"The `{column}` setting is not used by this platform.",
                        ref=cell.ref,
                        cell_value=cell.value,
                    )
                elif column in ("public_key", "submission_url"):
                    self.log.warning(
                        "setting_ignored",
                        f"`{column}` is an ODK Aggregate setting. Encryption and the "
                        "server address are project settings here, not form settings.",
                        ref=cell.ref,
                        cell_value=cell.value,
                        remedy="Set these on the project, not in the form.",
                    )
                else:
                    self.log.warning(
                        "unknown_setting",
                        f"The setting `{column}` is not one this importer knows.",
                        ref=cell.ref,
                        cell_value=cell.value,
                    )
        return values

    # -- choices -------------------------------------------------------------

    def read_choices(self, workbook: Workbook) -> None:
        sheet = workbook.sheet(CHOICES_SHEET)
        if sheet is None:
            return
        for row in sheet.rows:
            if row.is_empty:
                continue
            list_name = row.get("list_name") or row.get("list name")
            name = row.get("name")
            if not list_name or not name:
                for cell in row.cells.values():
                    self.log.warning(
                        "incomplete_choice",
                        "A choices row needs both `list_name` and `name`; this one is "
                        "missing at least one, so the whole row was skipped.",
                        ref=cell.ref,
                        cell_value=cell.value,
                    )
                continue

            labels: dict[str, str] = {}
            for column, cell in row.cells.items():
                base, language = _language_of(column)
                if base in ("list_name", "list name", "name"):
                    self.ledger.consume(cell.ref)
                elif base == "label":
                    key = language or "default"
                    labels[key] = cell.value
                    if language:
                        self.languages.add(language)
                    self.ledger.consume(cell.ref)
                    # The same check the question labels get, and it was missing
                    # here. Found on a handset: `xl_date_ambiguous_v1.xlsx` has
                    # choices labelled `${name1}`, `${name2}`, `${name3}`, the
                    # form imported as publishable, deployed, and offered a
                    # respondent three options reading literally "${name1}".
                    #
                    # A choice label is read out loud to somebody. That makes it
                    # exactly as bad as an output in a question label, and there
                    # is no reason the two checks should have been in different
                    # places.
                    outputs = substitutions(cell.value)
                    if outputs:
                        inserted = ", ".join("${" + o + "}" for o in outputs)
                        self.log.error(
                            "output_in_label",
                            f"This choice label inserts the answer to {inserted}. The "
                            "Form IR carries plain text (§7), so a respondent would be "
                            "offered an option reading literally that.",
                            ref=cell.ref,
                            cell_value=cell.value,
                            remedy="Rewrite the choice label without the ${...} insert.",
                        )
                elif base in ("image", "media"):
                    self.log.warning(
                        "choice_media_ignored",
                        "Choice media is not imported; the choice keeps its text label.",
                        ref=cell.ref,
                        cell_value=cell.value,
                    )
                else:
                    self.instrumentation.note_column(column)
                    self.log.warning(
                        "unknown_choice_column",
                        f"The choices column `{column}` is not one this importer uses.",
                        ref=cell.ref,
                        cell_value=cell.value,
                    )
            self.choice_lists.setdefault(list_name, []).append(
                {"value": name, "label": labels or {"default": name}}
            )
            self.choice_list_rows.setdefault(list_name, []).append(
                row.cells[next(iter(row.cells))].ref
            )

    # -- survey --------------------------------------------------------------

    def read_survey(self, workbook: Workbook) -> list[dict[str, Any]]:
        sheet = workbook.sheet(SURVEY_SHEET)
        assert sheet is not None  # read() refuses a workbook without one
        root: list[dict[str, Any]] = []
        stack: list[list[dict[str, Any]]] = [root]
        # Parallel to `stack`, so an `end group` can name what it is closing.
        open_containers: list[tuple[str, CellRef]] = []

        for row in sheet.rows:
            if row.is_empty:
                continue
            type_cell = row.cells.get("type")
            if type_cell is None:
                for cell in row.cells.values():
                    self.log.warning(
                        "row_without_type",
                        "This row has content but no `type`, so it is not a question "
                        "and was skipped.",
                        ref=cell.ref,
                        cell_value=cell.value,
                    )
                continue

            raw_type = re.sub(r"\s+", " ", type_cell.value).strip()
            lowered = raw_type.lower()

            if lowered in ("begin group", "begin_group", "begin repeat", "begin_repeat"):
                node = self._container(row, type_cell, lowered)
                self.ledger.produced(row.sheet, row.number)
                stack[-1].append(node)
                stack.append(node["children"])
                open_containers.append((node["id"], type_cell.ref))
                continue

            if lowered in ("end group", "end_group", "end repeat", "end_repeat"):
                self.ledger.consume(type_cell.ref)
                # Structural: it produces no node and is not a loss.
                self.ledger.produced(row.sheet, row.number)
                for column, cell in row.cells.items():
                    if column != "type":
                        self.log.info(
                            "ignored_on_end_row",
                            f"`{column}` on an `{lowered}` row has no meaning and was ignored.",
                            ref=cell.ref,
                            cell_value=cell.value,
                        )
                if len(stack) == 1:
                    self.log.error(
                        "unbalanced_group",
                        f"`{raw_type}` closes a group that was never opened.",
                        ref=type_cell.ref,
                        cell_value=raw_type,
                        remedy="Remove this row, or add the matching `begin` row above it.",
                    )
                    continue
                stack.pop()
                open_containers.pop()
                continue

            question = self._question(row, type_cell, raw_type)
            if question is not None:
                self.ledger.produced(row.sheet, row.number)
                stack[-1].append(question)

        for name, ref in open_containers:
            self.log.error(
                "unbalanced_group",
                f"The group `{name}` is never closed; every `begin` needs an `end`.",
                ref=ref,
                node_id=name,
                remedy="Add an `end group` row after the last question in it.",
            )
        return root

    def _container(self, row: Row, type_cell: Cell, lowered: str) -> dict[str, Any]:
        self.ledger.consume(type_cell.ref)
        kind = "repeat" if "repeat" in lowered else "group"
        name = row.get("name")
        name_cell = row.cells.get("name")
        if name_cell:
            self.ledger.consume(name_cell.ref)
        if not name:
            name = f"{kind}_{row.number}"
            self.log.warning(
                "container_without_name",
                f"This `{lowered}` has no `name`, so it was called `{name}`.",
                ref=type_cell.ref,
                cell_value=lowered,
            )
        name = self._identifier(name, type_cell.ref, row)
        if name is None:
            return {"type": kind, "id": f"{kind}_{row.number}", "children": []}

        node: dict[str, Any] = {"type": kind, "id": name, "children": []}
        self.node_rows[name] = row.number
        labels, label_args = self._labels(row, node_id=name)
        if labels:
            node["label"] = labels
        if label_args:
            node["labelArgs"] = label_args

        # A group or repeat carries `relevant` too (§2.2, §2.3), and the engine
        # reads it for the whole subtree — relevance is inherited. This ran only
        # for questions, so a `relevant` on a `begin repeat` fell through to the
        # unknown-column branch and was reported as "`relevant` is not a column
        # this importer understands", which is both wrong and a warning. Four
        # repeats in the UCL form lost their condition that way, and every
        # question inside them with it.
        self._expressions(row, node, name)

        # `repeat_count` is `countExpr` (§2.3): with it the count is computed
        # and the enumerator cannot add or remove instances; without it they
        # can. That is a difference in what gets collected, so it is imported
        # rather than warned about.
        if kind == "repeat":
            count_cell = row.cells.get("repeat_count")
            if count_cell is not None:
                try:
                    node["countExpr"] = translate(count_cell.value, self_path=name)
                    self.ledger.consume(count_cell.ref)
                    self.expression_cells.append(
                        (node, "countExpr", count_cell.ref, count_cell.value, name)
                    )
                except ExpressionError as failure:
                    if failure.function:
                        self.instrumentation.note_function(failure.function)
                    self.log.error(
                        "untranslatable_expression",
                        f"The `repeat_count` of `{name}` could not be translated: "
                        f"{failure}. Left out, the enumerator would add and remove "
                        "instances by hand instead of the count being computed.",
                        ref=count_cell.ref,
                        cell_value=count_cell.value,
                        node_id=name,
                    )

        self._consume_remaining(
            row,
            node_id=name,
            handled={
                "type", "name", "relevant", "constraint", "calculation", "repeat_count",
            },
        )
        return node

    def _question(self, row: Row, type_cell: Cell, raw_type: str) -> dict[str, Any] | None:
        lowered = raw_type.lower()
        name = row.get("name")
        name_cell = row.cells.get("name")

        if lowered in _METADATA_TYPES:
            self.ledger.consume(type_cell.ref)
            if name_cell:
                self.ledger.consume(name_cell.ref)
            self._consume_remaining(row, node_id=name, handled={"type", "name"}, quiet=True)
            self.log.info(
                "metadata_type_dropped",
                f"`{raw_type}` records device metadata rather than an answer. The "
                "platform records this itself (Form IR §4.2), so no question was created.",
                ref=type_cell.ref,
                cell_value=raw_type,
                node_id=name,
            )
            return None

        if not name:
            self.log.error(
                "question_without_name",
                "A question needs a `name`; without one nothing can refer to its answer.",
                ref=type_cell.ref,
                cell_value=raw_type,
                remedy="Give the row a `name`.",
            )
            self._consume_remaining(row, node_id=None, handled={"type"}, quiet=True)
            return None

        original_name = name
        name = self._identifier(name, name_cell.ref if name_cell else type_cell.ref, row)
        if name is None:
            self._consume_remaining(row, node_id=None, handled={"type"}, quiet=True)
            return None
        if original_name != name:
            self.renames[original_name] = name

        if name in self.question_ids:
            self.log.error(
                "duplicate_question_name",
                f"`{name}` is used by more than one question. Answers are stored by "
                "name, so two questions sharing one would overwrite each other.",
                ref=name_cell.ref if name_cell else type_cell.ref,
                cell_value=name,
                node_id=name,
                remedy="Rename one of them.",
            )
            self._consume_remaining(row, node_id=name, handled={"type"}, quiet=True)
            return None

        data_type, choice_ref = self._data_type(row, type_cell, raw_type, name)
        if data_type is None:
            self._consume_remaining(row, node_id=name, handled={"type", "name"}, quiet=True)
            return None

        self.ledger.consume(type_cell.ref)
        if name_cell:
            self.ledger.consume(name_cell.ref)
        self.question_ids.add(name)
        self.node_rows[name] = row.number

        node: dict[str, Any] = {"type": "question", "id": name, "dataType": data_type}

        labels, label_args = self._labels(row, node_id=name)
        if labels:
            node["label"] = labels
        if label_args:
            node["labelArgs"] = label_args
        # A hint carries no arguments: §7.1 gives slots to `label` and
        # `constraintMessage` only, and the corpus has no hint that inserts one.
        hints, hint_args = self._labels(row, node_id=name, base="hint")
        if hints:
            node["hint"] = hints
        if hint_args:
            self.log.warning(
                "output_in_hint",
                "This hint inserts an answer. Form IR §7.1 gives slots to labels "
                "and constraint messages; a hint carries plain text, so the "
                "insert was left as written.",
                ref=row.ref("hint"),
                node_id=name,
            )
            node["hint"] = {k: _from_slots(v, hint_args) for k, v in hints.items()}

        if choice_ref is not None and choice_ref[0] == "inline":
            choice_list = choice_ref[1]
            self.used_choice_lists.add(choice_list)
            self.choice_list_users.setdefault(choice_list, []).append(name)
            items = self.choice_lists.get(choice_list)
            if items is None:
                self.log.error(
                    "missing_choice_list",
                    f"`{name}` uses the choice list `{choice_list}`, which is not on "
                    "the choices sheet. The question has no options to offer.",
                    ref=type_cell.ref,
                    cell_value=raw_type,
                    node_id=name,
                    remedy=f"Add rows with `list_name` = `{choice_list}` to the choices sheet.",
                )
            else:
                node["choices"] = {
                    "kind": "inline",
                    "items": [self._choice_item(item) for item in items],
                }
        elif choice_ref is not None:
            self._dataset_choices(row, node, name, choice_ref[1], type_cell, raw_type)

        self._expressions(row, node, name)
        self._flags(row, node, name)
        self._consume_remaining(
            row,
            node_id=name,
            handled={
                "type", "name", "required", "relevant", "constraint", "calculation",
                "default", "readonly", "read_only", "constraint_message",
                "bind:jr:constraintmsg", "requiredmsg", "bind:jr:requiredmsg",
            },
        )

        collectability = datatypes.classify(data_type)
        if collectability == "in_spec_only":
            self.instrumentation.note_uncollectable(data_type)
            self.log.error(
                "type_not_collectable",
                f"`{name}` is a `{data_type}` question. That is a valid Form IR type, "
                "but no client can present it yet, so an enumerator would see a "
                "question they cannot answer.",
                ref=type_cell.ref,
                cell_value=raw_type,
                node_id=name,
                remedy="Use a type the app can collect, or wait for a build that\n"
                "supports this one.",
            )
        return node

    # -- dataset-backed choices (Form IR §3) ---------------------------------

    def _dataset_key(self, file_name: str, ref: CellRef, node_id: str) -> str | None:
        """The Form IR dataset key a companion file is published under.

        `UCL_villages.csv` becomes `ucl_villages`. The IR names a dataset by key
        and §2.4's identifier rule is what every other name in the document
        obeys, so a file name is normalised the same way a question name is —
        and the rename is reported for the same reason, because the key is what
        the console, the sync manifest and the retention rule all say.
        """
        stem = re.sub(r"\.csv$", "", file_name.strip(), flags=re.IGNORECASE)
        key = normalise_id(stem)
        if not key or not _ID_PATTERN.match(key):
            self.log.error(
                "unusable_dataset_name",
                f"`{file_name}` cannot be turned into a dataset key. Form IR §3 names "
                "a dataset by an identifier (§2.4): a lowercase letter followed by "
                "letters, digits and underscores.",
                ref=ref,
                cell_value=file_name,
                node_id=node_id,
                key=f"companion_unusable:{file_name.casefold()}",
                remedy="Rename the file, for example to `villages.csv`.",
            )
            return None

        owner = self.dataset_key_owner.get(key)
        if owner is not None and owner.casefold() != file_name.casefold():
            self.log.error(
                "dataset_key_collision",
                f"`{file_name}` and `{owner}` both become the dataset key `{key}`. "
                "One key cannot name two different lists, and choosing between them "
                "automatically would silently give a question the wrong options.",
                ref=ref,
                cell_value=file_name,
                node_id=node_id,
                key=f"companion_unusable:{file_name.casefold()}",
                remedy="Rename one of the files so the two differ by more than case "
                "or punctuation.",
            )
            return None
        self.dataset_key_owner[key] = file_name
        if key != stem:
            self.log.info(
                "dataset_key_normalised",
                f"`{file_name}` is published as the dataset `{key}` (Form IR §3 names "
                "a dataset by an identifier, §2.4).",
                ref=ref,
                cell_value=file_name,
                node_id=node_id,
            )
        return key

    def _companion(self, file_name: str, ref: CellRef, node_id: str) -> CompanionCsv | None:
        """The named companion file, read once however many questions use it.

        Missing is an error and not a warning, and it is worth being clear why:
        the question is not merely reduced, it has *no options at all*. A form
        whose village list did not arrive is a form that cannot be answered, and
        it looks exactly like a form that can.
        """
        if file_name in self.unreadable_files:
            return None

        actual = self._companions_folded.get(file_name.casefold())
        if actual is None:
            self.unreadable_files[file_name] = f"companion_missing:{file_name.casefold()}"
            supplied = ", ".join(f"`{n}`" for n in sorted(self.companions)) or "none at all"
            self.log.error(
                "companion_file_missing",
                f"`{file_name}` was not supplied. XLSForm keeps this list in a file "
                "beside the workbook rather than in it, so without the file the "
                "question has no options to offer — not fewer, none.",
                ref=ref,
                cell_value=file_name,
                node_id=node_id,
                key=f"companion_missing:{file_name.casefold()}",
                remedy=f"Attach `{file_name}` along with the workbook. Files supplied "
                f"with this import: {supplied}.",
            )
            return None

        try:
            return read_companion_csv(actual, self.companions[actual])
        except CsvUnreadable as failure:
            self.unreadable_files[file_name] = f"companion_unreadable:{file_name.casefold()}"
            self.log.error(
                "companion_file_unreadable",
                str(failure),
                ref=ref,
                cell_value=file_name,
                node_id=node_id,
                key=f"companion_unreadable:{file_name.casefold()}",
            )
            return None

    def _resolve_dataset(
        self, file_name: str, type_cell: Cell, name: str
    ) -> ImportedDataset | None:
        """Read the companion file behind a `select_one_from_file`, once.

        None means it cannot be used and the reason has been reported. Every
        question naming the same file shares one reading and one diagnostic —
        `species_names.csv` is named four times by the UCL form, and four
        copies of "this file is missing" is three too many.
        """
        existing = self.datasets.get(file_name.casefold())
        if existing is not None:
            return existing
        if file_name in self.unreadable_files:
            return None
        key = self._dataset_key(file_name, type_cell.ref, name)
        csv_file = self._companion(file_name, type_cell.ref, name) if key else None
        if key is None or csv_file is None:
            self.unreadable_files.setdefault(file_name, "unusable")
            return None

        if DEFAULT_VALUE_COLUMN not in csv_file.columns:
            self.log.error(
                "dataset_has_no_value_column",
                f"`{file_name}` has no `{DEFAULT_VALUE_COLUMN}` column. That is "
                "the column XLSForm stores as the answer, so without it there is "
                f"nothing to select. Its columns are: "
                f"{', '.join('`' + c + '`' for c in csv_file.columns)}.",
                ref=type_cell.ref,
                cell_value=file_name,
                node_id=name,
                key=f"companion_unusable:{file_name.casefold()}",
                remedy=f"Add a `{DEFAULT_VALUE_COLUMN}` column holding the value "
                "each row is chosen as.",
            )
            self.unreadable_files[file_name] = f"companion_unusable:{file_name.casefold()}"
            return None

        labels = csv_file.label_columns()
        if not labels and DEFAULT_LABEL_COLUMN in csv_file.columns:
            # A plain `label` with no language suffix, exactly as on the
            # choices sheet. Retagged onto the real default language once
            # the settings sheet has been read.
            labels = {"default": DEFAULT_LABEL_COLUMN}
        if not labels:
            self.log.warning(
                "dataset_has_no_label_column",
                f"`{file_name}` has no `{DEFAULT_LABEL_COLUMN}` column, so each "
                f"option will be shown as its `{DEFAULT_VALUE_COLUMN}` value. That "
                "is readable for a code like `TZ01` and not for an id.",
                ref=type_cell.ref,
                cell_value=file_name,
                node_id=name,
            )

        existing = ImportedDataset(
            key=key,
            file_name=file_name,
            columns=list(csv_file.columns),
            rows=csv_file.rows,
            value_column=DEFAULT_VALUE_COLUMN,
            label_columns=labels,
            encoding=csv_file.encoding,
            warnings=list(csv_file.warnings),
        )
        existing.columns_used = [DEFAULT_VALUE_COLUMN, *labels.values()]
        existing.checksum = content_address(
            [dict(r) for r in csv_file.rows], DEFAULT_VALUE_COLUMN
        )
        self.datasets[file_name.casefold()] = existing
        self._report_dataset_keys(existing, type_cell.ref)
        return existing

    def _dataset_choices(
        self,
        row: Row,
        node: dict[str, Any],
        name: str,
        file_name: str,
        type_cell: Cell,
        raw_type: str,
    ) -> None:
        """Attach the `choices.kind = "dataset"` block (Form IR §3).

        The file is already read — `_data_type` refuses the question outright if
        it is not — so this only builds the block and translates the filter.
        """
        existing = self.datasets[file_name.casefold()]
        existing.used_by.append(name)
        choices: dict[str, Any] = {
            "kind": "dataset",
            "dataset": existing.key,
            "valueColumn": existing.value_column,
        }
        if existing.label_columns:
            choices["labelColumn"] = dict(existing.label_columns)
        node["choices"] = choices

        self._choice_filter(row, node, name, existing)

        # Whether an enumerator can answer it, which is not the same question as
        # whether `select_one` is a collectable dataType. The registry decides,
        # not this file — see specs/collectable-types-v0.1.json.
        if datatypes.classify_choice_source("dataset") != "collectable":
            self.instrumentation.note_uncollectable(f"{node['dataType']} (dataset-backed)")
            self.log.error(
                "choice_source_not_collectable",
                "This question chooses from a dataset (Form IR §3). The reference "
                "data was read and will be published with the form, but nothing "
                "resolves a dataset-backed list yet — not the form engines and not "
                "a device — so the question would reach an enumerator with no "
                "options under it at all.",
                ref=type_cell.ref,
                cell_value=raw_type,
                node_id=name,
                blame="platform",
                remedy="Nothing is wrong with your spreadsheet or your CSV. Either "
                "wait for dataset-backed selects to ship, or replace the question "
                "with a `select_one` over a list on the choices sheet.",
            )

    def _report_dataset_keys(self, dataset: ImportedDataset, ref: CellRef) -> None:
        """Say at import what the publish endpoint would refuse, and why.

        The same `check_keys` the server runs, so the report and the gate cannot
        disagree — a report saying a file is fine and a publish then refusing it
        is the `publishable`-versus-the-gate failure one level down.
        """
        report = check_keys([dict(r) for r in dataset.rows], dataset.value_column)
        for problem in report.problems:
            self.log.error(
                "dataset_keys_unusable",
                f"`{dataset.file_name}`: {problem}",
                ref=ref,
                cell_value=dataset.file_name,
                remedy="Fix the file and import again. The rest of the form was read "
                "regardless, so anything else below is still worth reading.",
            )
        for warning in report.warnings:
            self.log.warning(
                "dataset_keys_confusable",
                f"`{dataset.file_name}`: {warning}",
                ref=ref,
                cell_value=dataset.file_name,
            )
        for warning in dataset.warnings:
            self.log.warning("companion_file_note", warning, ref=ref)

    def _choice_filter(
        self, row: Row, node: dict[str, Any], name: str, dataset: ImportedDataset
    ) -> None:
        """Translate `choice_filter` into `choices.filter` (Form IR §3).

        Only for a dataset-backed list. §3 addresses a candidate row's columns
        as `$row.column`, and an inline list's items carry no columns to address
        — so a filter over one has nowhere to land, and stays reported as a
        column that was not imported.
        """
        cell = row.cells.get("choice_filter")
        if cell is None:
            return
        try:
            expression = translate(cell.value, self_path=name, row_scope=True)
        except ExpressionError as failure:
            if failure.function:
                self.instrumentation.note_function(failure.function)
            self.log.error(
                "untranslatable_expression",
                f"The `choice_filter` of `{name}` could not be translated: {failure}. "
                "Left out, every row of the list would be offered instead of the ones "
                "that match.",
                ref=cell.ref,
                cell_value=cell.value,
                node_id=name,
                remedy="Rewrite it using the functions this importer supports.",
            )
            return

        # A filter naming a column the file has not got would silently match
        # nothing, which on a phone is a list that is simply empty.
        columns = {
            ref[len("$row.") :]
            for ref in expr_references(expression)
            if ref.startswith("$row.")
        }
        unknown = sorted(c for c in columns if c not in dataset.columns)
        if unknown:
            self.log.error(
                "filter_column_not_in_dataset",
                f"The `choice_filter` of `{name}` matches on "
                + ", ".join(f"`{c}`" for c in unknown)
                + f", which `{dataset.file_name}` has no column for. Its columns are: "
                + ", ".join(f"`{c}`" for c in dataset.columns)
                + ". A filter on a column that is not there matches no rows, so the "
                "question would offer nothing.",
                ref=cell.ref,
                cell_value=cell.value,
                node_id=name,
                remedy="Check the column name against the file's header row.",
            )
            return

        node["choices"]["filter"] = expression
        self.ledger.consume(cell.ref)
        for column in sorted(columns):
            if column not in dataset.columns_used:
                dataset.columns_used.append(column)
        # Checked and rewritten once every question has been seen, like every
        # other expression: a filter may refer to a question further down.
        self.expression_cells.append(
            (node["choices"], "filter", cell.ref, cell.value, name)
        )

    def _choice_item(self, item: dict[str, Any]) -> dict[str, Any]:
        labels = dict(item["label"])
        if "default" in labels and len(labels) == 1:
            value = labels.pop("default")
            labels = {self.default_language or "en": value}
        elif "default" in labels:
            labels.pop("default")
        return {"value": item["value"], "label": labels}

    def _data_type(
        self, row: Row, type_cell: Cell, raw_type: str, name: str
    ) -> tuple[str | None, tuple[str, str] | None]:
        """The IR dataType, and where this question's options come from.

        The second element is `("inline", list_name)` for a list on the choices
        sheet and `("dataset", file_name)` for a companion CSV — Form IR §3's
        two kinds, decided here and nowhere else.
        """
        lowered = raw_type.lower()

        # Before the plain select patterns: `select_one_from_file x.csv` starts
        # with `select_one` only if you read it carelessly, and `_SELECT_ONE`
        # would happily match it and take `x.csv` for a choices-sheet list name.
        for pattern, kind in (
            (_SELECT_ONE_FROM_FILE, "select_one"),
            (_SELECT_MULTI_FROM_FILE, "select_multiple"),
        ):
            match = pattern.match(raw_type)
            if match:
                file_name = match.group(1)
                # Resolved here rather than after the node is built, so that a
                # file that did not arrive drops the question exactly as any
                # other unimportable row is dropped. Producing a select with no
                # choices block instead would be a question with no options in
                # valid IR — and a `relevant` pointing at it would resolve, so
                # the report would not even show the knock-on.
                already = file_name in self.unreadable_files
                if self._resolve_dataset(file_name, type_cell, name) is None:
                    cause = self.unreadable_files[file_name]
                    self.dropped_questions[name] = cause
                    if already:
                        # The file was explained against the first question that
                        # named it. This row still has to say something, or a
                        # question would be gone with nothing pointing at its
                        # row — which is the silent drop the ledger exists to
                        # catch, and did catch when this was missing.
                        self.log.error(
                            "question_without_its_dataset",
                            f"`{name}` also chooses from `{file_name}`, which could "
                            "not be used (see above), so this question was not "
                            "imported either.",
                            ref=type_cell.ref,
                            cell_value=raw_type,
                            node_id=name,
                            caused_by=cause,
                            blame="author",
                        )
                    return None, None
                return kind, ("dataset", file_name)

        for pattern, kind in (
            (_SELECT_ONE, "select_one"),
            (_SELECT_MULTI, "select_multiple"),
            (_SELECT_MULTI_LONG, "select_multiple"),
            (_SELECT_ONE_LONG, "select_one"),
        ):
            match = pattern.match(raw_type)
            if match:
                if pattern in (_SELECT_ONE_LONG, _SELECT_MULTI_LONG):
                    self.log.info(
                        "legacy_type_spelling",
                        f"`{raw_type}` is the older XLSForm spelling; read as "
                        f"`{kind} {match.group(1)}`.",
                        ref=type_cell.ref,
                        cell_value=raw_type,
                        node_id=name,
                    )
                return kind, ("inline", match.group(1))

        if lowered in ("calculate", "hidden"):
            return "text", None
        keyword = lowered.split()[0]

        if keyword in _NOT_IN_THE_IR:
            self.instrumentation.note_type(keyword)
            key = f"unsupported_type:{name}"
            self.dropped_questions[name] = key
            self.log.error(
                "unsupported_type",
                f"This question is {_NOT_IN_THE_IR[keyword]}, which this platform's "
                "form format has no way to represent, so it was not imported.",
                ref=type_cell.ref,
                cell_value=raw_type,
                node_id=name,
                blame="author",
                key=key,
                remedy="There is no equivalent planned, so this question needs "
                "rewriting — a `select_one` with a single option is the usual "
                "substitute for an acknowledgement.",
            )
            return None, None

        if keyword in _NOT_YET_IMPLEMENTED:
            self.instrumentation.note_type(keyword)
            key = f"unsupported_type:{name}"
            self.dropped_questions[name] = key
            self.log.error(
                "type_not_implemented",
                f"This question uses {_NOT_YET_IMPLEMENTED[keyword]}. That is a "
                "valid XLSForm type; this platform has not built it yet, so the "
                "question was not imported.",
                ref=type_cell.ref,
                cell_value=raw_type,
                node_id=name,
                blame="platform",
                key=key,
                remedy="Nothing is wrong with your spreadsheet. Either wait for this "
                "to be supported, or replace the question with a `select_one` and an "
                "inline choice list.",
            )
            return None, None

        simple = _SIMPLE_TYPES.get(lowered)
        if simple:
            return simple, None

        # Keyed on the construct rather than the whole cell, so the roadmap
        # aggregates. Two words when the first alone is meaningless — `begin
        # loop over toilet_type` is the deprecated loop construct, and filing it
        # under `begin` says nothing.
        words = lowered.split()
        roadmap_key = " ".join(words[:2]) if words[0] in ("begin", "end", "select") else words[0]
        self.instrumentation.note_type(roadmap_key)
        # Nothing recognised it, so this really may be a typo — and only here is
        # "check the spelling" an honest thing to say.
        diagnostic_key = f"unsupported_type:{name}"
        self.dropped_questions[name] = diagnostic_key
        self.log.error(
            "unknown_type",
            f"`{raw_type}` is not a question type this importer recognises, so `{name}` "
            "was not imported.",
            ref=type_cell.ref,
            cell_value=raw_type,
            node_id=name,
            blame="author",
            key=diagnostic_key,
            remedy="Check the spelling against the XLSForm type list.",
        )
        return None, None

    def _labels(
        self, row: Row, node_id: str | None, base: str = "label"
    ) -> tuple[dict[str, str], list[dict[str, Any]]]:
        """One text column across its languages, and the arguments it inserts.

        `${slope_radius}` becomes a `{0}` slot and an expression (Form IR §7.1).
        Slots are numbered from a list shared by every language, in order of
        first appearance across the languages sorted by name — so a translator
        who reorders the inserts still gets the right values, and two runs of
        this importer over the same workbook produce the same numbering.
        """
        found: dict[str, str] = {}
        sources: dict[str, tuple[str, CellRef]] = {}
        for column, cell in row.cells.items():
            column_base, language = _language_of(column)
            if column_base != base:
                continue
            self.ledger.consume(cell.ref)
            key = language or self.default_language or "en"
            if language:
                self.languages.add(language)
            sources[key] = (cell.value, cell.ref)

        # One argument list per node, so the order has to be decided across all
        # the languages at once rather than per column.
        order: list[str] = []
        for key in sorted(sources):
            for name in substitutions(sources[key][0]):
                if name not in order:
                    order.append(name)

        for key, (text, ref) in sources.items():
            found[key] = _to_slots(text, order) if order else text
            if order:
                # `node_id or ""` rather than a nullable: a label with slots is
                # always attached to a named node by the time it is registered,
                # and a nullable here would push the None three frames away to
                # the report.
                self.label_arg_cells.append((node_id or "", base, ref, text, order))

        args = [{"op": "ref", "path": name} for name in order]
        return found, args

    def _expressions(self, row: Row, node: dict[str, Any], name: str) -> None:
        # (column, IR key, severity when it will not translate)
        #
        # relevant and constraint are errors because dropping them changes what
        # is asked and what is checked, silently. `default` is a warning: the
        # question is still asked and still validated, it just starts empty.
        rules: list[tuple[str, str, str]] = [
            ("relevant", "relevant", "error"),
            ("constraint", "constraint", "error"),
            ("calculation", "calculate", "error"),
        ]
        # `default` is handled apart from the rest because in XLSForm it is
        # usually a literal value and only sometimes an expression: `18.31`,
        # `2010-06-15` and `a c` (two choices of a select_multiple) are all real
        # defaults from the ODK sample, and none of them is XPath. Parsing them
        # as expressions and reporting the failure would bury a form in
        # diagnostics about things that were never wrong.
        self._default(row, node, name)
        for column, key, severity in rules:
            cell = row.cells.get(column)
            if cell is None:
                continue
            try:
                node[key] = translate(cell.value, self_path=name)
                self.ledger.consume(cell.ref)
                # Remembered so its references can be rewritten and checked once
                # every question has been seen — a form may refer forward.
                self.expression_cells.append((node, key, cell.ref, cell.value, name))
            except ExpressionError as failure:
                if failure.function:
                    self.instrumentation.note_function(failure.function)
                consequence = {
                    "relevant": "the question would be shown to everybody",
                    "constraint": "the answer would not be checked at all",
                    "calculate": "the value would never be computed",
                    "default": "the question simply starts empty",
                }[key]
                self.log.add(
                    severity,  # type: ignore[arg-type]
                    "untranslatable_expression",
                    f"The `{column}` of `{name}` could not be translated: {failure}. "
                    f"Left out, {consequence}.",
                    ref=cell.ref,
                    cell_value=cell.value,
                    node_id=name,
                    remedy="Rewrite it using the functions this importer supports.",
                )

        for column, key in (
            ("constraint_message", "constraintMessage"),
            ("bind:jr:constraintmsg", "constraintMessage"),
        ):
            messages, message_args = self._labels(row, node_id=name, base=column)
            if messages:
                node[key] = messages
            if message_args:
                node[key + "Args"] = message_args

    def _default(self, row: Row, node: dict[str, Any], name: str) -> None:
        cell = row.cells.get("default")
        if cell is None:
            return
        text = cell.value
        looks_like_expression = "${" in text or "(" in text
        if looks_like_expression:
            try:
                node["default"] = translate(text, self_path=name)
                self.ledger.consume(cell.ref)
                self.expression_cells.append((node, "default", cell.ref, text, name))
                return
            except ExpressionError as failure:
                if failure.function:
                    self.instrumentation.note_function(failure.function)
                self.log.warning(
                    "untranslatable_expression",
                    f"The `default` of `{name}` could not be translated: {failure}. "
                    "Left out, the question simply starts empty.",
                    ref=cell.ref,
                    cell_value=text,
                    node_id=name,
                )
                return
        # A literal. Typed to match the question, so a default of `8` on an
        # integer is the number 8 and not the string "8" — the engine does no
        # implicit coercion (§4.5), so the wrong one would fail the constraint
        # it was meant to satisfy.
        node["default"] = {"op": "lit", "value": self._literal(text, node.get("dataType"))}
        self.ledger.consume(cell.ref)

    @staticmethod
    def _literal(text: str, data_type: str | None) -> Any:
        if data_type == "integer":
            try:
                return int(text)
            except ValueError:
                return text
        if data_type == "decimal":
            try:
                return float(text)
            except ValueError:
                return text
        if data_type == "select_multiple":
            # XLSForm separates the chosen values with spaces.
            return text.split()
        return text

    def _flags(self, row: Row, node: dict[str, Any], name: str) -> None:
        for column, key in (("required", "required"), ("readonly", "readOnly"),
                            ("read_only", "readOnly")):
            cell = row.cells.get(column)
            if cell is None:
                continue
            text = cell.value.strip().lower()
            if text in ("yes", "true", "true()", "1"):
                node[key] = True
                self.ledger.consume(cell.ref)
            elif text in ("no", "false", "false()", "0", ""):
                self.ledger.consume(cell.ref)
            else:
                try:
                    node[key] = translate(cell.value, self_path=name)
                    self.ledger.consume(cell.ref)
                except ExpressionError as failure:
                    if failure.function:
                        self.instrumentation.note_function(failure.function)
                    self.log.error(
                        "untranslatable_expression",
                        f"The `{column}` of `{name}` could not be translated: {failure}.",
                        ref=cell.ref,
                        cell_value=cell.value,
                        node_id=name,
                    )

    def _identifier(self, name: str, ref: CellRef, row: Row) -> str | None:
        """A legal Form IR id for this XLSForm name, or None if there is none.

        Reported when it changes, because the id is what an export column is
        called: an author reconciling a data file against their spreadsheet has
        to know that `numberAsString` arrives as `numberasstring`.
        """
        if _ID_PATTERN.match(name):
            return name
        slug = normalise_id(name)
        if not slug or not _ID_PATTERN.match(slug):
            self.log.error(
                "unusable_name",
                f"`{name}` cannot be turned into a valid identifier. Form IR §2.4 "
                "requires a name starting with a lowercase letter and made of "
                "letters, digits and underscores.",
                ref=ref,
                cell_value=name,
                remedy="Rename it, for example to `question_1`.",
            )
            return None
        if slug in self.question_ids:
            self.log.error(
                "name_collision_after_normalising",
                f"`{name}` becomes `{slug}` under Form IR §2.4, and another question "
                "already has that id. Renaming one of them automatically would "
                "scramble which answers belong to which question, so neither was.",
                ref=ref,
                cell_value=name,
                remedy=f"Rename `{name}` to something that is already distinct in lowercase.",
            )
            return None
        self.log.warning(
            "name_normalised",
            f"`{name}` is not a valid Form IR identifier (§2.4) and was imported as "
            f"`{slug}`. Exported data will use `{slug}` as the column name.",
            ref=ref,
            cell_value=name,
            node_id=slug,
        )
        return slug

    def _consume_remaining(
        self, row: Row, node_id: str | None, handled: set[str], quiet: bool = False
    ) -> None:
        """Account for every cell in the row that nothing above claimed.

        This is what stops a new column being ignored in silence. Anything not
        already consumed and not already reported gets a diagnostic here, so the
        ledger balances by construction rather than by discipline.
        """
        for column, cell in row.cells.items():
            if cell.ref in self.ledger._consumed or cell.ref in self.ledger._reported:
                continue
            base, _ = _language_of(column)
            if base in handled or column in handled:
                self.ledger.consume(cell.ref)
                continue
            if quiet:
                # The row produced no node at all and something else has already
                # said why; naming every one of its columns would bury that under
                # noise. `suppress`, not `report`: this must not count as an
                # explanation of the row, or dropping a row silently would be
                # indistinguishable from explaining it.
                self.ledger.suppress(cell.ref)
                continue
            reason = _KNOWN_IGNORED_COLUMNS.get(base) or _KNOWN_IGNORED_COLUMNS.get(column)
            self.instrumentation.note_column(base)
            if reason:
                self.log.warning(
                    "column_ignored",
                    f"`{column}` was not imported: {reason}.",
                    ref=cell.ref,
                    cell_value=cell.value,
                    node_id=node_id,
                )
            else:
                self.log.warning(
                    "unknown_column",
                    f"`{column}` is not a column this importer understands, so it was "
                    "not imported.",
                    ref=cell.ref,
                    cell_value=cell.value,
                    node_id=node_id,
                )


def _walk_nodes(nodes: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for node in nodes:
        yield node
        yield from _walk_nodes(node.get("children", []) or [])


def _to_slots(text: str, order: list[str]) -> str:
    """`${slope_radius}` -> `{0}`, and existing braces escaped (§7.1).

    The escaping matters and is easy to skip: a label that already contains a
    brace would otherwise gain a slot it never asked for.
    """
    escaped = text.replace("{", "{{").replace("}", "}}")
    for index, name in enumerate(order):
        for spelling in ("${" + name + "}", "${ " + name + " }"):
            escaped = escaped.replace(
                spelling.replace("{", "{{").replace("}", "}}"), "{" + str(index) + "}"
            )
    return escaped


def _from_slots(text: str, args: list[dict[str, Any]]) -> str:
    """Put `${name}` back, for text §7.1 does not give slots to."""
    out = text
    for index, arg in enumerate(args):
        out = out.replace("{" + str(index) + "}", "${" + str(arg["path"]) + "}")
    return out.replace("{{", "{").replace("}}", "}")


def _is_platform(importer: _Importer, missing: list[str]) -> bool:
    """True when every dropped target went because *we* cannot do something."""
    keys = [importer.dropped_questions.get(m) for m in missing]
    return all(
        any(d.key == k and d.blame == "platform" for d in importer.log.entries)
        for k in keys
        if k
    )


def _rewrite_refs(node: Any, renames: dict[str, str]) -> None:
    """Point every reference at the id its question actually got.

    Renaming a question without this would leave `relevant` pointing at a name
    nothing answers, which §4.2 makes a compile error — so it would be caught,
    loudly, rather than silently. It is done anyway because a form that refuses
    to compile with an unresolvable reference is a far worse report than one
    that says "we renamed this and followed it through".
    """
    if isinstance(node, dict):
        if node.get("op") == "ref":
            path = str(node.get("path", ""))
            head, _, tail = path.partition(".")
            if head in renames:
                node["path"] = renames[head] + ("." + tail if tail else "")
        for value in node.values():
            _rewrite_refs(value, renames)
    elif isinstance(node, list):
        for item in node:
            _rewrite_refs(item, renames)


def import_workbook(
    data: bytes,
    *,
    form_id: str | None = None,
    companions: dict[str, bytes] | None = None,
) -> ImportResult:
    """Turn an .xlsx into a Form IR document and a full account of the rest.

    [companions] is the files that ship *beside* the workbook — the CSVs a
    `select_one_from_file` names (Form IR §3). Keyed by file name as supplied;
    matched against the survey sheet case-insensitively, because the sheet was
    written on Windows and the server is not.

    Passing none is not the same as there being none. A form that names a
    companion file and is imported without it reports every one of them as
    missing, by name, rather than quietly producing questions with no options.
    """
    ledger = CoverageLedger()
    try:
        workbook = read(data, ledger)
    except WorkbookError as failure:
        raise ImportFailed(str(failure)) from failure

    importer = _Importer(ledger, companions)
    settings = importer.read_settings(workbook)
    importer.default_language = None
    declared_default = settings.get("default_language")

    importer.read_choices(workbook)
    children = importer.read_survey(workbook)

    for sheet_name in workbook.extra_sheets:
        importer.log.info(
            "sheet_ignored",
            f"The sheet `{sheet_name}` is not part of the XLSForm format and was not read.",
        )

    # Renames are applied after the whole survey is read, because a form may
    # refer forward to a question defined further down the sheet.
    if importer.renames:
        _rewrite_refs(children, importer.renames)

    # A reference to something no question answers is a compile error (§4.2).
    # Caught here so it can name the cell and the missing name, rather than
    # surfacing later as a bare CompileError with no provenance.
    known = importer.question_ids
    for node, key, ref, source, owner in importer.expression_cells:
        expression = node.get(key)
        if expression is None:
            continue
        missing = sorted(
            r.split(".")[0] for r in expr_references(expression)
            # `$row.x` is a column of the candidate row inside a choice filter,
            # never a question — the engine resolves it from the row and
            # `collect_refs` already excludes it from the dependency graph. It
            # was checked against the file's header when the filter was
            # translated, which is a stronger check than this one could be.
            if r.split(".")[0] not in known
            and not r.startswith("_")
            and not r.startswith("$row.")
        )
        if missing:
            node.pop(key, None)
            # Was the target dropped earlier, rather than never existing?
            #
            # Five of the UCL form's twenty-two errors were this: a `relevant`
            # pointing at a `select_one_from_file` question one or two rows
            # above, which we had refused. Counting those as five more problems
            # tells an author their form is a disaster when the truth is one
            # missing feature. They are reported under their cause instead.
            causes = {
                importer.dropped_questions[m]
                for m in missing
                if m in importer.dropped_questions
            }
            root = sorted(causes)[0] if len(causes) == 1 else None
            cascade = len(causes) == len(set(missing))
            importer.log.error(
                "unknown_reference",
                f"The `{key}` of `{owner}` refers to "
                + ", ".join(f"`{m}`" for m in missing)
                + (
                    ", which was not imported (see above), so this rule was dropped too."
                    if cascade
                    else ", which no question in this form answers."
                ),
                ref=ref,
                cell_value=source,
                node_id=owner,
                blame="platform" if cascade and _is_platform(importer, missing) else "author",
                caused_by=root if cascade else None,
                remedy=None
                if cascade
                else "Check the spelling, or the order of the questions.",
            )

    # A label inserting a name nothing answers (§7.1).
    #
    # Reported against the LABEL's cell, not the question's type cell: an author
    # with the workbook open is looking at the sentence they wrote, and "row 28,
    # column label::english (en)" is where the mistake is. Silent before §7.1 —
    # the text simply reached a respondent reading `${plot_id}`.
    #
    # The arguments are dropped and the original `${...}` text restored, so the
    # IR stays compilable and the report is the only thing that changes. A form
    # left with a dangling slot would fail to compile and bury this under a
    # second error about something the author did not write.
    for owner_id, base, ref_cell, source, order in importer.label_arg_cells:
        missing_names = sorted(
            name for name in order
            if name.split(".")[0] not in known and not name.startswith("_")
        )
        if not missing_names:
            continue
        target = next(
            (n for n in _walk_nodes(children) if n.get("id") == owner_id), None
        )
        if target is not None:
            args_key = "labelArgs" if base == "label" else "constraintMessageArgs"
            text_key = "label" if base == "label" else "constraintMessage"
            target.pop(args_key, None)
            if isinstance(target.get(text_key), dict):
                target[text_key] = {
                    language: _from_slots(text, [{"path": n} for n in order])
                    for language, text in target[text_key].items()
                }
        cause = {
            importer.dropped_questions[m]
            for m in missing_names
            if m in importer.dropped_questions
        }
        importer.log.error(
            "unknown_reference_in_label",
            f"This {base} inserts the answer to "
            + ", ".join(f"`${{{m}}}`" for m in missing_names)
            + (
                ", which was not imported (see above), so the insert was left as "
                "written."
                if cause
                else ", which no question in this form answers, so a respondent "
                "would read it literally."
            ),
            ref=ref_cell,
            cell_value=source,
            node_id=owner_id or None,
            caused_by=sorted(cause)[0] if len(cause) == 1 else None,
            blame="platform" if cause else "author",
            remedy=None if cause else "Check the spelling, or the order of the questions.",
        )

    # A file supplied that nothing asked for. Almost always a filename typo on
    # one side or the other, and the symptom without this is a question whose
    # list is "missing" while the list is sitting right there in the upload.
    referenced = {name.casefold() for name in importer.datasets}
    referenced |= {name.casefold() for name in importer.unreadable_files}
    for supplied in sorted(importer.companions):
        if supplied.casefold() in referenced:
            continue
        wanted = sorted(
            {d.file_name for d in importer.datasets.values()} | set(importer.unreadable_files)
        )
        importer.log.warning(
            "companion_file_unused",
            f"`{supplied}` was supplied but no question refers to it, so it was not "
            "read and nothing will be published from it."
            + (
                " The files this form does ask for are: "
                + ", ".join(f"`{n}`" for n in wanted)
                + "."
                if wanted
                else " This form refers to no companion files at all."
            ),
            remedy="Check the file name against the `select_one_from_file` rows on "
            "the survey sheet — a mismatch is usually a rename on one side.",
        )

    unused = set(importer.choice_lists) - importer.used_choice_lists
    for list_name in sorted(unused):
        # Unused because its questions were dropped, or unused on its own?
        # The UCL form's `plot` list is the first kind, and reporting it as an
        # independent finding inflates the count with a consequence.
        users = importer.choice_list_users.get(list_name, [])
        causes = {importer.dropped_questions[u] for u in users if u in importer.dropped_questions}
        cascade = bool(users) and len(causes) >= 1 and all(
            u in importer.dropped_questions for u in users
        )
        rows = importer.choice_list_rows.get(list_name) or []
        importer.log.warning(
            "unused_choice_list",
            f"The choice list `{list_name}` is defined but no question uses it"
            + (
                " — the questions that used it were not imported (see above)."
                if cascade
                else "."
            ),
            ref=rows[0] if rows else None,
            caused_by=sorted(causes)[0] if cascade and len(causes) == 1 else None,
            blame="platform" if cascade else "author",
        )

    languages = sorted(importer.languages)
    if declared_default:
        tagged = re.search(r"\(([A-Za-z-]{2,})\)\s*$", declared_default)
        default_language = (tagged.group(1).lower() if tagged else declared_default.lower())
    else:
        default_language = languages[0] if languages else "en"
    if default_language not in languages:
        languages = [default_language] + languages

    form: dict[str, Any] = {
        "irVersion": "0.1",
        "formId": form_id or settings.get("form_id") or "imported_form",
        "version": int(settings.get("version") or 1)
        if str(settings.get("version") or 1).isdigit()
        else 1,
        "title": {default_language: settings.get("form_title") or "Imported form"},
        "defaultLanguage": default_language,
        "languages": languages,
        "children": children,
    }
    _retag_default_labels(form["children"], default_language)
    for dataset in importer.datasets.values():
        if "default" in dataset.label_columns:
            dataset.label_columns[default_language] = dataset.label_columns.pop("default")

    # A form with no questions in it.
    #
    # The coverage ledger cannot see this one, and that is worth saying out
    # loud: the ledger proves every cell was accounted for, and an empty sheet
    # has no cells to account for. It was found by importing the official ODK
    # XLSForm Template, which is a *blank* template — 499 rows by Excel's
    # reckoning and not one of them with content — and getting back a valid,
    # compilable, publishable form with nothing in it.
    #
    # That is the silent drop in its purest form: not one question lost but all
    # of them, with every check green. So it is checked directly rather than
    # inferred from coverage.
    question_count = _count_questions(children)
    if question_count == 0:
        importer.log.error(
            "no_questions",
            "This workbook produced no questions. Its `survey` sheet has column "
            "headers but no rows with content, so there is nothing to collect.",
            remedy="Check that the questions are on a sheet named `survey`, and that "
            "this is a filled-in form rather than a blank template.",
        )

    # Nested repeats, named before the engine gets to them.
    #
    # The engine refuses these, and its refusal is correct, but it arrives as a
    # sentence about the IR with no row and no idea whose problem it is. Form IR
    # §2.3 says nested repeats are "deferred to v0.2" — so the author has
    # written valid XLSForm and *we* have not built it, which is the opposite
    # of what a generic compile error implies.
    for outer, inner in _nested_repeats(children):
        importer.log.error(
            "nested_repeat_not_supported",
            f"`{inner}` is a repeat inside the repeat `{outer}`. That is valid "
            "XLSForm; this platform's form format defers nested repeats to a "
            "later version (Form IR §2.3), so the form cannot be imported as it "
            "stands.",
            ref=CellRef(SURVEY_SHEET, importer.node_rows[inner], "type")
            if inner in importer.node_rows
            else None,
            node_id=inner,
            blame="platform",
            key=f"nested_repeat:{inner}",
            remedy="Nothing is wrong with your spreadsheet. Until nested repeats "
            "are supported, the inner repeat has to be flattened into the outer "
            "one or split into a second form.",
        )

    # Does the IR we just produced actually compile?
    #
    # Enumerating every IR-level rule here would be a second copy of the engine,
    # and the copy that goes stale. Asking the engine is both shorter and
    # stronger: whatever it refuses, the author is told about, in the report,
    # instead of finding out when the publish endpoint returns a 500.
    #
    # Found by importing a real form — the UCL biomass survey nests a repeat
    # inside a repeat, which IR v0.1 does not support. Without this the importer
    # cheerfully returned IR that could not be compiled and called it
    # publishable.
    try:
        from app.modules.form_engine.runtime import CompiledForm

        CompiledForm(form)
    except Exception as failure:  # noqa: BLE001 - any refusal is the author's problem
        # The engine names the node it refused ("repeat 'stems'"), so the row
        # it came from is knowable — and an author with the file open should
        # not have to hunt for it.
        named = re.findall(r"'([A-Za-z_][\w]*)'", str(failure))
        row_number = next(
            (importer.node_rows[n] for n in named if n in importer.node_rows), None
        )
        # If something above already explained this refusal in specific terms,
        # this is the same finding in the engine's words. Reported as a
        # consequence rather than as a second problem.
        already = next(
            (
                d.key
                for d in importer.log.entries
                if d.severity == "error" and d.node_id and d.node_id in named and d.key
            ),
            None,
        )
        importer.log.error(
            "does_not_compile",
            "The imported form does not compile: "
            f"{failure}. This is a limit of the form format rather than of the "
            "importer, so the form needs changing before it can be used.",
            ref=CellRef(SURVEY_SHEET, row_number, "type") if row_number else None,
            caused_by=already,
            blame="platform" if already else "author",
            remedy=None if already else "Simplify the structure the message names.",
        )

    dropped_rows = ledger.row_residue(SURVEY_SHEET)
    if dropped_rows:
        raise CoverageHole(
            f"{len(dropped_rows)} survey row(s) produced no node and no diagnostic, "
            f"the first being row {dropped_rows[0]}. A question that is neither "
            "imported nor reported is the silent drop this ledger exists to prevent. "
            "This is an importer bug, not a problem with the form."
        )

    residue = ledger.residue
    if residue:
        raise CoverageHole(
            "the importer produced no IR and no diagnostic for "
            f"{len(residue)} cell(s), the first being {residue[0]}. Every cell must be "
            "consumed or reported — see workbook.CoverageLedger. This is an importer "
            "bug, not a problem with the form."
        )

    survey_sheet = workbook.sheet(SURVEY_SHEET)
    return ImportResult(
        form=form,
        diagnostics=importer.log.entries,
        instrumentation=importer.instrumentation,
        coverage=ledger.counts,
        survey_rows=sum(1 for r in (survey_sheet.rows if survey_sheet else []) if not r.is_empty),
        nodes=_count_nodes(children),
        questions=question_count,
        publishable=not importer.log.has_errors,
        languages=languages,
        # In the order the survey sheet first referred to them, which is the
        # order a person reads the form in. `dict` preserves insertion order.
        datasets=list(importer.datasets.values()),
    )


def _retag_default_labels(nodes: list[dict[str, Any]], language: str) -> None:
    """Move `default`-keyed strings onto the real default language.

    A single-language form has no `label::x` columns at all, so the labels come
    back under a placeholder key. Rewriting them here keeps every other part of
    the importer from having to know whether the form was translated.
    """
    for node in nodes:
        for key in ("label", "hint", "constraintMessage"):
            value = node.get(key)
            if isinstance(value, dict) and "default" in value:
                text = value.pop("default")
                value.setdefault(language, text)
        # `labelColumn` is the same shape and the same placeholder: a CSV with a
        # plain `label` column and no language suffix (species names have no
        # language) comes back keyed `default` exactly as a label does.
        choices = node.get("choices")
        if isinstance(choices, dict):
            columns = choices.get("labelColumn")
            if isinstance(columns, dict) and "default" in columns:
                columns.setdefault(language, columns.pop("default"))
        if node.get("children"):
            _retag_default_labels(node["children"], language)


def _nested_repeats(
    nodes: list[dict[str, Any]], inside: str | None = None
) -> list[tuple[str, str]]:
    """(outer, inner) for every repeat nested in another (Form IR §2.3)."""
    found: list[tuple[str, str]] = []
    for node in nodes:
        kind = node.get("type")
        if kind == "repeat":
            if inside is not None:
                found.append((inside, str(node.get("id"))))
            found += _nested_repeats(node.get("children") or [], str(node.get("id")))
        elif node.get("children"):
            found += _nested_repeats(node["children"], inside)
    return found


def _count_questions(nodes: list[dict[str, Any]]) -> int:
    """Question nodes only — groups and repeats collect nothing themselves."""
    total = 0
    for node in nodes:
        if node.get("type") == "question":
            total += 1
        if node.get("children"):
            total += _count_questions(node["children"])
    return total


def _count_nodes(nodes: list[dict[str, Any]]) -> int:
    total = 0
    for node in nodes:
        total += 1
        if node.get("children"):
            total += _count_nodes(node["children"])
    return total
