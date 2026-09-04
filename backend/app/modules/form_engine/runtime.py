"""Form runtime: dependency graph, repeat instances, deterministic recalculation.

Spec: specs/form-ir-v0.1.md sections 2.3, 4.2, 5.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from .datasets import ChoiceQuery, DatasetSource, InMemoryDatasetSource, compile_choices
from .document import check_document
from .expression import (
    CompileError,
    EvalContext,
    cast_str,
    coerce_boolean,
    collect_refs,
    evaluate,
)
from .text import render_field_text, slot_indices

ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
#: An instance id this engine minted. Ids from a device may look like
#: anything else, and `_restore_instance` leaves those alone.
SERIAL_ID = re.compile(r"i(\d+)")

#: Distinguishes "no additional equality" from "equal to None", which are
#: different questions to ask a source: the first returns the whole selected
#: list, the second asks whether a null answer is a member of it.
_UNSET = object()


@dataclass
class FieldState:
    path: str
    data_type: str
    relevant: bool = True
    required: bool = False
    read_only: bool = False
    value: Any = None
    valid: bool = True
    errors: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "relevant": self.relevant,
            "required": self.required,
            "readOnly": self.read_only,
            "value": self.value,
            "valid": self.valid,
            "errors": self.errors,
        }


@dataclass
class CompiledField:
    field_id: str
    node: dict[str, Any]
    data_type: str
    depends_on: set[str]
    ancestors: list[str]
    repeat: str | None  # innermost enclosing repeat id, if any
    #: A dataset-backed `choices` block, decomposed (§3.2). None for an inline
    #: list or no list at all. Computed at compile time because it is a pure
    #: function of the IR: the same document must decompose the same way on
    #: every engine, and a vector asserts that it did.
    choice_query: ChoiceQuery | None = None


class CompiledForm:
    """A validated form with its dependency graph resolved."""

    def __init__(self, ir: dict[str, Any]) -> None:
        # §10.1 first, over the raw document. Everything below this line — and
        # every semantic check in _compile — may assume the keys it reads exist
        # and hold what they say they do. Without it `ir["formId"]` on the next
        # line is a KeyError on any document that is not a form.
        check_document(ir)

        self.ir = ir
        self.form_id: str = ir["formId"]
        self.version: int = ir["version"]
        self.fields: dict[str, CompiledField] = {}
        self.containers: dict[str, dict[str, Any]] = {}
        self.repeats: dict[str, dict[str, Any]] = {}
        self.warnings: list[str] = []
        self.order: list[str] = []
        self._compile()

    def _walk(
        self, nodes: list[dict[str, Any]], ancestors: list[str]
    ) -> Iterator[tuple[dict[str, Any], list[str]]]:
        for node in nodes:
            yield node, ancestors
            if node["type"] in ("group", "repeat"):
                yield from self._walk(node.get("children", []), ancestors + [node["id"]])

    def _compile(self) -> None:
        seen: set[str] = set()

        for node, ancestors in self._walk(self.ir.get("children", []), []):
            node_id = node["id"]
            if not ID_PATTERN.match(node_id):
                raise CompileError(f"invalid id format: {node_id!r}")
            if node_id in seen:
                raise CompileError(f"duplicate id: {node_id}")
            seen.add(node_id)

            enclosing_repeats = [a for a in ancestors if a in self.repeats]
            if len(enclosing_repeats) > 1:
                raise CompileError(
                    f"nested repeats are not supported in IR v0.1 (field {node_id!r})"
                )

            if node["type"] == "repeat":
                if enclosing_repeats:
                    raise CompileError(
                        f"nested repeats are not supported in IR v0.1 (repeat {node_id!r})"
                    )
                self.repeats[node_id] = node
                self.containers[node_id] = node
                continue

            if node["type"] == "group":
                self.containers[node_id] = node
                continue

            deps: set[str] = set()
            for key in ("relevant", "constraint", "calculate", "required", "readOnly", "default"):
                expr = node.get(key)
                if isinstance(expr, dict):
                    collect_refs(expr, deps)

            # Interpolated labels are dependencies too (§7.1), and the edge is
            # load-bearing in three places rather than one. A client re-renders
            # on it; `_check_references` turns a label reading a name nothing
            # answers into a compile error through it; and
            # `check_sensitivity_propagation` reads `depends_on`, so a label
            # interpolating a sensitive field is refused at publish by a check
            # that already exists (envelope §5.2).
            #
            # Dropping it leaves every rendered string correct — both engines
            # render on demand — so `conformance/vectors/label-005` asserts the
            # edge itself rather than a render.
            for args_key in ("labelArgs", "constraintMessageArgs"):
                for expression in node.get(args_key) or []:
                    if isinstance(expression, dict):
                        collect_refs(expression, deps)

            for anc in ancestors:
                anc_node = self.containers.get(anc)
                if anc_node and isinstance(anc_node.get("relevant"), dict):
                    collect_refs(anc_node["relevant"], deps)

            choices = node.get("choices")
            query = compile_choices(choices) if isinstance(choices, dict) else None
            if query is not None:
                # A selector expression reads answers, so the field depends on
                # them: changing the district must re-resolve the village list
                # and re-check the village already chosen. `collect_refs`
                # deliberately ignores `$row.` — those are columns, not fields —
                # and the selector's right-hand sides are exactly the part that
                # is not `$row`, which is why they are collected from here
                # rather than from the filter as a whole.
                for expression in query.selector.values():
                    collect_refs(expression, deps)
                if query.residual is not None:
                    collect_refs(query.residual, deps)

            self.fields[node_id] = CompiledField(
                field_id=node_id,
                node=node,
                data_type=node["dataType"],
                depends_on=deps,
                ancestors=list(ancestors),
                repeat=enclosing_repeats[0] if enclosing_repeats else None,
                choice_query=query,
            )
            self.order.append(node_id)

        self._check_interpolation()
        self._check_references()
        self.topo_order = self._topological_order()
        self._lint()

    def _check_interpolation(self) -> None:
        """Slots and arguments agree, and no argument reads a row (§7.1).

        Both are static properties of the document, so they are compile errors
        rather than something a renderer discovers. `{5}` with three arguments
        would otherwise be an empty gap in a sentence nobody could explain.
        """
        for field_id, compiled in self.fields.items():
            for key, args_key in (
                ("label", "labelArgs"),
                ("constraintMessage", "constraintMessageArgs"),
            ):
                args = compiled.node.get(args_key) or []
                if not args:
                    continue
                strings = compiled.node.get(key) or {}
                for language, template in strings.items():
                    if not isinstance(template, str):
                        continue
                    missing = sorted(i for i in slot_indices(template) if i >= len(args))
                    if missing:
                        raise CompileError(
                            f"{field_id}: {key}[{language}] uses slot "
                            f"{{{missing[0]}}} and {args_key} has {len(args)} "
                            "argument(s)"
                        )
                for expression in args:
                    for path in _paths(expression):
                        if path.startswith("$row."):
                            raise CompileError(
                                f"{field_id}: {args_key} reads {path!r}. A label "
                                "has no candidate row (§7.1)."
                            )

    def _check_references(self) -> None:
        known = set(self.fields) | set(self.containers)
        for f in self.fields.values():
            for dep in f.depends_on:
                base = dep.split("[")[0].split(".")[0]
                if base not in known:
                    raise CompileError(
                        f"unresolvable reference {dep!r} in field {f.field_id!r}"
                    )

    def _topological_order(self) -> list[str]:
        """Kahn's algorithm, tie-broken by document order for determinism."""
        indegree = {p: 0 for p in self.fields}
        dependents: dict[str, list[str]] = {p: [] for p in self.fields}

        for path, f in self.fields.items():
            for dep in f.depends_on:
                base = dep.split("[")[0].split(".")[0]
                if base in self.fields and base != path:
                    dependents[base].append(path)
                    indegree[path] += 1

        ready = [p for p in self.order if indegree[p] == 0]
        result: list[str] = []
        while ready:
            ready.sort(key=self.order.index)
            current = ready.pop(0)
            result.append(current)
            for dep in dependents[current]:
                indegree[dep] -= 1
                if indegree[dep] == 0:
                    ready.append(dep)

        if len(result) != len(self.fields):
            cyclic = sorted(set(self.fields) - set(result))
            raise CompileError(f"dependency cycle involving: {', '.join(cyclic)}")
        return result

    def _lint(self) -> None:
        languages = set(self.ir.get("languages", []))
        for f in self.fields.values():
            label = f.node.get("label") or {}
            missing = languages - set(label)
            if missing:
                self.warnings.append(
                    f"{f.field_id}: missing translation for {', '.join(sorted(missing))}"
                )
            if f.data_type == "decimal" and isinstance(f.node.get("constraint"), dict):
                if f.node["constraint"].get("op") == "eq":
                    self.warnings.append(
                        f"{f.field_id}: direct equality comparison on a decimal field"
                    )


def _paths(expr: Any) -> set[str]:
    """Every `ref` path in an expression, including the `$row.` ones.

    `collect_refs` deliberately drops `$row.` — they are columns, not fields —
    so a check *about* them needs its own walk.
    """
    found: set[str] = set()
    if isinstance(expr, dict):
        if expr.get("op") == "ref":
            found.add(str(expr.get("path", "")))
        for arg in expr.get("args") or []:
            found |= _paths(arg)
    return found


def _inline_values(node: dict[str, Any], value: Any) -> list[Any]:
    """Values not present in an **inline** choice list (spec 6.3).

    Matching is **exact** — no trimming, no case folding, no normalisation.
    That is §6.3's decision, not an accident of `==`: a device that accepted
    "Male" for "male" would store "Male", and every later comparison would have
    to make the same allowance or disagree with it.
    """
    choices = node.get("choices")
    if not choices or choices.get("kind") != "inline":
        return []
    permitted = {item.get("value") for item in choices.get("items", [])}

    if node.get("dataType") == "select_multiple":
        # An empty list is an unanswered question, not a list in which nothing
        # matched. Iterating it and concluding failure is the mistake §6.3 names.
        if not isinstance(value, list):
            return [value] if value not in permitted else []
        return [v for v in value if v not in permitted]

    return [] if value in permitted else [value]


class FormInstance:
    """Live answer state for one compiled form.

    Canonical value paths:
      top-level field   ``age``
      repeat field      ``members[i3].age``   (``i3`` is a stable instance id)

    Instance ids are stable: deleting an instance never renumbers the others in
    storage (spec 5.4). Positional addressing (``members[0].age``) resolves
    against the current ordered list at evaluation time.
    """

    def __init__(
        self,
        form: CompiledForm,
        *,
        today: date | None = None,
        now: datetime | None = None,
        metadata: dict[str, Any] | None = None,
        datasets: DatasetSource | None = None,
    ) -> None:
        self.form = form
        self.today = today or date.today()
        self.now = now or datetime.now()
        self.metadata = metadata or {}
        # A form with no dataset-backed list never touches this; one that has
        # them and is given no source resolves every list to empty, which shows
        # up as a select with nothing to choose from rather than as a crash
        # during recalculation. That is the honest state for a device that has
        # not yet synced its reference data (§3.2).
        self.datasets: DatasetSource = datasets or InMemoryDatasetSource({})

        self.instances: dict[str, list[str]] = {rid: [] for rid in form.repeats}
        # A plain serial rather than a counter object, because `restore` has to
        # push it past ids minted on a device: a form rebuilt from storage
        # already holds `i1`..`i4`, and a `countExpr` that grows afterwards must
        # not mint an id one of them is using.
        self._instance_serial = 0

        self.values: dict[str, Any] = {
            fid: None for fid, f in form.fields.items() if f.repeat is None
        }
        self.states: dict[str, FieldState] = {
            fid: FieldState(path=fid, data_type=f.data_type)
            for fid, f in form.fields.items()
            if f.repeat is None
        }

        for rid, node in form.repeats.items():
            for _ in range(int(node.get("minInstances", 0))):
                self._create_instance(rid)

        self.recalculate()

    # -- repeat instances --------------------------------------------------

    def _fields_of(self, repeat_id: str) -> list[str]:
        return [fid for fid, f in self.form.fields.items() if f.repeat == repeat_id]

    def _create_instance(self, repeat_id: str) -> str:
        self._instance_serial += 1
        instance_id = f"i{self._instance_serial}"
        self.instances[repeat_id].append(instance_id)
        for fid in self._fields_of(repeat_id):
            path = f"{repeat_id}[{instance_id}].{fid}"
            self.values[path] = None
            self.states[path] = FieldState(
                path=path, data_type=self.form.fields[fid].data_type
            )
        return instance_id

    def _destroy_instance(self, repeat_id: str, instance_id: str) -> None:
        for fid in self._fields_of(repeat_id):
            path = f"{repeat_id}[{instance_id}].{fid}"
            self.values.pop(path, None)
            self.states.pop(path, None)

    def add_instance(self, repeat_id: str) -> str:
        if repeat_id not in self.form.repeats:
            raise CompileError(f"unknown repeat: {repeat_id}")
        node = self.form.repeats[repeat_id]
        if node.get("countExpr") is not None:
            raise CompileError(
                f"repeat {repeat_id} is controlled by countExpr; instances cannot be added"
            )
        maximum = node.get("maxInstances")
        if maximum is not None and len(self.instances[repeat_id]) >= int(maximum):
            raise CompileError(f"repeat {repeat_id} is at its maximum of {maximum}")
        instance_id = self._create_instance(repeat_id)
        self.recalculate()
        return instance_id

    def delete_instance(self, repeat_id: str, index: int) -> None:
        """Delete by position. Remaining instances keep their stable ids."""
        ordered = self.instances.get(repeat_id)
        if ordered is None:
            raise CompileError(f"unknown repeat: {repeat_id}")
        node = self.form.repeats[repeat_id]
        # Spec 2.3: under a countExpr the user can neither add nor remove. The
        # add refused and the delete did not, and the delete is the dangerous
        # half — recalculate() restores the COUNT by appending a new instance,
        # so the answers are gone and the id is different. Vector repeat-011.
        if node.get("countExpr") is not None:
            raise CompileError(
                f"repeat {repeat_id} is controlled by countExpr; instances cannot be removed"
            )
        if index < 0 or index >= len(ordered):
            raise CompileError(f"no instance at {repeat_id}[{index}]")
        # Spec 2.3 bounds the count by minInstances AND maxInstances. The
        # ceiling was checked on the add and the floor was checked nowhere, so
        # a roster declaring minInstances 1 could be emptied. Vector repeat-009.
        minimum = node.get("minInstances")
        if minimum is not None and len(ordered) <= minimum:
            raise CompileError(f"repeat {repeat_id} is at its minimum of {minimum}")
        instance_id = ordered.pop(index)
        self._destroy_instance(repeat_id, instance_id)
        self.recalculate()

    def instance_count(self, repeat_id: str) -> int:
        return len(self.instances.get(repeat_id, []))

    # -- hydration ---------------------------------------------------------

    def restore(
        self,
        *,
        instances: Mapping[str, Sequence[str]],
        answers: Mapping[str, Any],
    ) -> tuple[str, ...]:
        """Rebuild answer state from storage, keeping the ids storage recorded.

        `add_instance` mints an id; this **adopts** one. That difference is the
        whole reason the method exists. An instance id is minted once, on the
        device, and every operation about that instance names it for the life of
        the submission (§2.3, §5.4) — so a server rebuilding the form to read a
        submission back has to take the ids it is given. Minting fresh ones
        would renumber a household's members every time anything reads them,
        which is the failure `docs/` and docs/project-conventions.md's export section name: a key
        that means a different person before and after a delete.

        Positions are deliberately not an input. `instances[repeat]` is an
        ordered list of **stable ids**, and the order is the order to display
        and export them in — never an addressing scheme.

        Returns the paths in `answers` this form has no field for, rather than
        raising on the first one. A submission collected under a version whose
        fields were later renamed still has to export the answers that did
        survive; the ones that did not are named in the export manifest instead
        of taking the whole run down.

        One recalculation, at the end. Restoring instance by instance would
        recompute the form once per member of a roster.
        """
        unplaced: list[str] = []

        for repeat_id, ordered in instances.items():
            if repeat_id not in self.form.repeats:
                unplaced.extend(f"{repeat_id}[{iid}]" for iid in ordered)
                continue
            for instance_id in ordered:
                self._restore_instance(repeat_id, instance_id)

        for path, value in answers.items():
            try:
                canonical = self._canonical(path)
            except CompileError:
                unplaced.append(path)
                continue
            if canonical not in self.values:
                unplaced.append(path)
                continue
            self.values[canonical] = value

        self.recalculate()
        return tuple(unplaced)

    def _restore_instance(self, repeat_id: str, instance_id: str) -> None:
        """Create one instance under an id that came from somewhere else."""
        ordered = self.instances[repeat_id]
        if instance_id in ordered:
            return
        ordered.append(instance_id)
        for fid in self._fields_of(repeat_id):
            path = f"{repeat_id}[{instance_id}].{fid}"
            self.values[path] = None
            self.states[path] = FieldState(
                path=path, data_type=self.form.fields[fid].data_type
            )
        # A restored `i7` must not be handed out again by a later `countExpr`
        # growth or `add_instance`. Ids from another minter are left alone —
        # they cannot collide with `i<n>` — so nothing changes for a form that
        # is never restored, and the ids two engines mint stay identical.
        minted = SERIAL_ID.fullmatch(instance_id)
        if minted is not None:
            self._instance_serial = max(self._instance_serial, int(minted.group(1)))

    # -- answering ---------------------------------------------------------

    def _canonical(self, path: str) -> str:
        """Translate positional addressing into a stable-id path."""
        if "[" in path and "]." in path:
            repeat_id, rest = path.split("[", 1)
            index_text, suffix = rest.split("].", 1)
            ordered = self.instances.get(repeat_id)
            if ordered is None:
                raise CompileError(f"unknown repeat: {repeat_id}")
            if index_text.isdigit():
                index = int(index_text)
                if index >= len(ordered):
                    raise CompileError(f"no instance at {repeat_id}[{index}]")
                return f"{repeat_id}[{ordered[index]}].{suffix}"
            return path  # already a stable id
        return path

    def set(self, path: str, value: Any) -> None:
        self.set_many({path: value})

    def set_many(self, answers: dict[str, Any]) -> None:
        for path, value in answers.items():
            canonical = self._canonical(path)
            if canonical not in self.values:
                raise CompileError(f"unknown field: {path}")
            self.values[canonical] = value
        self.recalculate()

    # -- evaluation --------------------------------------------------------

    def _context(self, scope: tuple[str, str] | None = None) -> EvalContext:
        return EvalContext(
            values=self.values,
            today=self.today,
            now=self.now,
            metadata=self.metadata,
            scope=scope,
            instances=self.instances,
            # `pulldata` reads through the same source the choice filters do,
            # so a client's form-version binding covers both (§3.2).
            datasets=self.datasets,
        )

    def _evaluate_field(self, fid: str, path: str, scope: tuple[str, str] | None) -> None:
        cf = self.form.fields[fid]
        node = cf.node
        state = self.states[path]
        state.errors = []
        ctx = self._context(scope)

        relevant = True
        for anc in cf.ancestors:
            anc_node = self.form.containers.get(anc)
            if anc_node and anc_node.get("relevant") is not None:
                if not coerce_boolean(evaluate(anc_node["relevant"], ctx), null_is=True):
                    relevant = False
                    break
        if relevant and node.get("relevant") is not None:
            relevant = coerce_boolean(evaluate(node["relevant"], ctx), null_is=True)
        state.relevant = relevant

        if node.get("calculate") is not None and relevant:
            self.values[path] = evaluate(node["calculate"], ctx)
            ctx = self._context(scope)

        state.value = self.values[path]

        req = node.get("required")
        if isinstance(req, bool):
            state.required = req
        elif req is not None:
            state.required = coerce_boolean(evaluate(req, ctx), null_is=False)
        else:
            state.required = False

        ro = node.get("readOnly")
        if isinstance(ro, bool):
            state.read_only = ro
        elif ro is not None:
            state.read_only = coerce_boolean(evaluate(ro, ctx), null_is=False)
        else:
            state.read_only = False

        state.valid = True
        if relevant:
            if state.required and state.value is None:
                state.valid = False
                state.errors.append({"kind": "required"})
            # Choice membership (spec 6.3), before the constraint.
            #
            # Neither engine read `choices` at all before this: a select_one
            # could hold "purple" and both engines called the form valid and
            # finalisable. Thirty-nine vectors never saw it, because not one
            # of them ever set a value outside its list.
            #
            # `null` is deliberately excluded — an unanswered question is not a
            # membership failure, it is `required`'s business (§4.4, §6.3).
            if state.value is not None:
                offending = self._values_outside_choices(cf, state.value, scope)
                if offending:
                    state.valid = False
                    # One error on the field, not one per offending value: the
                    # field is what is invalid, and two engines that disagree
                    # about the count would both look correct.
                    state.errors.append({"kind": "choice"})
            if state.value is not None and node.get("constraint") is not None:
                if not coerce_boolean(evaluate(node["constraint"], ctx), null_is=True):
                    state.valid = False
                    state.errors.append(
                        {
                            "kind": "constraint",
                            "message": node.get("constraintMessage"),
                            "severity": node.get("severity", "error"),
                        }
                    )

    # -- dataset-backed choice lists (§3.2) --------------------------------

    def _selector_values(
        self, query: ChoiceQuery, ctx: EvalContext
    ) -> dict[str, Any]:
        """The selector, evaluated against the current answers.

        A term evaluating to `null` selects on `null` and matches no row unless
        the column holds one. It is deliberately not dropped: an unanswered
        district must narrow the village list to nothing, not widen it to
        everything (§3.2, §4.4).
        """
        return {column: evaluate(expr, ctx) for column, expr in query.selector.items()}

    def candidate_rows(
        self,
        field_id: str,
        *,
        equals: Any = _UNSET,
        scope: tuple[str, str] | None = _UNSET,  # type: ignore[assignment]
    ) -> list[dict[str, Any]]:
        """Rows the source returns for this field's selector, before residual.

        Public because it is what the performance contract is measured in: it
        is O(rows matching the selector) and never O(dataset), and a vector
        asserts its length so that "did the engine narrow" is comparable
        between implementations rather than only visible in a profiler.
        """
        cf = self.form.fields[field_id]
        query = cf.choice_query
        if query is None:
            return []
        if scope is _UNSET:
            scope = self._scope_of(field_id)
        ctx = self._context(scope)
        narrowing = (
            None if equals is _UNSET else (query.value_column, equals)
        )
        return [
            dict(row)
            for row in self.datasets.rows(
                query.dataset, self._selector_values(query, ctx), narrowing
            )
        ]

    def _rows_after_residual(
        self,
        field_id: str,
        rows: list[dict[str, Any]],
        scope: tuple[str, str] | None = _UNSET,  # type: ignore[assignment]
    ) -> list[dict[str, Any]]:
        query = self.form.fields[field_id].choice_query
        if query is None or query.residual is None:
            return rows
        if scope is _UNSET:
            scope = self._scope_of(field_id)
        base = self._context(scope)
        kept: list[dict[str, Any]] = []
        for row in rows:
            # The same context carrying that row: `$row.column` resolves from
            # here and nowhere else (expression.py). `null_is=False` because a
            # filter that cannot be decided must not offer the row — §4.4's
            # boundary rule for `constraint` coerces the other way, and this is
            # not a constraint: an undecidable row is not a permitted answer.
            if coerce_boolean(
                evaluate(query.residual, dataclasses.replace(base, row=row)),
                null_is=False,
            ):
                kept.append(row)
        return kept

    def choices(self, field_id: str) -> list[dict[str, Any]]:
        """The resolved option list for a field, in dataset order (§3.2).

        Inline lists are returned as they stand; a dataset-backed list is the
        selector's rows with the residual applied. Each entry is
        `{"value": ..., "label": {lang: ...}}`, so a client renders both kinds
        the same way and cannot end up implementing one of them itself.
        """
        cf = self.form.fields[field_id]
        query = cf.choice_query
        if query is None:
            choices = cf.node.get("choices") or {}
            return [dict(item) for item in choices.get("items", [])]

        rows = self._rows_after_residual(field_id, self.candidate_rows(field_id))

        return [
            {
                "value": row.get(query.value_column),
                "label": {
                    language: row.get(column)
                    for language, column in query.label_columns.items()
                },
            }
            for row in rows
        ]

    def _values_outside_choices(
        self, cf: CompiledField, value: Any, scope: tuple[str, str] | None
    ) -> list[Any]:
        """Values not present in this question's choice list (spec 6.3).

        For a dataset-backed list this is a **lookup, not a scan** (§3.2): the
        answer is pushed into the source alongside the selector, so with no
        residual it is one indexed question whatever the dataset's size. It is
        never "fetch the list, then search it" — that is the difference between
        a village select that works on a handset and one that does not.
        """
        query = cf.choice_query
        if query is None:
            return _inline_values(cf.node, value)

        wanted = (
            value
            if cf.data_type == "select_multiple" and isinstance(value, list)
            else [value]
        )
        missing: list[Any] = []
        for one in wanted:
            rows = self.candidate_rows(cf.field_id, equals=one, scope=scope)
            if not self._rows_after_residual(cf.field_id, rows, scope):
                missing.append(one)
        return missing

    def _scope_of(self, field_id: str) -> tuple[str, str] | None:
        """The repeat instance a field id belongs to, for building a context."""
        repeat = self.form.fields[field_id].repeat
        if repeat is None:
            return None
        # Resolution inside a repeat is the instance currently being evaluated;
        # `choices()` called from outside one uses the first instance. Repeats
        # with dataset-backed lists are not exercised until v0.2's repeat
        # screen flow, so this is deliberately the simple reading.
        instances = self.instances.get(repeat) or []
        return (repeat, instances[0]) if instances else None

    # -- interpolated text (§7.1) ------------------------------------------

    def rendered_label(self, field_id: str, language: str) -> str | None:
        """This field's label in one language, with its slots filled.

        Rendered on demand rather than stored on `FieldState`: a form has as
        many labels as it has languages, and computing every one of them on
        every recalculation would be work nobody asked for. A client asks for
        the language it is showing.
        """
        return self._render(field_id, "label", "labelArgs", language)

    def rendered_constraint_message(self, field_id: str, language: str) -> str | None:
        """The message a failed constraint shows, with its slots filled.

        The case that made §7.1 worth building: "Minimum circumference for this
        part of the plot is {0} cm", where the threshold is itself computed and
        so cannot be written into the sentence.
        """
        return self._render(
            field_id, "constraintMessage", "constraintMessageArgs", language
        )

    def _render(
        self, field_id: str, key: str, args_key: str, language: str
    ) -> str | None:
        field = self.form.fields.get(field_id)
        if field is None:
            return None
        return render_field_text(
            field.node,
            key,
            args_key,
            language,
            self._context(self._scope_of(field_id)),
            cast_str,
        )

    def recalculate(self) -> None:
        """Deterministic full pass in topological order (spec 5.2).

        A repeat field is evaluated once per instance, in instance order, before
        the pass moves to the next field. A field outside a repeat that
        aggregates over one therefore always sees fully-evaluated instances.
        """
        # countExpr governs instance count before anything inside is evaluated
        for rid, node in self.form.repeats.items():
            if node.get("countExpr") is None:
                continue
            wanted = evaluate(node["countExpr"], self._context())
            wanted = 0 if wanted is None else max(0, int(wanted))
            while len(self.instances[rid]) < wanted:
                self._create_instance(rid)
            while len(self.instances[rid]) > wanted:
                self._destroy_instance(rid, self.instances[rid].pop())

        for fid in self.form.topo_order:
            cf = self.form.fields[fid]
            if cf.repeat is None:
                self._evaluate_field(fid, fid, None)
            else:
                for instance_id in list(self.instances[cf.repeat]):
                    self._evaluate_field(
                        fid, f"{cf.repeat}[{instance_id}].{fid}", (cf.repeat, instance_id)
                    )

    # -- output ------------------------------------------------------------

    @property
    def is_valid(self) -> bool:
        return all(s.valid for s in self.states.values() if s.relevant)

    def answers(self, *, include_irrelevant: bool = False) -> dict[str, Any]:
        return {
            p: s.value for p, s in self.states.items() if include_irrelevant or s.relevant
        }

    def snapshot(self) -> dict[str, Any]:
        return {p: s.to_dict() for p, s in self.states.items()}
