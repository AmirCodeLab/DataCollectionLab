"""Dataset-backed choice lists: decomposing a filter, and asking for rows.

Form IR §3.2. The reference implementation of the rule that makes a 38,000-row
village list usable on a handset, which is not an optimisation but a shape:

**The engine never materialises a dataset.** It decomposes `choices.filter`
once, at compile time, into the part a store can answer from an index and the
part it cannot, then asks a `DatasetSource` for rows.

    filter:   $row.district_id = ${district} and $row.population > 1000
    selector: {"district_id": <expr for ${district}>}   <- indexed lookup
    residual: $row.population > 1000                    <- evaluated per row

Everything that decides *what the list is* stays here, in the engine, where a
conformance vector can compare two implementations. The source decides only how
quickly it can find rows — never which rows exist. That asymmetry is the whole
design, and §3.2 spells out why: which rows are candidates is a *which-artifact*
decision, and a vector fixes the inputs so it cannot see a caller choosing them.
A client permitted to pre-narrow would be a client deciding the choice list, and
two clients narrowing differently would both pass every vector.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

ROW_PREFIX = "$row."


def _row_column(expr: Any) -> str | None:
    """The column name when [expr] is exactly `$row.something`, else None."""
    if not isinstance(expr, dict) or expr.get("op") != "ref":
        return None
    path = str(expr.get("path", ""))
    return path[len(ROW_PREFIX) :] if path.startswith(ROW_PREFIX) else None


def _mentions_row(expr: Any) -> bool:
    """Whether `$row` appears anywhere in this subtree.

    Checked over the whole subtree rather than at the top: `$row.a = 1 + $row.b`
    has no `$row` at either end of the `eq` and is still not a selector term.
    """
    if isinstance(expr, dict):
        if expr.get("op") == "ref" and str(expr.get("path", "")).startswith(ROW_PREFIX):
            return True
        return any(_mentions_row(arg) for arg in expr.get("args", []) or [])
    if isinstance(expr, list):
        return any(_mentions_row(item) for item in expr)
    return False


def _conjuncts(expr: Any) -> list[Any]:
    """Top-level `and` flattened, fully. Nothing else decomposes (§3.2)."""
    if isinstance(expr, dict) and expr.get("op") == "and":
        found: list[Any] = []
        for arg in expr.get("args", []) or []:
            found.extend(_conjuncts(arg))
        return found
    return [expr]


@dataclass(frozen=True)
class ChoiceQuery:
    """A dataset-backed `choices` block, compiled (§3.2).

    Immutable and computed once per field at compile time, because it is a pure
    function of the IR: the same document must decompose the same way on every
    engine, and a vector asserts that it did.
    """

    dataset: str
    value_column: str
    label_columns: Mapping[str, str] = field(default_factory=dict)
    #: Column -> the expression whose value that column must equal. Ordered by
    #: column name so two engines emit it identically.
    selector: Mapping[str, Any] = field(default_factory=dict)
    #: What the selector could not absorb, as one expression, or None.
    residual: Any | None = None

    @property
    def scans(self) -> bool:
        """True when nothing narrows and resolution is O(dataset).

        Named rather than inferred, because §3.2's contract is that an engine
        *says* a filter is a full scan instead of quietly performing one.
        """
        return not self.selector


def compile_choices(choices: Mapping[str, Any]) -> ChoiceQuery | None:
    """Decompose a `choices.kind = "dataset"` block, or None if it is inline."""
    if choices.get("kind") != "dataset":
        return None

    selector: dict[str, Any] = {}
    residuals: list[Any] = []
    for conjunct in _conjuncts(choices.get("filter")) if choices.get("filter") else []:
        column = _selector_term(conjunct)
        # First binding wins; a column bound twice sends its later bindings to
        # the residual. Nothing is merged and nothing is called contradictory —
        # `$row.a = 1 and $row.a = 2` selects on 1 and finds nothing, which is
        # the right answer and not an error.
        if column is not None and column[0] not in selector:
            selector[column[0]] = column[1]
        else:
            residuals.append(conjunct)

    residual: Any | None = None
    if len(residuals) == 1:
        residual = residuals[0]
    elif residuals:
        residual = {"op": "and", "args": residuals}

    return ChoiceQuery(
        dataset=str(choices.get("dataset", "")),
        value_column=str(choices.get("valueColumn", "")),
        label_columns=dict(choices.get("labelColumn") or {}),
        # Sorted, so the selector two engines produce is comparable as data
        # rather than only in its effect.
        selector={key: selector[key] for key in sorted(selector)},
        residual=residual,
    )


def _selector_term(conjunct: Any) -> tuple[str, Any] | None:
    """`(column, expression)` when this conjunct is `$row.col = <no $row>`."""
    if not isinstance(conjunct, dict) or conjunct.get("op") != "eq":
        return None
    args = conjunct.get("args") or []
    if len(args) != 2:
        return None
    for index in (0, 1):
        column = _row_column(args[index])
        other = args[1 - index]
        if column is not None and not _mentions_row(other):
            return column, other
    return None


class DatasetSource(Protocol):
    """Where an engine gets dataset rows from.

    One method on purpose. `equals` is the additional equality a membership
    check needs (§6.3), passed through rather than applied afterwards so that a
    store can answer the whole question from one index: with no residual,
    "is this answer in the list" is a single lookup whatever the dataset's size.

    An implementation may be as fast as it likes and must not be selective —
    it answers exactly the rows matching what it was asked, in dataset order.
    """

    def rows(
        self,
        dataset: str,
        selector: Mapping[str, Any],
        equals: tuple[str, Any] | None = None,
    ) -> Sequence[Mapping[str, Any]]: ...


class InMemoryDatasetSource:
    """Every row in memory. The conformance harness, the server, small lists.

    Exact rather than fast, deliberately: this is the implementation the vectors
    compare against, so it must be the plainest possible reading of §3.2. A
    device-side source backed by SQLCipher answers the same questions from an
    index and must agree with it row for row.
    """

    def __init__(self, datasets: Mapping[str, Iterable[Mapping[str, Any]]]) -> None:
        self._datasets = {key: list(rows) for key, rows in datasets.items()}

    def rows(
        self,
        dataset: str,
        selector: Mapping[str, Any],
        equals: tuple[str, Any] | None = None,
    ) -> Sequence[Mapping[str, Any]]:
        found = self._datasets.get(dataset)
        if found is None:
            # An unknown key is an empty list, not a crash. A device that has
            # not yet synced a dataset holds no rows for it, and the question
            # must still answer — as a select with nothing to choose from,
            # which is visible, rather than as an exception in recalculation.
            return []
        matched = [row for row in found if _matches(row, selector)]
        if equals is not None:
            column, value = equals
            matched = [row for row in matched if _same(row.get(column), value)]
        return matched


def _matches(row: Mapping[str, Any], selector: Mapping[str, Any]) -> bool:
    return all(_same(row.get(column), value) for column, value in selector.items())


def _same(cell: Any, value: Any) -> bool:
    """Exact match, the same rule as §6.3 — no trimming, no case folding.

    Numbers are compared to their string form as well, because a CSV holds text
    and an answer set from a `calculate` may be a number. That is a narrow
    accommodation, not a coercion: `1` matches the cell `"1"` and nothing else
    about the null and comparison rules of §4.4 changes.
    """
    if cell == value:
        return True
    if cell is None or value is None:
        return False
    if isinstance(value, bool) or isinstance(cell, bool):
        return False
    if isinstance(value, int | float) and isinstance(cell, str):
        return cell == _plain(value)
    if isinstance(cell, int | float) and isinstance(value, str):
        return value == _plain(cell)
    return False


def _plain(number: int | float) -> str:
    """`1` not `1.0`, so an integer-valued float matches an integer cell."""
    if isinstance(number, float) and number.is_integer():
        return str(int(number))
    return str(number)
