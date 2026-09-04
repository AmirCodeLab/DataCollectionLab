"""Runs every conformance vector against the Python reference engine.

The Kotlin engine runs the same vectors from shared/form-engine. Any divergence
between the two is a release blocker.
"""

from __future__ import annotations

import json
import pathlib
from datetime import date, datetime

import pytest

from app.modules.form_engine.datasets import InMemoryDatasetSource
from app.modules.form_engine.runtime import CompiledForm, CompileError, FormInstance
from app.modules.form_engine.screens import (
    blocking_fields,
    build_screen_plan,
    can_finalize,
    first_blocking_screen,
    next_screen,
    previous_screen,
    relevant_screens,
)


class RecordingDatasetSource(InMemoryDatasetSource):
    """An in-memory source that remembers what the engine asked it for.

    The vectors' `selector` and `candidates` expectations are assertions about
    the **question the engine asked**, not about the answer it ended up with,
    and the difference is the entire performance contract (§3.2). Reading them
    off the engine's own output instead was watched to be useless: an engine
    that asked for every row and filtered them itself produced the right
    selector, the right list and the right count, and passed. It is the source
    that has to be the witness.
    """

    def __init__(self, datasets) -> None:  # type: ignore[no-untyped-def]
        super().__init__(datasets)
        self.calls: list[tuple[str, dict, tuple | None, int]] = []

    def rows(self, dataset, selector, equals=None):  # type: ignore[no-untyped-def]
        found = super().rows(dataset, selector, equals)
        self.calls.append((dataset, dict(selector), equals, len(found)))
        return found


VECTOR_DIR = pathlib.Path(__file__).resolve().parents[2] / "conformance" / "vectors"
VECTORS = sorted(VECTOR_DIR.glob("*.json"))

assert VECTORS, f"no conformance vectors found in {VECTOR_DIR}"


def _load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text())


def _state(instance: FormInstance, path: str):
    """Resolve a positional path from a vector to the canonical state entry."""
    return instance.states[instance._canonical(path)]


def _refuse(instance: FormInstance, op: dict, vector_id: str, step_index: int) -> None:
    """Run an operation the spec says must be refused.

    Asserts the refusal and nothing about its wording: a message is English and
    the vectors are the contract between two engines. What stops this passing
    on the wrong refusal is the vector around it — repeat-009 deletes a valid
    index that a permitted delete has already exercised two steps earlier, so a
    bound is the only thing left to refuse it.
    """
    where = f"{vector_id} step {step_index}"
    try:
        if "addInstance" in op:
            instance.add_instance(op["addInstance"])
        elif "deleteInstance" in op:
            instance.delete_instance(
                op["deleteInstance"]["repeat"], op["deleteInstance"]["index"]
            )
        else:
            raise AssertionError(f"{where}: refuse step names no operation: {sorted(op)}")
    except CompileError:
        return
    raise AssertionError(f"{where}: expected {sorted(op)[0]} to be refused, it succeeded")


def _check(instance: FormInstance, expect: dict, vector_id: str, step_index: int) -> None:
    where = f"{vector_id} step {step_index}"

    for path, want in expect.get("relevant", {}).items():
        got = _state(instance, path).relevant
        assert got == want, f"{where}: relevant[{path}] expected {want}, got {got}"

    for path, want in expect.get("values", {}).items():
        got = _state(instance, path).value
        assert got == want, f"{where}: values[{path}] expected {want!r}, got {got!r}"

    for path, want in expect.get("required", {}).items():
        got = _state(instance, path).required
        assert got == want, f"{where}: required[{path}] expected {want}, got {got}"

    for path, want in expect.get("valid", {}).items():
        got = _state(instance, path).valid
        assert got == want, f"{where}: valid[{path}] expected {want}, got {got}"

    for path, want_kinds in expect.get("errors", {}).items():
        got_kinds = [e["kind"] for e in _state(instance, path).errors]
        assert got_kinds == want_kinds, (
            f"{where}: errors[{path}] expected {want_kinds}, got {got_kinds}"
        )

    for repeat_id, want in expect.get("instanceCount", {}).items():
        got = instance.instance_count(repeat_id)
        assert got == want, (
            f"{where}: instanceCount[{repeat_id}] expected {want}, got {got}"
        )

    # --- interpolated text (§7.1) -----------------------------------------

    for path, want_by_language in expect.get("renderedLabels", {}).items():
        for language, want_text in want_by_language.items():
            got_text = instance.rendered_label(path, language)
            assert got_text == want_text, (
                f"{where}: renderedLabels[{path}][{language}]\n"
                f"  expected {want_text!r}\n"
                f"  got      {got_text!r}"
            )

    for path, want_by_language in expect.get("renderedMessages", {}).items():
        for language, want_text in want_by_language.items():
            got_text = instance.rendered_constraint_message(path, language)
            assert got_text == want_text, (
                f"{where}: renderedMessages[{path}][{language}]\n"
                f"  expected {want_text!r}\n"
                f"  got      {got_text!r}"
            )

    for path, want_deps in expect.get("dependsOn", {}).items():
        # Asserted directly, not inferred from a re-render. A label that
        # happened to be recomputed for another reason would pass a render
        # check; this is the edge itself.
        got_deps = sorted(instance.form.fields[path].depends_on)
        assert got_deps == sorted(want_deps), (
            f"{where}: dependsOn[{path}] expected {sorted(want_deps)}, got {got_deps}"
        )

    # --- dataset-backed choice lists (§3.2) -------------------------------
    #
    # Three assertions and not one, deliberately. `choices` alone would pass on
    # an engine that scanned the whole dataset to build the same list, and on a
    # handset those are not the same engine. `selector` compares the
    # decomposition and `candidates` compares how many rows the source was
    # asked to hand back, so a change that quietly stops narrowing fails here
    # while the answer stays right.

    for path, want_values in expect.get("choices", {}).items():
        got_values = [c["value"] for c in instance.choices(path)]
        assert got_values == want_values, (
            f"{where}: choices[{path}] expected {want_values}, got {got_values}"
        )

    for path, want_labels in expect.get("labels", {}).items():
        got_labels = [c["label"] for c in instance.choices(path)]
        assert got_labels == want_labels, (
            f"{where}: labels[{path}] expected {want_labels}, got {got_labels}"
        )

    for path, want_selector in expect.get("selector", {}).items():
        _, got_selector, _, _ = _resolution_call(instance, path, where)
        assert got_selector == want_selector, (
            f"{where}: selector[{path}] expected {want_selector}, got {got_selector} — "
            "this is what the source was asked for, not what the engine computed"
        )

    for path, want_order in expect.get("selectorOrder", {}).items():
        query = instance.form.fields[path].choice_query
        assert query is not None
        got_order = list(query.selector)
        assert got_order == want_order, (
            f"{where}: selectorOrder[{path}] expected {want_order}, got {got_order}"
        )

    for path, want_count in expect.get("candidates", {}).items():
        _, _, _, got_count = _resolution_call(instance, path, where)
        assert got_count == want_count, (
            f"{where}: candidates[{path}] expected {want_count} row(s) back from "
            f"the source, got {got_count} — the engine asked a different "
            "question, which is the performance contract (§3.2) and not only a "
            "count"
        )

    for path, want_scans in expect.get("scans", {}).items():
        query = instance.form.fields[path].choice_query
        assert query is not None
        assert query.scans == want_scans, (
            f"{where}: scans[{path}] expected {want_scans}, got {query.scans}"
        )

    if "formValid" in expect:
        got = instance.is_valid
        assert got == expect["formValid"], (
            f"{where}: formValid expected {expect['formValid']}, got {got}"
        )

    screens = expect.get("screens")
    if screens is not None:
        plan = build_screen_plan(instance.form.ir)
        if "count" in screens:
            assert len(plan) == screens["count"], (
                f"{where}: screens.count expected {screens['count']}, got {len(plan)}"
            )
        for idx, want in screens.get("questions", {}).items():
            got_q = list(plan[int(idx)].question_ids)
            assert got_q == want, (
                f"{where}: screens.questions[{idx}] expected {want}, got {got_q}"
            )
        for idx, want in screens.get("groups", {}).items():
            got_g = plan[int(idx)].group_id
            assert got_g == want, (
                f"{where}: screens.groups[{idx}] expected {want}, got {got_g}"
            )
        for idx, want in screens.get("sections", {}).items():
            got_s = plan[int(idx)].section_id
            assert got_s == want, (
                f"{where}: screens.sections[{idx}] expected {want}, got {got_s}"
            )
        if "relevant" in screens:
            got_r = relevant_screens(plan, instance)
            assert got_r == screens["relevant"], (
                f"{where}: screens.relevant expected {screens['relevant']}, got {got_r}"
            )
        for frm, want in screens.get("next", {}).items():
            got_n = next_screen(plan, instance, int(frm))
            assert got_n == want, (
                f"{where}: screens.next[{frm}] expected {want}, got {got_n}"
            )
        for frm, want in screens.get("previous", {}).items():
            got_p = previous_screen(plan, instance, int(frm))
            assert got_p == want, (
                f"{where}: screens.previous[{frm}] expected {want}, got {got_p}"
            )
        if "canFinalize" in screens:
            got_c = can_finalize(instance)
            assert got_c == screens["canFinalize"], (
                f"{where}: screens.canFinalize expected {screens['canFinalize']}, "
                f"got {got_c}"
            )
        if "blocking" in screens:
            # Vectors address repeat fields positionally, as everywhere else.
            want_b = [instance._canonical(p) for p in screens["blocking"]]
            got_b = blocking_fields(instance)
            assert got_b == want_b, (
                f"{where}: screens.blocking expected {want_b}, got {got_b}"
            )
        if "firstBlocking" in screens:
            got_f = first_blocking_screen(plan, instance)
            assert got_f == screens["firstBlocking"], (
                f"{where}: screens.firstBlocking expected "
                f"{screens['firstBlocking']}, got {got_f}"
            )


def _resolution_call(
    instance: FormInstance, path: str, where: str
) -> tuple[str, dict, tuple | None, int]:
    """Resolve this field's list and return the one call it made to the source.

    Exactly one: resolving a list is one question, and an engine that asked
    twice — once to narrow and once to check — would be doing on a handset the
    thing §3.2 exists to stop.
    """
    source = instance.datasets
    assert isinstance(source, RecordingDatasetSource)
    source.calls.clear()
    instance.choices(path)
    assert len(source.calls) == 1, (
        f"{where}: resolving {path} made {len(source.calls)} calls to the "
        "dataset source; §3.2 is one question, asked once"
    )
    return source.calls[0]


@pytest.mark.parametrize("vector_path", VECTORS, ids=lambda p: p.stem)
def test_vector(vector_path: pathlib.Path) -> None:
    vector = _load(vector_path)
    compiled = CompiledForm(vector["form"])

    ctx = vector.get("context", {})
    today = date.fromisoformat(ctx["today"]) if "today" in ctx else date(2026, 8, 28)
    now = (
        datetime.fromisoformat(ctx["now"])
        if "now" in ctx
        else datetime.combine(today, datetime.min.time())
    )

    # Rows are plain JSON in the vector; the source hands them back unchanged.
    datasets = RecordingDatasetSource(vector.get("datasets") or {})
    instance = FormInstance(compiled, today=today, now=now, datasets=datasets)

    for i, step in enumerate(vector["steps"]):
        if "addInstance" in step:
            instance.add_instance(step["addInstance"])
        if "deleteInstance" in step:
            instance.delete_instance(
                step["deleteInstance"]["repeat"], step["deleteInstance"]["index"]
            )
        if "refuse" in step:
            _refuse(instance, step["refuse"], vector["id"], i)
        if "set" in step:
            instance.set_many(step["set"])
        if "expect" in step:
            _check(instance, step["expect"], vector["id"], i)


def test_determinism_pairs_agree() -> None:
    """determinism-001 and -002 apply the same answers in opposite orders and
    must end in identical state."""
    a = _load(VECTOR_DIR / "determinism-001.json")
    b = _load(VECTOR_DIR / "determinism-002.json")

    def run(vector: dict) -> dict:
        inst = FormInstance(CompiledForm(vector["form"]), today=date(2026, 8, 28))
        for step in vector["steps"]:
            if "set" in step:
                inst.set_many(step["set"])
        return {k: v["value"] for k, v in inst.snapshot().items()}

    assert run(a) == run(b)
