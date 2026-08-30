"""Screen partition and navigation. Reference implementation for spec §11.

The Kotlin engine (shared/form-engine Screens.kt) must produce identical
results for every conformance vector. Clients render what this module says —
they never compute screen flow themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .runtime import FormInstance


@dataclass(frozen=True)
class FormScreen:
    """One screen of the plan. ``index`` is stable; relevance never renumbers it."""

    index: int
    group_id: str | None
    section_id: str | None
    question_ids: tuple[str, ...]


def build_screen_plan(ir: dict[str, Any]) -> list[FormScreen]:
    """Computes the static screen plan from the IR alone (spec 11.1)."""
    screens: list[FormScreen] = []

    def collect_questions(nodes: list[dict[str, Any]], out: list[str]) -> None:
        for node in nodes:
            kind = node["type"]
            if kind == "question":
                out.append(node["id"])
            elif kind == "group":
                collect_questions(node.get("children", []), out)
            # repeat: excluded from the screen plan (spec 11.1)

    def walk(nodes: list[dict[str, Any]], section_id: str | None) -> None:
        for node in nodes:
            kind = node["type"]
            if kind == "question":
                screens.append(
                    FormScreen(len(screens), None, section_id, (node["id"],))
                )
            elif kind == "group":
                if node.get("appearance") == "field-list":
                    questions: list[str] = []
                    collect_questions(node.get("children", []), questions)
                    if questions:
                        screens.append(
                            FormScreen(
                                len(screens), node["id"], section_id, tuple(questions)
                            )
                        )
                else:
                    walk(node.get("children", []), node["id"])
            # repeat: excluded from the screen plan (spec 11.1)

    walk(ir.get("children", []), None)
    return screens


def screen_relevant(screen: FormScreen, instance: FormInstance) -> bool:
    """A screen is relevant while at least one of its questions is (spec 11.2)."""
    return any(
        qid in instance.states and instance.states[qid].relevant
        for qid in screen.question_ids
    )


def next_screen(
    plan: list[FormScreen], instance: FormInstance, from_index: int
) -> int | None:
    """Lowest-index relevant screen after ``from_index``; ``-1`` gives the first."""
    for screen in plan:
        if screen.index > from_index and screen_relevant(screen, instance):
            return screen.index
    return None


def previous_screen(
    plan: list[FormScreen], instance: FormInstance, from_index: int
) -> int | None:
    """Highest-index relevant screen before ``from_index``."""
    for screen in reversed(plan):
        if screen.index < from_index and screen_relevant(screen, instance):
            return screen.index
    return None


def relevant_screens(plan: list[FormScreen], instance: FormInstance) -> list[int]:
    """Indices of every currently relevant screen, in order."""
    return [s.index for s in plan if screen_relevant(s, instance)]


def blocking_fields(instance: FormInstance) -> list[str]:
    """Fields that block finalisation (spec 6.2).

    Relevant, and carrying at least one error of severity ``error``. A soft
    constraint (``warning``) makes a field invalid without blocking it, so this
    is deliberately not ``not instance.is_valid``.

    Order is field-state order — fields outside a repeat in document order, then
    each repeat instance's fields in instance order — which is the same on both
    engines.
    """
    return [
        path
        for path, state in instance.states.items()
        if state.relevant
        and any(e.get("severity", "error") == "error" for e in state.errors)
    ]


def can_finalize(instance: FormInstance) -> bool:
    """True when nothing blocks finalisation (spec 6.2)."""
    return not blocking_fields(instance)


def first_blocking_screen(
    plan: list[FormScreen], instance: FormInstance
) -> int | None:
    """Lowest-index screen holding a blocking field (spec 6.2), else ``None``.

    ``None`` does not mean finalisation is allowed: a blocking field inside a
    repeat has no screen at all, because repeats are excluded from the plan
    (spec 11.1). ``can_finalize`` is the question about finalising; this one is
    about navigating.
    """
    blocking = set(blocking_fields(instance))
    for screen in plan:
        if any(qid in blocking for qid in screen.question_ids):
            return screen.index
    return None
