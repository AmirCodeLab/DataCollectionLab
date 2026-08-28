"""Runs every conformance vector against the Python reference engine.

The Kotlin engine runs the same vectors from shared/form-engine. Any divergence
between the two is a release blocker.
"""

from __future__ import annotations

import json
import pathlib
from datetime import date, datetime

import pytest

from app.modules.form_engine.runtime import CompiledForm, FormInstance

VECTOR_DIR = pathlib.Path(__file__).resolve().parents[2] / "conformance" / "vectors"
VECTORS = sorted(VECTOR_DIR.glob("*.json"))

assert VECTORS, f"no conformance vectors found in {VECTOR_DIR}"


def _load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text())


def _state(instance: FormInstance, path: str):
    """Resolve a positional path from a vector to the canonical state entry."""
    return instance.states[instance._canonical(path)]


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

    if "formValid" in expect:
        got = instance.is_valid
        assert got == expect["formValid"], (
            f"{where}: formValid expected {expect['formValid']}, got {got}"
        )


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

    instance = FormInstance(compiled, today=today, now=now)

    for i, step in enumerate(vector["steps"]):
        if "addInstance" in step:
            instance.add_instance(step["addInstance"])
        if "deleteInstance" in step:
            instance.delete_instance(
                step["deleteInstance"]["repeat"], step["deleteInstance"]["index"]
            )
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
