"""Runs every reachability vector against the Python reference.

The Kotlin engine runs the same files from shared/form-engine. A form that
publishes on one implementation and is refused on the other is a release
blocker: a form author would meet a refusal their builder told them was not
there. Spec: Form IR §10.2, §10.3, §11.1.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from app.modules.form_engine.reachability import check_reachability, never_shown_questions
from app.modules.form_engine.runtime import CompiledForm
from app.modules.forms.service import PublishRefused, check_publishable

VECTOR_DIR = pathlib.Path(__file__).resolve().parents[2] / "conformance" / "reachability"
VECTORS = sorted(VECTOR_DIR.glob("*.json"))

assert VECTORS, f"no reachability vectors found in {VECTOR_DIR}"


@pytest.mark.parametrize("path", VECTORS, ids=lambda p: p.stem)
def test_vector(path: pathlib.Path) -> None:
    vector = json.loads(path.read_text())
    assert vector["type"] == "reachability"
    form = vector["form"]
    label = f"{vector['id']}: {vector['description']}"

    assert check_reachability(form) == vector["expectedViolations"], label
    assert CompiledForm(form).warnings == vector["expectedWarnings"], label
    assert never_shown_questions(form) == vector["expectedNeverShown"], label


@pytest.mark.parametrize("path", VECTORS, ids=lambda p: p.stem)
def test_the_publish_gate_agrees_with_the_vector(path: pathlib.Path) -> None:
    """The check is only worth having if the publish path actually runs it.

    This is the half scope §0.1 found missing: the importer's reachability
    diagnostic reached the gate only as an import record, which a builder
    structurally cannot supply.
    """
    vector = json.loads(path.read_text())
    expected = vector["expectedViolations"]

    if not expected:
        check_publishable(vector["form"])  # must not raise
        return

    with pytest.raises(PublishRefused) as refusal:
        check_publishable(vector["form"])
    assert refusal.value.violations == expected


def test_the_six_shapes_are_the_probe_s_own() -> None:
    """The vectors are the scope doc's six shapes, not cases written for the
    occasion — lifted from the probe script, in its order."""
    import importlib.util

    script = VECTOR_DIR.parents[1] / "scripts" / "probe_publishable_empty_containers.py"
    spec = importlib.util.spec_from_file_location("probe", script)
    assert spec is not None and spec.loader is not None
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)

    shapes = [(name, ir) for name, ir in probe.SHAPES]
    assert len(shapes) == len(VECTORS) == 6
    for path, (name, ir) in zip(VECTORS, shapes, strict=True):
        vector = json.loads(path.read_text())
        assert vector["shape"] == name
        assert vector["form"] == ir
