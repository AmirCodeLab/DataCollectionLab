"""§4.3's table is the list of functions, and both engines must implement it.

This exists because the guarantee had a hole big enough to ship a mid-interview
crash, and nothing in the repository could have said so.

`regex`, `substr` and `distance` were in the spec's table, implemented in the
Python reference, and **absent from the Kotlin engine's `when`** — they fell
through to `throw CompileException("function not implemented")`. A form using
one worked perfectly on the server and threw on a phone the moment the field was
evaluated, and the UCL biomass form's phone-number constraint uses `regex`.
`pulldata` was in the table and in neither engine. All four were *declared* in
Kotlin's signature map, which is the whole lesson: **a declaration is not an
implementation, so nothing may be checked against a declaration.**

The check is therefore by execution, and it is not this file that does it —
`conformance/functions` calls every function in the table on both engines, and a
function with no branch throws instead of answering. What this file does is make
that coverage impossible to lose: the matrix is generated from the table, this
asserts the two still agree, and `FunctionSurfaceTest` asserts the same thing
from the Kotlin side.

Break 49.
"""

from __future__ import annotations

import json
import pathlib

from app.modules.form_engine.expression import FUNCTIONS
from app.modules.form_engine.spec import OPERATORS_IN_THE_FUNCTION_TABLE, spec_functions

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
MATRIX_DIR = REPO_ROOT / "conformance" / "functions"


def _called_in_the_matrix() -> set[str]:
    """Every function name the committed matrix actually calls.

    Read out of the probes rather than off the file names, because a file can
    exist and probe nothing — which is the same "green paperwork over nothing"
    the suites guard refuses one level up.
    """
    called: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if node.get("op") == "call" and isinstance(node.get("fn"), str):
                called.add(node["fn"])
            for arg in node.get("args") or []:
                walk(arg)

    for path in MATRIX_DIR.glob("*.json"):
        for probe in json.loads(path.read_text())["probes"]:
            walk(probe["expr"])
    return called


def test_the_spec_table_parses_to_something() -> None:
    # If this fails the rest prove nothing, so it is asserted first and alone.
    functions = spec_functions()
    assert len(functions) >= 25, f"only parsed {sorted(functions)} out of §4.3"
    assert "regex" in functions and "pulldata" in functions, (
        "the four that had no implementation must be in the parsed list, or "
        "this guard would not have caught the thing it was written for"
    )


def test_every_function_in_the_spec_is_implemented_by_the_reference() -> None:
    missing = sorted(spec_functions() - set(FUNCTIONS))
    assert not missing, (
        f"§4.3 declares {', '.join(missing)} and the Python reference does not "
        "implement them. A form using one compiles, publishes, deploys, and "
        "raises when the field is evaluated."
    )


def test_the_reference_implements_nothing_the_spec_does_not_declare() -> None:
    """The other direction, and it is not pedantry.

    A function the engine has and the spec does not is a function the Kotlin
    engine has no reason to implement and no way to know about — which is one
    end of exactly the asymmetry that shipped. It is also a function no importer
    will ever emit, so it is dead weight pretending to be a feature.
    """
    extra = sorted(set(FUNCTIONS) - spec_functions() - OPERATORS_IN_THE_FUNCTION_TABLE)
    assert not extra, (
        f"the reference implements {', '.join(extra)} and §4.3 does not declare "
        "them. Either add a row to the table or delete the implementation; a "
        "function only one engine knows about is how the last hole started."
    )


def test_the_conformance_matrix_calls_every_function_in_the_table() -> None:
    """The coverage that turns the table into an executed check.

    This is the assertion that would have caught `regex`, `substr`, `distance`
    and `pulldata`. Not because it inspects an engine — it inspects the *matrix*
    — but because a function the matrix calls is a function both engines are
    made to run, and one with no branch throws.
    """
    uncalled = sorted(spec_functions() - _called_in_the_matrix())
    assert not uncalled, (
        f"§4.3 declares {', '.join(uncalled)} and conformance/functions never "
        "calls them, so neither engine is ever made to run them. Re-run "
        "`python conformance/generate_function_matrix.py`, which refuses to "
        "write a matrix that misses one."
    )


def test_the_matrix_calls_nothing_the_table_does_not_declare() -> None:
    invented = sorted(_called_in_the_matrix() - spec_functions())
    assert not invented, (
        f"the matrix calls {', '.join(invented)}, which §4.3 does not declare — "
        "the table and the tests disagree about what exists"
    )


def test_the_kotlin_half_of_this_guard_still_exists() -> None:
    """Each half asserts the other is there.

    The suites guard catches a CI step that stops running a suite. It cannot
    catch a test *file* being deleted — the suite reports one fewer and stays
    green — and this guard is worth exactly nothing on one engine, since the
    engine it was written about is the other one.
    """
    kotlin = (
        REPO_ROOT
        / "shared/form-engine/src/jvmTest/kotlin/com/dcp/form/FunctionSurfaceTest.kt"
    )
    assert kotlin.is_file(), (
        f"{kotlin.relative_to(REPO_ROOT)} is gone. It is the half that checks the "
        "KOTLIN engine implements §4.3, which is the engine that was missing four "
        "functions — without it this file only proves the reference agrees with "
        "itself."
    )
    assert "4.3 Functions" in kotlin.read_text(), (
        "the Kotlin half no longer reads the spec's function table"
    )
