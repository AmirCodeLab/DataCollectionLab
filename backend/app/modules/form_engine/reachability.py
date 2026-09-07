"""Which questions a form can never ask, decided from the document alone.

Form IR §10.2 and §10.3. Two findings, one function each, and the publish
gate reads both:

- **Reachability** — a question that is not a `calculate` and sits on no
  screen of §11.1's partition. This is defect 14's shape, the one the
  importer's `questions_cannot_be_asked` was written for; it lives here now so
  that every caller of `check_publishable` gets it, not only an import.
- **Liveness** — a container that provably yields no screen: a `relevant`
  that is statically false, or a repeat that can never hold an instance
  (§10.3's three shapes). The engine is right to skip it at runtime
  (`screens.screen_relevant`); that is why the document must not ship.

Both are static. Nothing here evaluates an answer, and an expression that
reads one is not decided however plainly it fails — §10.3 says why, and the
Kotlin twin (`Reachability.kt`) must agree to the sentence, because a form
one builder refuses and another accepts is two rules. `conformance/reachability`
pins the messages.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.form_engine.expression import is_static, static_value, statically_false
from app.modules.form_engine.screens import build_screen_plan


@dataclass(frozen=True)
class DeadContainer:
    id: str
    reason: str
    #: Answerable questions inside, in document order.
    questions: list[str]


def _answerable(nodes: list[dict[str, Any]]) -> list[str]:
    """Every question meant to be answered or read: not a `calculate`.

    A `note` counts — it stores nothing, but a note nobody can see is still
    content that silently vanished.
    """
    out: list[str] = []
    for node in nodes:
        if node.get("type") == "question" and node.get("calculate") is None:
            out.append(node["id"])
        if node.get("children"):
            out.extend(_answerable(node["children"]))
    return out


def dead_reason(node: dict[str, Any]) -> str | None:
    """Why this container can never show a screen, or None (§10.3)."""
    kind = node.get("type")
    if kind not in ("group", "repeat"):
        return None
    if statically_false(node.get("relevant")):
        return "is never shown: its relevant is statically false"
    if kind != "repeat":
        return None
    count = node.get("countExpr")
    if count is not None and is_static(count):
        value = static_value(count)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value <= 0:
            return f"never holds an instance: its countExpr is statically {value}"
    if node.get("maxInstances") == 0:
        return "never holds an instance: maxInstances is 0"
    source = node.get("rowSource")
    if (
        isinstance(source, dict)
        and source.get("kind") == "inline"
        and not source.get("items")
        and not source.get("allowAdd", False)
    ):
        return "never holds an instance: its fixed list is empty and rows cannot be added"
    return None


def dead_containers(ir: dict[str, Any]) -> list[DeadContainer]:
    """Unreachable containers holding answerable questions, outermost only."""
    found: list[DeadContainer] = []

    def walk(nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            reason = dead_reason(node)
            if reason is not None:
                questions = _answerable(node.get("children", []))
                if questions:
                    found.append(DeadContainer(node["id"], reason, questions))
                # Reported once, by the outermost: nothing inside is reachable.
                continue
            if node.get("children"):
                walk(node["children"])

    walk(ir.get("children", []))
    return found


def _named(ids: list[str]) -> str:
    shown = ", ".join(f"'{q}'" for q in ids[:5])
    if len(ids) > 5:
        shown += f" and {len(ids) - 5} more"
    return shown


def check_reachability(ir: dict[str, Any]) -> list[str]:
    """Violations that block publish, in document order. Empty when none."""
    violations: list[str] = []

    on_screen = build_screen_plan(ir).askable_question_ids()
    unreachable = [q for q in _answerable(ir.get("children", [])) if q not in on_screen]
    if unreachable:
        violations.append(
            f"{len(unreachable)} question(s) in this form cannot be asked by any client, "
            f"so they would be silently skipped in the field: {_named(unreachable)}. "
            "Nothing in the screen plan reaches them (Form IR §11.1)."
        )

    for dead in dead_containers(ir):
        n = len(dead.questions)
        violations.append(
            f"'{dead.id}' {dead.reason}, so {n} question(s) inside it would never be "
            f"asked: {_named(dead.questions)} (Form IR §10.3)."
        )
    return violations


def never_shown_questions(ir: dict[str, Any]) -> list[str]:
    """Every answerable question the document itself says is never shown.

    Inside an unreachable container, or carrying a statically-false `relevant`
    of its own. Document order. This is the field a builder's "never shown"
    badge reads — the same finding as the refusal and the warning, structured,
    so the console does not have to parse either.
    """
    out: list[str] = []

    def walk(nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            if dead_reason(node) is not None:
                out.extend(_answerable(node.get("children", [])))
                continue
            if node.get("type") == "question":
                if node.get("calculate") is None and statically_false(node.get("relevant")):
                    out.append(node["id"])
            if node.get("children"):
                walk(node["children"])

    walk(ir.get("children", []))
    return out
