"""Runs every document-shape vector against the Python reference engine.

The Kotlin engine runs the same files from shared/form-engine. A document that
compiles on one implementation and is refused on the other is a release blocker,
not a platform difference — and this is the class of divergence the main vector
suite could not see, because every vector there assumes a form that compiled.

Spec: Form IR §10.1 (document errors) and §9 (irVersion).
"""

from __future__ import annotations

import json
import pathlib

import pytest

from app.modules.form_engine.document import DocumentError
from app.modules.form_engine.runtime import CompiledForm

VECTOR_DIR = pathlib.Path(__file__).resolve().parents[2] / "conformance" / "malformed"
VECTORS = sorted(VECTOR_DIR.glob("*.json"))

assert VECTORS, f"no document-shape vectors found in {VECTOR_DIR}"


def load(path: pathlib.Path) -> dict:
    vector = json.loads(path.read_text())
    assert vector["type"] == "malformed"
    return vector


@pytest.mark.parametrize("path", VECTORS, ids=lambda p: p.stem)
def test_vector(path: pathlib.Path) -> None:
    vector = load(path)
    where = f"{vector['id']}: {vector['description']}"

    if not vector["refused"]:
        # Compiles, and the note says why it must. A gate tightened past the
        # spec strands forms that were valid when they were published.
        CompiledForm(vector["form"])
        return

    with pytest.raises(DocumentError) as raised:
        CompiledForm(vector["form"])

    assert raised.value.reason == vector["reason"], (
        f"{where}: expected reason {vector['reason']!r}, got {raised.value.reason!r}"
    )
    assert raised.value.where == vector["where"], (
        f"{where}: expected location {vector['where']!r}, got {raised.value.where!r}"
    )


@pytest.mark.parametrize("path", VECTORS, ids=lambda p: p.stem)
def test_a_refusal_is_a_compile_error_to_every_caller(path: pathlib.Path) -> None:
    """DocumentError must stay a CompileError.

    Nothing in this repository catches DocumentError by name. The API routes,
    `check_publishable` and `scripts/seed_dev.py` all catch CompileError, and
    they refuse a malformed document only because DocumentError is one. Break
    that inheritance and every one of them goes back to a 500 — with the gate
    still in place and still passing its own tests.
    """
    from app.modules.form_engine.expression import CompileError

    vector = load(path)
    if not vector["refused"]:
        return

    with pytest.raises(CompileError):
        CompiledForm(vector["form"])


def test_the_set_covers_every_reason_in_the_spec() -> None:
    """§10.1 names five reasons. A reason with no vector is an unchecked rule."""
    reasons = {v["reason"] for v in map(load, VECTORS) if v["refused"]}
    assert reasons == {
        "not_an_object",
        "missing_field",
        "wrong_type",
        "unknown_node_type",
        "unknown_ir_version",
    }


def test_the_set_still_proves_what_is_accepted() -> None:
    """A set of nothing but refusals only proves the engine will refuse."""
    accepted = [v for v in map(load, VECTORS) if not v["refused"]]
    assert len(accepted) >= 3, "the accepted documents are what bound the gate"
