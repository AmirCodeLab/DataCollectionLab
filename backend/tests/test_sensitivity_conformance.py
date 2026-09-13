"""Runs every sensitivity vector against the Python reference check.

The Kotlin engine runs the same files from shared/form-engine. A form that
publishes on one implementation and is refused on the other is a release
blocker: a form author would meet a refusal their builder told them was not
there. Spec: Form IR §10, encryption envelope §5.2.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from app.modules.crypto.envelope import check_sensitivity_propagation, referenced_field
from app.modules.form_engine.runtime import CompiledForm
from app.modules.forms.collectability import check_collectability
from app.modules.forms.service import PublishRefused, check_publishable

VECTOR_DIR = pathlib.Path(__file__).resolve().parents[2] / "conformance" / "sensitivity"
VECTORS = sorted(VECTOR_DIR.glob("*.json"))

assert VECTORS, f"no sensitivity vectors found in {VECTOR_DIR}"


@pytest.mark.parametrize("path", VECTORS, ids=lambda p: p.stem)
def test_vector(path: pathlib.Path) -> None:
    vector = json.loads(path.read_text())
    assert vector["type"] == "sensitivity"

    compiled = CompiledForm(vector["form"])
    assert check_sensitivity_propagation(compiled) == vector["expectedViolations"], (
        f"{vector['id']}: {vector['description']}"
    )


@pytest.mark.parametrize("path", VECTORS, ids=lambda p: p.stem)
def test_the_publish_gate_agrees_with_the_vector(path: pathlib.Path) -> None:
    """The check is only worth having if the publish path actually runs it.

    The gate says more than §10.2 does, so the comparison names the difference
    rather than loosening to a subset. `sensitivity-003` asks a yes/no question
    as a `boolean`, which is the right IR type and a type no client can present,
    so since 12 September 2026 the gate refuses that document twice — once for
    the leak the vector is about and once for the widget that does not exist
    (`docs/known-defects.md` 28). Asserting `expected + check_collectability(...)`
    keeps this an equality: anything the gate reports that neither of those two
    explains still fails here, which a `set(expected) <= set(actual)` would not.
    """
    vector = json.loads(path.read_text())
    expected = vector["expectedViolations"]
    uncollectable = check_collectability(vector["form"])

    if not expected and not uncollectable:
        check_publishable(vector["form"])  # must not raise
        return

    with pytest.raises(PublishRefused) as refusal:
        check_publishable(vector["form"])
    # The order is `check_publishable`'s: §10.2 first, then collectability last.
    assert refusal.value.violations == expected + uncollectable


def test_a_reference_resolves_to_the_field_it_reads_not_the_repeat() -> None:
    """Form IR §4.2.

    Resolving `members[0].income` to `members` would look harmless — `members`
    is not in `fields`, so the check would simply find nothing — and would make
    the whole check blind inside repeats, which is where household income and
    per-member health data actually live.
    """
    assert referenced_field("income") == "income"
    assert referenced_field("members[0].income") == "income"
    assert referenced_field("members[.].income") == "income"
    assert referenced_field("members[].income") == "income"
    # Not a field; resolving it to something harmless is the point.
    assert referenced_field("_metadata.start_time") == "_metadata.start_time"
