"""Form runtime: dependency graph, repeat instances, deterministic recalculation.

Spec: specs/form-ir-v0.1.md sections 2.3, 4.2, 5.
"""

from __future__ import annotations

import dataclasses
import heapq
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
    statically_false,
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
        #: A container's own ancestor chain, so a repeat screen's relevance can
        #: be evaluated without a field inside it to hang the walk on (§11.3).
        self.container_ancestors: dict[str, list[str]] = {}
        self.repeats: dict[str, dict[str, Any]] = {}
        # repeat id -> expression key -> field ids it reads (see the repeat
        # branch below). Read by `check_sensitivity_propagation`.
        self.container_expr_deps: dict[str, dict[str, set[str]]] = {}
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

    def _check_row_source(self, node: dict[str, Any]) -> None:
        """§10.2's four `rowSource` refusals, checked where the repeat is met.

        Each is a form that would run, and run differently on two engines or on
        two days. `kind: "dataset"` is the odd one out and its message says so:
        it is specified and not yet buildable, not malformed, and it is the one
        refusal here that is expected to be deleted (§2.3, *What is live*).
        """
        repeat_id = node["id"]
        source = node.get("rowSource")
        if source is None:
            return
        if node.get("countExpr") is not None:
            raise CompileError(
                f"repeat {repeat_id!r} carries both countExpr and rowSource; "
                "countExpr says how many and rowSource says which, and nothing "
                "arbitrates between them"
            )

        kind = source.get("kind")
        if kind == "dataset":
            raise CompileError(
                f"repeat {repeat_id!r} uses rowSource kind 'dataset', which is "
                "specified but not yet implemented: it needs _metadata.case_key "
                "(Phase 3 item 2) and a dataset version's row order to survive "
                "reaching a device (known-defects 16). Use kind 'inline' or wait"
            )
        if kind != "inline":
            raise CompileError(
                f"repeat {repeat_id!r} has an unknown rowSource kind {kind!r}"
            )

        own_fields = {
            child["id"]
            for child, _ in self._walk(node.get("children", []), [])
            if child["type"] == "question"
        }
        for question_id, column in (source.get("bind") or {}).items():
            if question_id not in own_fields:
                raise CompileError(
                    f"repeat {repeat_id!r} binds {question_id!r}, which is not a "
                    "question inside it; a row's value cannot land in a field "
                    "that is not per-row"
                )
            # A label is §7 i18n and an answer is one value in no language, so
            # binding one would make an engine pick a language and two engines
            # picking one is two forms.
            if column == "label":
                raise CompileError(
                    f"repeat {repeat_id!r} binds {question_id!r} to an inline "
                    "row's label; only 'value' is bindable, because a label is "
                    "i18n and an answer is not"
                )
            if column != "value":
                raise CompileError(
                    f"repeat {repeat_id!r} binds {question_id!r} to {column!r}; "
                    "an inline row has only 'value'"
                )

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
                # A field-list group says "these questions appear together on
                # one screen" and a repeat says "this is a separate screen you
                # enter and leave" (§11.3). Both cannot be true of the same
                # subtree, so this refusal states what is already the case
                # rather than choosing between two behaviours. The alternative —
                # dropping the repeat's questions from the field-list screen — is
                # the silent omission of defect 14, in a corner nobody looks in.
                for anc in ancestors:
                    anc_node = self.containers.get(anc)
                    if anc_node and anc_node.get("appearance") == "field-list":
                        raise CompileError(
                            f"a repeat cannot appear inside a field-list group "
                            f"(repeat {node_id!r} inside group {anc!r})"
                        )
                self._check_row_source(node)
                self.repeats[node_id] = node
                self.containers[node_id] = node
                self.container_ancestors[node_id] = list(ancestors)
                # A repeat's own expressions, kept per key rather than merged.
                #
                # `check_sensitivity_propagation` walks fields, and a repeat is
                # not one — it has no `CompiledField` and therefore no
                # `depends_on`, so for as long as this was not collected there
                # was no way for the check to see `summaryLabelArgs` at all
                # (defect 19). A repeat cannot be marked `sensitive` either, so
                # the violation has to name which expression carries the read,
                # which is why this is a map by key and not one set.
                repeat_deps: dict[str, set[str]] = {}
                count_expr = node.get("countExpr")
                if isinstance(count_expr, dict):
                    found: set[str] = set()
                    collect_refs(count_expr, found)
                    if found:
                        repeat_deps["countExpr"] = found
                summary_deps: set[str] = set()
                for expression in node.get("summaryLabelArgs") or []:
                    if isinstance(expression, dict):
                        collect_refs(expression, summary_deps)
                if summary_deps:
                    repeat_deps["summaryLabelArgs"] = summary_deps
                if repeat_deps:
                    self.container_expr_deps[node_id] = repeat_deps
                continue

            if node["type"] == "group":
                self.containers[node_id] = node
                self.container_ancestors[node_id] = list(ancestors)
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

        # `summaryLabel` is §7.1 on a repeat rather than on a field, and every
        # §7.1 rule applies to it unchanged (§2.3) — including this one, which
        # is the difference between a slot an author can see is wrong and a gap
        # in a sentence on a handset.
        for repeat_id, node in self.repeats.items():
            args = node.get("summaryLabelArgs") or []
            if not args:
                continue
            strings = node.get("summaryLabel") or {}
            for language, template in strings.items():
                if not isinstance(template, str):
                    continue
                missing = sorted(i for i in slot_indices(template) if i >= len(args))
                if missing:
                    raise CompileError(
                        f"{repeat_id}: summaryLabel[{language}] uses slot "
                        f"{{{missing[0]}}} and summaryLabelArgs has {len(args)} "
                        "argument(s)"
                    )
            # `$row.` is a column of a *choice* list's candidate row (§3.2). A
            # summary label reads the instance, and an instance is answers.
            for expression in args:
                for path in _paths(expression):
                    if path.startswith("$row."):
                        raise CompileError(
                            f"{repeat_id}: summaryLabelArgs reads {path!r}. A "
                            "label has no candidate row (§7.1)."
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

        # The tie-break is "lowest document position wins", so the ready set is
        # a min-heap keyed on that position and never a list that is re-sorted.
        #
        # The shape this replaces was `ready.sort(key=self.order.index)` inside
        # the loop, and it is worth naming because it was correct and it did
        # not scale: `self.order` is a list, so `.index` is a linear scan, and
        # the scan ran once per ready element per iteration. On every form this
        # repository had ever been shown — three screens — that is free. On a
        # 2,128-question questionnaire it was **16.3 seconds**, against 10 ms
        # here, and it was the whole cost of an import and of every compile.
        #
        # No vector could see it. The order this produces is identical, which
        # is the entire reach of a conformance vector; the Kotlin twin has
        # always kept its document index in a **map**, so the two engines
        # differed by three orders of magnitude while agreeing exactly.
        # docs/scale-run-2026-09-12-sindh.md, break 226.
        position = {p: i for i, p in enumerate(self.order)}
        ready = [position[p] for p in self.order if indegree[p] == 0]
        heapq.heapify(ready)
        result: list[str] = []
        while ready:
            current = self.order[heapq.heappop(ready)]
            result.append(current)
            for dep in dependents[current]:
                indegree[dep] -= 1
                if indegree[dep] == 0:
                    heapq.heappush(ready, position[dep])

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
            # §10.3: a statically-false relevant on a question is a warning —
            # staging is real work. On a container it is a §10.2 error, checked
            # at the publish gate (`reachability.check_reachability`), because
            # nobody writes questions in order to guarantee they are never asked.
            if statically_false(f.node.get("relevant")):
                self.warnings.append(f"{f.field_id}: unreachable relevance (statically false)")


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
        # The source row each instance came from (§2.3), by instance id. An
        # instance the enumerator added has no entry and reads back as None —
        # which is the difference between "the sample knew about this member"
        # and "the enumerator added them", and is what an export joins on.
        self.row_keys: dict[str, dict[str, str | None]] = {rid: {} for rid in form.repeats}
        # The source row's own label, kept beside its key because §2.3's
        # chain needs it: a row with no `summaryLabel` shows what its source
        # row said. An added instance has no entry here, which is exactly the
        # case the chain falls through for.
        self.row_labels: dict[str, dict[str, dict[str, str]]] = {
            rid: {} for rid in form.repeats
        }
        # Which repeats have had their rowSource resolved. §2.3: resolved ONCE,
        # the first time the repeat is relevant, and never re-resolved.
        self._rows_resolved: set[str] = set()
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
            # §2.3: minInstances has no effect on a rowSource repeat — the
            # source decides the initial count, and a floor beside it would
            # create empty rows alongside the real ones.
            if node.get("rowSource") is not None:
                continue
            for _ in range(int(node.get("minInstances", 0))):
                self._create_instance(rid)

        self.recalculate()

    # -- repeat instances --------------------------------------------------

    def _fields_of(self, repeat_id: str) -> list[str]:
        return [fid for fid, f in self.form.fields.items() if f.repeat == repeat_id]

    def _assert_creation_order(self, repeat_id: str) -> None:
        """A repeat's instance list is in creation order. Checked, not argued.

        Spec 2.3's "shrinking discards the trailing instances" is only true
        while this holds: the shrink pops from the END, so a list out of
        creation order discards somebody else's answers with the count still
        reading correctly — break 75's damage, arriving by a different road.
        The countExpr guard on `delete_instance` closes the one path inside the
        engine that could reorder a list. This closes the rest.

        The two halves of 2.3 are load bearing on each other and neither
        sentence says so, which is the reason this is an assertion rather than
        a comment.

        Ordinals are read off the id, because `i<n>` is minted sequentially and
        is therefore its own creation ordinal — so a `restore()` that hands
        minted ids back out of order fails here rather than silently reordering
        a household. Ids from another minter carry no readable ordinal and the
        caller's order stands; that is the caller boundary described in
        docs/project-conventions.md, and no assertion inside the engine can
        reach it.
        """
        serials: list[int] = []
        for instance_id in self.instances[repeat_id]:
            minted = SERIAL_ID.fullmatch(instance_id)
            if minted is None:
                return
            serials.append(int(minted.group(1)))
        if any(a >= b for a, b in zip(serials, serials[1:], strict=False)):
            raise CompileError(
                f"repeat {repeat_id} instances are not in creation order: "
                f"{list(self.instances[repeat_id])}"
            )

    def _create_instance(self, repeat_id: str, row_key: str | None = None) -> str:
        self._instance_serial += 1
        instance_id = f"i{self._instance_serial}"
        self.instances[repeat_id].append(instance_id)
        self.row_keys[repeat_id][instance_id] = row_key
        self._assert_creation_order(repeat_id)
        for fid in self._fields_of(repeat_id):
            path = f"{repeat_id}[{instance_id}].{fid}"
            self.values[path] = None
            self.states[path] = FieldState(
                path=path, data_type=self.form.fields[fid].data_type
            )
        return instance_id

    def _resolve_rows(self, repeat_id: str) -> None:
        """Create this repeat's instances from its `rowSource`. Once, ever.

        §2.3: the row set is resolved the first time the repeat is relevant and
        is **never re-resolved**. A row deleted from the source afterwards does
        not delete the instance holding a respondent's answers, and a row the
        enumerator deleted does not come back.

        `maxInstances` is deliberately not consulted. It bounds *adding*; a
        source with more rows than the ceiling instantiates all of them and
        permits no add, because truncating would drop a row with nothing in an
        error state.
        """
        node = self.form.repeats[repeat_id]
        source = node.get("rowSource")
        if source is None or repeat_id in self._rows_resolved:
            return
        if not self.container_relevant(repeat_id):
            return
        self._rows_resolved.add(repeat_id)
        bind = source.get("bind") or {}
        for item in source.get("items") or []:
            key = item["value"]
            instance_id = self._create_instance(repeat_id, row_key=key)
            label = item.get("label")
            if isinstance(label, dict):
                self.row_labels[repeat_id][instance_id] = label
            # A seeded value is an ordinary answer from this moment: it behaves
            # as if it had arrived as the question's `default`, and a later set
            # overwrites it and it stays overwritten.
            for question_id, column in bind.items():
                path = f"{repeat_id}[{instance_id}].{question_id}"
                value = item.get(column)
                self.values[path] = value
                self.states[path].value = value

    def _destroy_instance(self, repeat_id: str, instance_id: str) -> None:
        self.row_keys[repeat_id].pop(instance_id, None)
        self.row_labels[repeat_id].pop(instance_id, None)
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
        # §2.3: `allowAdd` and `allowDelete` are independent, and both default
        # to false. Two booleans rather than one, because a spec sentence naming
        # two operations is one an engine implements half of and looks finished
        # — breaks 74 and 75. Vectors rows-004 and rows-005, one half each.
        source = node.get("rowSource")
        if source is not None and not source.get("allowAdd", False):
            raise CompileError(
                f"repeat {repeat_id} takes its rows from a rowSource that does "
                "not permit adding"
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
        source = node.get("rowSource")
        if source is not None and not source.get("allowDelete", False):
            raise CompileError(
                f"repeat {repeat_id} takes its rows from a rowSource that does "
                "not permit deleting"
            )
        if index < 0 or index >= len(ordered):
            raise CompileError(f"no instance at {repeat_id}[{index}]")
        # Spec 2.3 bounds the count by minInstances AND maxInstances. The
        # ceiling was checked on the add and the floor was checked nowhere, so
        # a roster declaring minInstances 1 could be emptied. Vector repeat-009.
        # A rowSource repeat has no floor: §2.3 gives minInstances no effect
        # there, so a delete it permits is not silently bounded by one.
        minimum = None if source is not None else node.get("minInstances")
        if minimum is not None and len(ordered) <= minimum:
            raise CompileError(f"repeat {repeat_id} is at its minimum of {minimum}")
        instance_id = ordered.pop(index)
        self._assert_creation_order(repeat_id)
        self._destroy_instance(repeat_id, instance_id)
        self.recalculate()

    def row_key(self, repeat_id: str, instance_id: str) -> str | None:
        """The source row an instance came from, or None if nobody's row.

        §2.3 addresses it as `members[.]._rowKey`. It is the identity the sample
        already had, where an instance id is this submission's private counter.
        """
        return self.row_keys.get(repeat_id, {}).get(instance_id)

    def container_relevant(self, container_id: str) -> bool:
        """A group's or repeat's own relevance, with its ancestors' (spec 5).

        A repeat screen has no questions to read relevance off (§11.3), so this
        evaluates the node's own chain instead. Top-level context: a container
        outside a repeat cannot see an instance scope, and a repeat's own
        `relevant` is evaluated once for the repeat and not once per instance.
        """
        ctx = self._context(None)
        node = self.form.containers.get(container_id)
        if node is None:
            return True
        chain = list(self.form.container_ancestors.get(container_id, [])) + [container_id]
        for cid in chain:
            container = self.form.containers.get(cid)
            if container is None or container.get("relevant") is None:
                continue
            if not coerce_boolean(evaluate(container["relevant"], ctx), null_is=True):
                return False
        return True

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
        self._assert_creation_order(repeat_id)
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

    def rendered_add_label(self, repeat_id: str, language: str) -> str | None:
        """The text on the add control, or None if the form does not name it.

        No arguments and no interpolation: "Add another household member" is
        per-form and per-language and says nothing about any instance, which is
        why it is a plain `{lang: string}` and why it lives on the node rather
        than in a client (§2.3). A client that has None here supplies its own
        wording; a client that has a string uses it exactly.
        """
        node = self.form.repeats.get(repeat_id)
        if node is None:
            raise CompileError(f"unknown repeat: {repeat_id}")
        strings = node.get("addLabel")
        if not isinstance(strings, dict):
            return None
        text = strings.get(language)
        return text if isinstance(text, str) else None

    def summary_label(self, repeat_id: str, instance_id: str, language: str) -> str:
        """What one row of the instance list says (§2.3).

        The chain, first thing that produces a label:

        1. `summaryLabel`, rendered in this instance's scope — unless it has
           arguments and every one of them is null.
        2. The source row's own label, for an instance a `rowSource` created.
        3. The instance's 1-based position in the current order.

        Rule 1's exception is what an added instance needs. Between pressing
        add and typing anything it has answered nothing, so a template of
        ``"{0} — {1}"`` renders ``" — "`` — and two rows reading ``" — "``
        cannot be told apart, which is the one thing the list exists to do.

        The test is on the arguments, not on the rendered string: emptiness in
        a string is punctuation, and recognising it would mean guessing at
        languages the engine does not read. "This instance has answered none of
        the things its label is made of" is the same question everywhere.
        """
        ordered = self.instances.get(repeat_id)
        if ordered is None:
            raise CompileError(f"unknown repeat: {repeat_id}")
        if instance_id not in ordered:
            raise CompileError(f"repeat {repeat_id} has no instance {instance_id!r}")
        node = self.form.repeats[repeat_id]

        args = node.get("summaryLabelArgs") or []
        strings = node.get("summaryLabel")
        if isinstance(strings, dict) and isinstance(strings.get(language), str):
            ctx = self._context((repeat_id, instance_id))
            # A constant summary label — a template with no arguments — is the
            # author's deliberate choice and does not fall through. The chain
            # only begins where there is something to have answered.
            if not args or any(
                evaluate(expression, ctx) is not None for expression in args
            ):
                rendered = render_field_text(
                    node, "summaryLabel", "summaryLabelArgs", language, ctx, cast_str
                )
                if rendered is not None:
                    return rendered

        source_label = self.row_labels.get(repeat_id, {}).get(instance_id)
        if isinstance(source_label, dict):
            text = source_label.get(language)
            if isinstance(text, str):
                return text

        return str(ordered.index(instance_id) + 1)

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
        # A rowSource resolves before anything inside is evaluated, for the same
        # reason countExpr does below: the instances have to exist before the
        # fields in them are walked. It runs on every pass and returns at once
        # after the first, because "the first time the repeat is relevant" is a
        # condition only recalculation can notice.
        for rid in self.form.repeats:
            self._resolve_rows(rid)

        # countExpr governs instance count before anything inside is evaluated
        for rid, node in self.form.repeats.items():
            if node.get("countExpr") is None:
                continue
            wanted = evaluate(node["countExpr"], self._context())
            wanted = 0 if wanted is None else max(0, int(wanted))
            # Before the shrink pops from the end, not after.
            self._assert_creation_order(rid)
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
