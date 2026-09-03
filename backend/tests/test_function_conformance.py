"""Every §4.3 function and operator, against every value shape.

`test_conformance.py` runs chosen cases: somebody thought of a construct and
wrote it down. That is the limitation the coverage ledger was built around one
layer up, and the function library had it too — nothing in the corpus had ever
put text where a number belongs, because until dataset columns existed nothing
could. A CSV holds nothing but text, so `int($row.population)` made it an
everyday case overnight and 762 of 1,395 probes turned out to disagree between
the two engines (break 46).

So this set is the cross product rather than a selection, and its whole value
is that nobody picked the cases. Form IR §4.7 is the rule it encodes:

  - an argument that is not of the type §4.3 declares is null
  - evaluation raises for exactly one reason: integer overflow (§4.5)
  - `eq` / `ne` are total across types
  - `concat` renders rather than refuses

`FunctionConformanceTest` (`:shared:form-engine:jvmTest`) runs the same files.
"""

from __future__ import annotations

import json
import pathlib
from datetime import date, datetime

import pytest

from app.modules.form_engine.datasets import InMemoryDatasetSource
from app.modules.form_engine.expression import (
    EvalContext,
    EvaluationError,
    evaluate,
)

MATRIX_DIR = pathlib.Path(__file__).resolve().parents[2] / "conformance" / "functions"
FILES = sorted(MATRIX_DIR.glob("*.json"))

assert FILES, f"no function matrix found in {MATRIX_DIR}"


def _context(document: dict) -> EvalContext:
    today = date.fromisoformat(document.get("context", {}).get("today", "2026-08-28"))
    return EvalContext(
        values={},
        today=today,
        now=datetime.combine(today, datetime.min.time()),
        # `pulldata` reads reference data, and it comes from the file rather
        # than from each runner so both engines read the same bytes.
        datasets=InMemoryDatasetSource(document.get("datasets") or {}),
    )


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_function_matrix(path: pathlib.Path) -> None:
    document = json.loads(path.read_text())
    ctx = _context(document)
    probes = document["probes"]
    assert probes, f"{path.name} holds no probes; an empty file proves nothing"

    for probe in probes:
        where = probe["id"]
        if "raises" in probe:
            # The single exception §4.7 allows. Asserted rather than assumed,
            # so "evaluation is total apart from integer overflow" is a claim
            # this suite makes rather than one it makes about itself.
            with pytest.raises(EvaluationError):
                evaluate(probe["expr"], ctx)
            continue

        try:
            got = evaluate(probe["expr"], ctx)
        except Exception as failure:  # noqa: BLE001 - any raise is the finding
            pytest.fail(
                f"{where}: evaluation raised {type(failure).__name__}: {failure}. "
                "§4.7 makes evaluation total apart from integer overflow — an "
                "expression evaluated on every keystroke must not be able to "
                "stop a form mid-interview."
            )

        want = probe["expect"]
        assert got == want and type(got) is type(want), (
            f"{where}: expected {want!r} ({type(want).__name__}), "
            f"got {got!r} ({type(got).__name__})"
        )


def test_the_spec_examples_are_present_and_hand_written() -> None:
    """`fn.spec.json` is the anchor and must not be generated away.

    The other 43 files were produced by evaluating the reference. That is
    legitimate — docs/project-conventions.md makes the reference the definition where behaviour is
    ambiguous — but it means a change to the reference rewrites its own
    expectations. `fn.spec.json` is typed from §4.7's table instead, and the
    generator refuses to write it when the reference disagrees.
    """
    spec = MATRIX_DIR / "fn.spec.json"
    assert spec.is_file(), "the hand-written anchor file is gone"
    probes = json.loads(spec.read_text())["probes"]
    assert len(probes) >= 20, f"only {len(probes)} spec examples; §4.7's table is longer"

    ids = {p["id"] for p in probes}
    # The two that carry §4.7's least obvious decisions.
    assert "spec.equality_across_types" in ids
    assert "spec.concat_renders_a_number" in ids
