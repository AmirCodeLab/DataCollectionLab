"""Screen partition and navigation. Reference implementation for spec §11.

The Kotlin engine (shared/form-engine Screens.kt) must produce identical
results for every conformance vector. Clients render what this module says —
they never compute screen flow themselves.

Two levels, and exactly two. The plan holds one screen per question, one per
field-list group and **one per repeat**; a repeat's own children are partitioned
by the same rules into an *instance plan*, which is rendered once per instance
(§11.3). A repeat inside a repeat is a compile error (§2.3), so an instance plan
can hold no repeat screen and the nesting cannot go deeper.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .runtime import FormInstance

QUESTIONS = "questions"
REPEAT = "repeat"


@dataclass(frozen=True)
class FormScreen:
    """One screen of a plan. ``index`` is stable; nothing renumbers it.

    A ``repeat`` screen carries no questions and names the repeat whose instance
    list it shows. A ``questions`` screen carries no repeat.
    """

    index: int
    kind: str
    group_id: str | None
    section_id: str | None
    question_ids: tuple[str, ...]
    repeat_id: str | None = None


@dataclass(frozen=True)
class ScreenPlan:
    """The whole partition: the top-level screens and one plan per repeat.

    Both halves are pure functions of the IR. **An instance count never enters
    either** (§11.3) — that is what keeps indices stable while an enumerator
    adds members, and it is the property to check a change against.
    """

    screens: tuple[FormScreen, ...]
    instance_plans: Mapping[str, tuple[FormScreen, ...]]

    def __len__(self) -> int:
        return len(self.screens)

    def __getitem__(self, index: int) -> FormScreen:
        return self.screens[index]

    def askable_question_ids(self) -> set[str]:
        """Every question a runtime can put in front of somebody.

        Both levels, in one call, deliberately. The importer's reachability
        refusal reads this to decide whether a form can be published
        (`docs/known-defects.md` 14), and a caller that read `screens` alone
        would silently miss every repeat question — which is the exact defect
        that refusal exists to catch. There is no way to ask this question
        half-way.
        """
        found = {qid for screen in self.screens for qid in screen.question_ids}
        for plan in self.instance_plans.values():
            found.update(qid for screen in plan for qid in screen.question_ids)
        return found


@dataclass(frozen=True)
class Position:
    """Where the enumerator is (§11.2).

    A top-level screen, or — inside a repeat instance — that repeat's screen
    plus the **instance id** and the index within the instance plan.

    The id is the point. §2.3 guarantees a delete never renumbers the survivors,
    so a position holding an ordinal would silently move the enumerator into a
    different person's answers when some other instance was deleted, with every
    control on the screen still reading correctly. An id either still resolves
    or it does not.
    """

    screen: int
    instance_id: str | None = None
    instance_screen: int | None = None

    @property
    def inside(self) -> bool:
        return self.instance_id is not None


def build_screen_plan(ir: dict[str, Any]) -> ScreenPlan:
    """Computes the static plan from the IR alone (spec 11.1)."""
    screens: list[FormScreen] = []
    instance_plans: dict[str, tuple[FormScreen, ...]] = {}

    def collect_questions(nodes: list[dict[str, Any]], out: list[str]) -> None:
        for node in nodes:
            kind = node["type"]
            if kind == "question":
                # A calculate is computed, never asked (§11.1). Listing it on a
                # field-list screen puts a control nobody can answer beside the
                # ones they can, and makes the screen relevant on the strength
                # of a field that is never drawn.
                if node.get("calculate") is None:
                    out.append(node["id"])
            elif kind == "group":
                collect_questions(node.get("children", []), out)
            # A repeat cannot appear here: it is a compile error inside a
            # field-list group (§10.2), and this walk only runs under one.

    def walk(
        nodes: list[dict[str, Any]], section_id: str | None, out: list[FormScreen]
    ) -> None:
        for node in nodes:
            kind = node["type"]
            if kind == "question":
                # A calculate produces NO screen. It has nothing to read and
                # nothing to answer, so its screen is blank: the enumerator taps
                # past it, and — the part that is not merely ugly — it counts
                # toward the "N of M" progress, which then overstates how much
                # work is left on every form that carries one.
                if node.get("calculate") is None:
                    out.append(
                        FormScreen(len(out), QUESTIONS, None, section_id, (node["id"],))
                    )
            elif kind == "group":
                if node.get("appearance") == "field-list":
                    questions: list[str] = []
                    collect_questions(node.get("children", []), questions)
                    if questions:
                        out.append(
                            FormScreen(
                                len(out), QUESTIONS, node["id"], section_id,
                                tuple(questions),
                            )
                        )
                else:
                    walk(node.get("children", []), node["id"], out)
            elif kind == "repeat":
                # One screen, whatever the instance count — see ScreenPlan.
                out.append(
                    FormScreen(
                        len(out), REPEAT, None, section_id, (), repeat_id=node["id"]
                    )
                )
                inner: list[FormScreen] = []
                walk(node.get("children", []), node["id"], inner)
                instance_plans[node["id"]] = tuple(inner)

    walk(ir.get("children", []), None, screens)
    return ScreenPlan(tuple(screens), instance_plans)


# -- relevance -------------------------------------------------------------


def _can_add(instance: FormInstance, repeat_id: str) -> bool:
    """Whether §2.3 would let the enumerator add an instance right now."""
    node = instance.form.repeats.get(repeat_id)
    if node is None or node.get("countExpr") is not None:
        return False
    maximum = node.get("maxInstances")
    if maximum is None:
        return True
    return instance.instance_count(repeat_id) < int(maximum)


def screen_relevant(screen: FormScreen, instance: FormInstance) -> bool:
    """A screen is relevant while at least one of its questions is (spec 11.2).

    A repeat screen has no questions, so §11.3 decides it instead: the repeat
    itself is relevant, **and** the screen has something to offer — an instance,
    or one the enumerator may add.

    Both halves of that second condition matter and they pull opposite ways. A
    countExpr repeat sized zero offers neither and is skipped, as a screen of
    only calculates is. An enumerator-driven repeat with no instances yet must
    NOT be skipped: its empty screen is the only door to the first instance.
    """
    if screen.kind == REPEAT:
        assert screen.repeat_id is not None
        if not instance.container_relevant(screen.repeat_id):
            return False
        return instance.instance_count(screen.repeat_id) > 0 or _can_add(
            instance, screen.repeat_id
        )
    return any(
        qid in instance.states and instance.states[qid].relevant
        for qid in screen.question_ids
    )


def instance_screen_relevant(
    screen: FormScreen, instance: FormInstance, repeat_id: str, instance_id: str
) -> bool:
    """The same rule, read against one instance's field states."""
    return any(
        instance.states[path].relevant
        for path in (f"{repeat_id}[{instance_id}].{qid}" for qid in screen.question_ids)
        if path in instance.states
    )


def relevant_instance_screens(
    plan: ScreenPlan, instance: FormInstance, repeat_id: str, instance_id: str
) -> list[int]:
    return [
        s.index
        for s in plan.instance_plans.get(repeat_id, ())
        if instance_screen_relevant(s, instance, repeat_id, instance_id)
    ]


# -- top-level navigation (spec 11.2) --------------------------------------


def next_screen(plan: ScreenPlan, instance: FormInstance, from_index: int) -> int | None:
    """Lowest-index relevant screen after ``from_index``; ``-1`` gives the first."""
    for screen in plan.screens:
        if screen.index > from_index and screen_relevant(screen, instance):
            return screen.index
    return None


def previous_screen(
    plan: ScreenPlan, instance: FormInstance, from_index: int
) -> int | None:
    """Highest-index relevant screen before ``from_index``."""
    for screen in reversed(plan.screens):
        if screen.index < from_index and screen_relevant(screen, instance):
            return screen.index
    return None


def relevant_screens(plan: ScreenPlan, instance: FormInstance) -> list[int]:
    """Indices of every currently relevant screen, in order."""
    return [s.index for s in plan.screens if screen_relevant(s, instance)]


# -- positions (spec 11.2, 11.3) -------------------------------------------


def _repeat_of(plan: ScreenPlan, screen_index: int) -> str | None:
    screen = plan.screens[screen_index]
    return screen.repeat_id if screen.kind == REPEAT else None


def resolve_position(
    plan: ScreenPlan, instance: FormInstance, position: Position
) -> Position:
    """An instance that ceases to exist drops the position back to its repeat.

    One rule for every cause (§11.3): a delete, or a countExpr shrink that
    discarded the trailing instance the enumerator was inside.
    """
    if not position.inside:
        return position
    repeat_id = _repeat_of(plan, position.screen)
    if repeat_id is None:
        return Position(position.screen)
    if position.instance_id not in instance.instances.get(repeat_id, []):
        return Position(position.screen)
    return position


def enter_instance(
    plan: ScreenPlan, instance: FormInstance, repeat_id: str, instance_id: str
) -> Position:
    """The only way into an instance (§11.2). `next` never enters one."""
    screen = next(
        (s for s in plan.screens if s.kind == REPEAT and s.repeat_id == repeat_id), None
    )
    if screen is None:
        raise KeyError(f"no repeat screen for {repeat_id!r}")
    relevant = relevant_instance_screens(plan, instance, repeat_id, instance_id)
    if not relevant:
        return Position(screen.index)
    return Position(screen.index, instance_id, relevant[0])


def next_position(
    plan: ScreenPlan, instance: FormInstance, position: Position
) -> Position | None:
    """`next` over a position (§11.2, §11.3).

    From inside an instance this never returns nothing: past the last relevant
    instance screen it **leaves the instance** to the repeat screen, which is
    where the "are we finished?" decision belongs. It never moves to another
    instance.
    """
    position = resolve_position(plan, instance, position)
    if not position.inside:
        nxt = next_screen(plan, instance, position.screen)
        return None if nxt is None else Position(nxt)

    repeat_id = _repeat_of(plan, position.screen)
    assert repeat_id is not None and position.instance_id is not None
    relevant = relevant_instance_screens(plan, instance, repeat_id, position.instance_id)
    assert position.instance_screen is not None
    later = [i for i in relevant if i > position.instance_screen]
    if later:
        return Position(position.screen, position.instance_id, later[0])
    return Position(position.screen)


def previous_position(
    plan: ScreenPlan, instance: FormInstance, position: Position
) -> Position | None:
    """`previous` over a position. From the first instance screen it leaves."""
    position = resolve_position(plan, instance, position)
    if not position.inside:
        prv = previous_screen(plan, instance, position.screen)
        return None if prv is None else Position(prv)

    repeat_id = _repeat_of(plan, position.screen)
    assert repeat_id is not None and position.instance_id is not None
    relevant = relevant_instance_screens(plan, instance, repeat_id, position.instance_id)
    assert position.instance_screen is not None
    earlier = [i for i in relevant if i < position.instance_screen]
    if earlier:
        return Position(position.screen, position.instance_id, earlier[-1])
    return Position(position.screen)


# -- progress (spec 11.2, 11.3) --------------------------------------------


def progress(plan: ScreenPlan, instance: FormInstance, position: Position) -> tuple[int, int]:
    """The form-level pair: 1-based position among relevant screens, and how many.

    A repeat screen counts **once**, whatever it holds, and this pair does not
    move while the enumerator is inside an instance — they have not left the
    repeat screen. A household of six members reads `4 of 12` and still reads
    `4 of 12` at seven; a denominator that moves is a promise the form withdraws.

    Position is 0 while the current screen is not itself relevant.
    """
    relevant = relevant_screens(plan, instance)
    return (
        relevant.index(position.screen) + 1 if position.screen in relevant else 0,
        len(relevant),
    )


def instance_progress(
    plan: ScreenPlan, instance: FormInstance, position: Position
) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """The two pairs an open instance reports (§11.3), or None outside one.

    Within the instance: position among its currently relevant instance screens.
    Across instances: which instance is open, out of how many exist.

    Specified here rather than left to clients for §6.2's reason — two runtimes
    that each decide what "3 of 5" counts will decide differently, it will read
    as a UX detail, and no conformance vector reaches a client.

    The across pair moves as instances are added. That is correct: it is the
    roster's own count and not a claim about how much of the form is left.
    """
    position = resolve_position(plan, instance, position)
    if not position.inside:
        return None
    repeat_id = _repeat_of(plan, position.screen)
    assert repeat_id is not None and position.instance_id is not None
    relevant = relevant_instance_screens(plan, instance, repeat_id, position.instance_id)
    within = (
        relevant.index(position.instance_screen) + 1
        if position.instance_screen in relevant
        else 0,
        len(relevant),
    )
    order = instance.instances.get(repeat_id, [])
    across = (order.index(position.instance_id) + 1, len(order))
    return within, across


# -- finalisation (spec 6.2) -----------------------------------------------


def blocking_fields(instance: FormInstance) -> list[str]:
    """Fields that block finalisation (spec 6.2).

    Relevant, and carrying at least one error of severity ``error``. A soft
    constraint (``warning``) makes a field invalid without blocking it, so this
    is deliberately not ``not instance.is_valid``.

    Order is field-state order — fields outside a repeat in document order, then
    each repeat instance's fields in instance order — which is the same on both
    engines, and is **not** the order `first_blocking_position` walks.
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


def first_blocking_position(
    plan: ScreenPlan, instance: FormInstance
) -> Position | None:
    """The earliest place to send somebody to see a blocking field (spec 6.2).

    Screen order, not `blocking_fields` order: lowest top-level screen; then,
    within a repeat screen, earliest instance in instance order, then lowest
    instance screen. A blocking field on screen 9 can come first in
    `blocking_fields` while one on repeat screen 3 is the earliest place to go.
    Both orders are defined and they answer different questions.

    ``None`` does not mean finalisation is allowed. A `calculate` produces no
    screen (§11.1), and a calculate carrying a failing hard constraint is
    relevant and blocking, so nothing in the plan holds it —
    `docs/known-defects.md` 15. `can_finalize` is the question about finalising;
    this one is about navigating.
    """
    blocking = set(blocking_fields(instance))
    if not blocking:
        return None
    for screen in plan.screens:
        if screen.kind == REPEAT:
            assert screen.repeat_id is not None
            inner = plan.instance_plans.get(screen.repeat_id, ())
            for instance_id in instance.instances.get(screen.repeat_id, []):
                for inner_screen in inner:
                    if any(
                        f"{screen.repeat_id}[{instance_id}].{qid}" in blocking
                        for qid in inner_screen.question_ids
                    ):
                        return Position(screen.index, instance_id, inner_screen.index)
        elif any(qid in blocking for qid in screen.question_ids):
            return Position(screen.index)
    return None
