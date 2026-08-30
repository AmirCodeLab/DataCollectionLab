"""Form runtime: dependency graph, repeat instances, deterministic recalculation.

Spec: specs/form-ir-v0.1.md sections 2.3, 4.2, 5.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from .document import check_document
from .expression import (
    CompileError,
    EvalContext,
    coerce_boolean,
    collect_refs,
    evaluate,
)

ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


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

            for anc in ancestors:
                anc_node = self.containers.get(anc)
                if anc_node and isinstance(anc_node.get("relevant"), dict):
                    collect_refs(anc_node["relevant"], deps)

            self.fields[node_id] = CompiledField(
                field_id=node_id,
                node=node,
                data_type=node["dataType"],
                depends_on=deps,
                ancestors=list(ancestors),
                repeat=enclosing_repeats[0] if enclosing_repeats else None,
            )
            self.order.append(node_id)

        self._check_references()
        self.topo_order = self._topological_order()
        self._lint()

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
    ) -> None:
        self.form = form
        self.today = today or date.today()
        self.now = now or datetime.now()
        self.metadata = metadata or {}

        self.instances: dict[str, list[str]] = {rid: [] for rid in form.repeats}
        self._instance_counter = itertools.count(1)

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
        instance_id = f"i{next(self._instance_counter)}"
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
        if index < 0 or index >= len(ordered):
            raise CompileError(f"no instance at {repeat_id}[{index}]")
        instance_id = ordered.pop(index)
        self._destroy_instance(repeat_id, instance_id)
        self.recalculate()

    def instance_count(self, repeat_id: str) -> int:
        return len(self.instances.get(repeat_id, []))

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
