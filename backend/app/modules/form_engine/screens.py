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
