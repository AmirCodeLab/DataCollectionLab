"""Form runtime: dependency graph construction and deterministic recalculation.

Spec: specs/form-ir-v0.1.md section 5.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterator

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
    path: str
    node: dict[str, Any]
    data_type: str
    depends_on: set[str]
    ancestors: list[str]  # ids of enclosing groups/repeats, for relevance inheritance


class CompiledForm:
    """A validated form with its dependency graph resolved."""

    def __init__(self, ir: dict[str, Any]) -> None:
        self.ir = ir
        self.form_id: str = ir["formId"]
        self.version: int = ir["version"]
        self.fields: dict[str, CompiledField] = {}
        self.containers: dict[str, dict[str, Any]] = {}
        self.warnings: list[str] = []
        self.order: list[str] = []
        self._compile()

    # -- compilation -------------------------------------------------------

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

            if node["type"] in ("group", "repeat"):
                self.containers[node_id] = node
                continue

            deps: set[str] = set()
            for key in ("relevant", "constraint", "calculate", "required", "readOnly", "default"):
                expr = node.get(key)
                if isinstance(expr, dict):
                    collect_refs(expr, deps)

            # a field inherits relevance from every enclosing container
            for anc in ancestors:
                anc_node = self.containers.get(anc)
                if anc_node and isinstance(anc_node.get("relevant"), dict):
                    collect_refs(anc_node["relevant"], deps)

            self.fields[node_id] = CompiledField(
                path=node_id,
                node=node,
                data_type=node["dataType"],
                depends_on=deps,
                ancestors=list(ancestors),
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
                        f"unresolvable reference {dep!r} in field {f.path!r}"
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
                    f"{f.path}: missing translation for {', '.join(sorted(missing))}"
                )
            if f.data_type == "decimal" and isinstance(f.node.get("constraint"), dict):
                if f.node["constraint"].get("op") == "eq":
                    self.warnings.append(
                        f"{f.path}: direct equality comparison on a decimal field"
                    )


class FormInstance:
    """A live answer state for one compiled form."""

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
        self.values: dict[str, Any] = {p: None for p in form.fields}
        self.states: dict[str, FieldState] = {
            p: FieldState(path=p, data_type=f.data_type) for p, f in form.fields.items()
        }
        self.recalculate()

    # -- answering ---------------------------------------------------------

    def set(self, path: str, value: Any) -> None:
        if path not in self.form.fields:
            raise CompileError(f"unknown field: {path}")
        self.values[path] = value
        self.recalculate()

    def set_many(self, answers: dict[str, Any]) -> None:
        for path, value in answers.items():
            if path not in self.form.fields:
                raise CompileError(f"unknown field: {path}")
            self.values[path] = value
        self.recalculate()

    # -- evaluation --------------------------------------------------------

    def _context(self) -> EvalContext:
        return EvalContext(
            values=self.values,
            today=self.today,
            now=self.now,
            metadata=self.metadata,
        )

    def recalculate(self) -> None:
        """Full deterministic pass in topological order (spec 5.2).

        A full pass rather than a dirty-subset pass keeps the reference
        implementation obviously correct; the client engine may optimise to
        the dirty subtree provided results stay identical.
        """
        ctx = self._context()

        for path in self.form.topo_order:
            cf = self.form.fields[path]
            node = cf.node
            state = self.states[path]
            state.errors = []

            # 1. relevance, including inheritance from enclosing containers
            relevant = True
            for anc in cf.ancestors:
                anc_node = self.form.containers.get(anc)
                if anc_node and anc_node.get("relevant") is not None:
                    if not coerce_boolean(
                        evaluate(anc_node["relevant"], ctx), null_is=True
                    ):
                        relevant = False
                        break
            if relevant and node.get("relevant") is not None:
                relevant = coerce_boolean(evaluate(node["relevant"], ctx), null_is=True)
            state.relevant = relevant

            # 2. calculate
            if node.get("calculate") is not None and relevant:
                self.values[path] = evaluate(node["calculate"], ctx)
                ctx = self._context()

            state.value = self.values[path]

            # 3. required
            req = node.get("required")
            if isinstance(req, bool):
                state.required = req
            elif req is not None:
                state.required = coerce_boolean(evaluate(req, ctx), null_is=False)
            else:
                state.required = False

            # 4. readOnly
            ro = node.get("readOnly")
            if isinstance(ro, bool):
                state.read_only = ro
            elif ro is not None:
                state.read_only = coerce_boolean(evaluate(ro, ctx), null_is=False)
            else:
                state.read_only = False

            # 5. constraint — only meaningful for relevant, answered fields
            state.valid = True
            if relevant:
                if state.required and state.value is None:
                    state.valid = False
                    state.errors.append({"kind": "required"})
                if state.value is not None and node.get("constraint") is not None:
                    ok = coerce_boolean(evaluate(node["constraint"], ctx), null_is=True)
                    if not ok:
                        state.valid = False
                        state.errors.append(
                            {
                                "kind": "constraint",
                                "message": node.get("constraintMessage"),
                                "severity": node.get("severity", "error"),
                            }
                        )

    # -- output ------------------------------------------------------------

    @property
    def is_valid(self) -> bool:
        return all(s.valid for s in self.states.values() if s.relevant)

    def answers(self, *, include_irrelevant: bool = False) -> dict[str, Any]:
        """Relevant answers only by default — non-relevant values are retained
        in storage but excluded from export (spec 5.3)."""
        return {
            p: s.value
            for p, s in self.states.items()
            if include_irrelevant or s.relevant
        }

    def snapshot(self) -> dict[str, Any]:
        return {p: s.to_dict() for p, s in self.states.items()}
