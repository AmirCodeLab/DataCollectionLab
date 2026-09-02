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
from dataclasses import dataclass, field
from typing import Any

from . import datatypes
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
    "choice_filter": "cascading choice filters are not implemented",
    "parameters": "widget parameters are not implemented",
    "trigger": "recalculation triggers are inferred from the dependency graph (§5.1)",
    "repeat_count": "repeat bounds are not imported yet",
    "instance_name": "instance naming is not implemented",
    "body::accuracythreshold": "GPS accuracy is a project setting, not a form one",
    "autoplay": "media autoplay is not implemented",
    "image": "question media is not imported",
    "audio": "question media is not imported",
    "video": "question media is not imported",
    "rows": "textarea sizing is a display hint the IR does not carry",
    "read_only": "handled as `readonly`",
}

_SELECT_ONE = re.compile(r"^select_one\s+(\S+)", re.IGNORECASE)
_SELECT_MULTI = re.compile(r"^select_multiple\s+(\S+)", re.IGNORECASE)
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
    def __init__(self, ledger: CoverageLedger) -> None:
        self.ledger = ledger
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
                stack[-1].append(node)
                stack.append(node["children"])
                open_containers.append((node["id"], type_cell.ref))
                continue

            if lowered in ("end group", "end_group", "end repeat", "end_repeat"):
                self.ledger.consume(type_cell.ref)
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
        labels = self._labels(row, node_id=name)
        if labels:
            node["label"] = labels
        self._consume_remaining(row, node_id=name, handled={"type", "name"})
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

        data_type, choice_list = self._data_type(row, type_cell, raw_type, name)
        if data_type is None:
            self._consume_remaining(row, node_id=name, handled={"type", "name"}, quiet=True)
            return None

        self.ledger.consume(type_cell.ref)
        if name_cell:
            self.ledger.consume(name_cell.ref)
        self.question_ids.add(name)

        node: dict[str, Any] = {"type": "question", "id": name, "dataType": data_type}

        labels = self._labels(row, node_id=name)
        if labels:
            node["label"] = labels
        hints = self._labels(row, node_id=name, base="hint")
        if hints:
            node["hint"] = hints

        if choice_list is not None:
            self.used_choice_lists.add(choice_list)
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
    ) -> tuple[str | None, str | None]:
        lowered = raw_type.lower()

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
                return kind, match.group(1)

        if lowered in ("calculate", "hidden"):
            return "text", None
        if lowered in ("trigger", "acknowledge"):
            self.instrumentation.note_type(lowered)
            self.log.error(
                "unsupported_type",
                f"`{raw_type}` has no equivalent in the Form IR, so `{name}` was not "
                "imported. It is an acknowledgement widget rather than a question.",
                ref=type_cell.ref,
                cell_value=raw_type,
                node_id=name,
                remedy="Use a `select_one` with a single option, or remove the row.",
            )
            return None, None

        simple = _SIMPLE_TYPES.get(lowered)
        if simple:
            return simple, None

        # Keyed on the construct rather than the whole cell, so the roadmap
        # aggregates: five rows of `select_one_from_file X.csv` with five
        # different filenames are one missing feature, not five. Two words when
        # the first alone is meaningless — `begin loop over toilet_type` is the
        # deprecated loop construct, and filing it under `begin` says nothing.
        words = lowered.split()
        key = " ".join(words[:2]) if words[0] in ("begin", "end", "select") else words[0]
        self.instrumentation.note_type(key)
        self.log.error(
            "unsupported_type",
            f"`{raw_type}` is not a question type this importer knows, so `{name}` "
            "was not imported.",
            ref=type_cell.ref,
            cell_value=raw_type,
            node_id=name,
            remedy="Check the spelling against the XLSForm type list.",
        )
        return None, None

    def _labels(self, row: Row, node_id: str | None, base: str = "label") -> dict[str, str]:
        found: dict[str, str] = {}
        for column, cell in row.cells.items():
            column_base, language = _language_of(column)
            if column_base != base:
                continue
            self.ledger.consume(cell.ref)
            key = language or self.default_language or "en"
            if language:
                self.languages.add(language)
            text = cell.value
            outputs = substitutions(text)
            if outputs:
                inserted = ", ".join("${" + o + "}" for o in outputs)
                self.log.error(
                    "output_in_label",
                    f"This {base} inserts the answer to {inserted}. "
                    "The Form IR carries plain text (§7), so a respondent would see "
                    "the ${...} literally.",
                    ref=cell.ref,
                    cell_value=text,
                    node_id=node_id,
                    remedy="Rewrite the text without the ${...} insert.",
                )
            found[key] = text
        return found

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
            messages = self._labels(row, node_id=name, base=column)
            if messages:
                node[key] = messages

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
                # The row produced no node at all and has already been reported;
                # naming every one of its columns would bury that under noise.
                self.ledger.report(cell.ref)
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


def import_workbook(data: bytes, *, form_id: str | None = None) -> ImportResult:
    """Turn an .xlsx into a Form IR document and a full account of the rest."""
    ledger = CoverageLedger()
    try:
        workbook = read(data, ledger)
    except WorkbookError as failure:
        raise ImportFailed(str(failure)) from failure

    importer = _Importer(ledger)
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
            if r.split(".")[0] not in known and not r.startswith("_")
        )
        if missing:
            node.pop(key, None)
            importer.log.error(
                "unknown_reference",
                f"The `{key}` of `{owner}` refers to "
                + ", ".join(f"`{m}`" for m in missing)
                + ", which no question in this form answers.",
                ref=ref,
                cell_value=source,
                node_id=owner,
                remedy="Check the spelling, or the order of the questions.",
            )

    unused = set(importer.choice_lists) - importer.used_choice_lists
    for list_name in sorted(unused):
        importer.log.warning(
            "unused_choice_list",
            f"The choice list `{list_name}` is defined but no question uses it.",
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
        importer.log.error(
            "does_not_compile",
            "The imported form does not compile: "
            f"{failure}. This is a limit of the Form IR rather than of the "
            "importer, so the form needs changing before it can be used.",
            remedy="Simplify the structure the message names.",
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
        if node.get("children"):
            _retag_default_labels(node["children"], language)


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
