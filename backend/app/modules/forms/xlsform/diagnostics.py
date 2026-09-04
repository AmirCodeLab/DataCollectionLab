"""What an import found, as data rather than prose.

Every diagnostic carries where it happened — sheet, row, column, and the value
that was actually in the cell — as separate fields. Not formatted into a
sentence: a console wants to link to `survey!H14`, a report generator wants to
group by sheet, and a person emailing the author wants the whole thing in a
table. A string that says "row 14, column relevant: ..." can serve exactly one
of those and has to be parsed to serve the others.

## The severity rule

Severity is decided by consequence, not by feel, because the whole point is
that an author can act on it:

  error    would change what data is collected, or whether a question is asked.
           The form still imports — the author needs every problem in one pass,
           not one per round trip — but the version is not publishable.
  warning  cosmetic or advisory; the collected data is the same either way.
  info     handled, but mapped to something near rather than exact.

An untranslatable `relevant` is an **error**, not a warning. Dropping it makes
a question that should have been conditional permanently visible, which is
silent in exactly the way this module exists to prevent. The same goes for
`constraint`: dropped, it becomes `true` and validation is simply gone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .workbook import CellRef, CoverageLedger

Severity = Literal["error", "warning", "info"]

#: Whose problem it is, which is the first thing an author needs to know.
#:
#: `platform` means we cannot do this yet: the form is correct XLSForm and the
#: fix is on our side. `author` means something in the spreadsheet needs
#: changing. Getting this wrong costs somebody an evening trying to fix
#: something they cannot fix — `select_one_from_file` is spelled correctly, is
#: a real XLSForm type, and was being reported with "check the spelling".
Blame = Literal["platform", "author"]


@dataclass
class Diagnostic:
    severity: Severity
    #: Machine-readable and stable — the console groups on it, and it is what a
    #: roadmap is counted from. Human wording lives in `message` and may change.
    code: str
    message: str
    ref: CellRef | None = None
    #: What was actually in the cell, so the author does not have to go and look.
    cell_value: str | None = None
    #: Where this would have landed in the IR, when that is known.
    node_id: str | None = None
    #: What to do about it, when there is something specific to say.
    remedy: str | None = None
    #: Whose problem this is. Defaults to the author's, because most findings
    #: are, and a platform limitation has to be claimed deliberately.
    blame: Blame = "author"
    #: The root this descends from, when it is a knock-on rather than a finding
    #: of its own.
    #:
    #: A reference that fails because its target was dropped two rows earlier is
    #: not a second problem, and counting it as one is how a form with one
    #: missing feature is reported as twenty-two problems. The author is told
    #: about it under its cause, and the headline count is root causes.
    caused_by: str | None = None
    #: This diagnostic's own key, for others to point at.
    key: str | None = None


class DiagnosticLog:
    """Collects diagnostics and keeps the coverage ledger honest.

    Reporting a diagnostic against a cell is what marks that cell accounted
    for, so the two cannot drift: there is no way to tell the author about a
    cell without also satisfying the ledger, and no way to satisfy the ledger
    by claiming to have reported something that was never written down.
    """

    def __init__(self, ledger: CoverageLedger) -> None:
        self._ledger = ledger
        self.entries: list[Diagnostic] = []

    def add(
        self,
        severity: Severity,
        code: str,
        message: str,
        *,
        ref: CellRef | None = None,
        cell_value: str | None = None,
        node_id: str | None = None,
        remedy: str | None = None,
        blame: Blame = "author",
        caused_by: str | None = None,
        key: str | None = None,
    ) -> Diagnostic:
        diagnostic = Diagnostic(
            severity=severity,
            code=code,
            message=message,
            ref=ref,
            cell_value=cell_value,
            node_id=node_id,
            remedy=remedy,
            blame=blame,
            caused_by=caused_by,
            key=key,
        )
        self.entries.append(diagnostic)
        if ref is not None:
            self._ledger.report(ref)
        return diagnostic

    def error(self, code: str, message: str, **kwargs: Any) -> Diagnostic:
        return self.add("error", code, message, **kwargs)

    def warning(self, code: str, message: str, **kwargs: Any) -> Diagnostic:
        return self.add("warning", code, message, **kwargs)

    def info(self, code: str, message: str, **kwargs: Any) -> Diagnostic:
        return self.add("info", code, message, **kwargs)

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.entries if d.severity == "error"]

    @property
    def root_errors(self) -> list[Diagnostic]:
        """Errors that are not a knock-on of another error.

        What an author should be told they have to deal with. The cascades are
        still reported, under their cause, because "and these five stopped
        working too" is information — it is just not five more problems.
        """
        return [d for d in self.entries if d.severity == "error" and d.caused_by is None]

    @property
    def has_errors(self) -> bool:
        return any(d.severity == "error" for d in self.entries)

    def counts(self) -> dict[str, int]:
        return {
            "error": sum(1 for d in self.entries if d.severity == "error"),
            "warning": sum(1 for d in self.entries if d.severity == "warning"),
            "info": sum(1 for d in self.entries if d.severity == "info"),
        }


@dataclass
class Instrumentation:
    """What the form actually needed that we could not give it.

    Kept apart from the diagnostics because it answers a different question. A
    diagnostic tells one author about one form; this tells us which XPath
    functions and which question types real forms reach for, which is the
    priority order for what to implement next. Guessing that order from the
    XLSForm specification produces a different answer from counting it across
    forms people have actually written.
    """

    #: XPath function name -> how many cells used it.
    unsupported_functions: dict[str, int] = field(default_factory=dict)
    #: XLSForm type -> how many rows used it, for types that produced no node.
    unsupported_types: dict[str, int] = field(default_factory=dict)
    #: dataType -> row count, for types that imported but no device can collect.
    uncollectable_types: dict[str, int] = field(default_factory=dict)
    #: Column name -> row count, for columns nothing here understands.
    ignored_columns: dict[str, int] = field(default_factory=dict)

    def note_function(self, name: str) -> None:
        self.unsupported_functions[name] = self.unsupported_functions.get(name, 0) + 1

    def note_type(self, name: str) -> None:
        self.unsupported_types[name] = self.unsupported_types.get(name, 0) + 1

    def note_uncollectable(self, name: str) -> None:
        self.uncollectable_types[name] = self.uncollectable_types.get(name, 0) + 1

    def note_column(self, name: str) -> None:
        self.ignored_columns[name] = self.ignored_columns.get(name, 0) + 1
