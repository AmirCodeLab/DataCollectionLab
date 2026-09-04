"""The normative §4.3 function table, parsed from the specification.

Parsed rather than transcribed, for the reason everything else in this
repository is: the spec is normative (docs/project-conventions.md rule 1), so it is the thing to
read, and a transcription is a second copy of a list that changes.

This exists because the list had **four** entries no engine implemented, and
nothing anywhere could have said so. `regex`, `substr` and `distance` were in
the table, implemented in the Python reference, and absent from the Kotlin
engine's `when` — they fell through to `throw CompileException("function not
implemented")`, so the UCL biomass form's phone-number constraint worked on the
server and threw mid-interview on a phone. `pulldata` was in the table and in
neither engine. The Kotlin signature map even *declared* all four, which is
exactly why declaring is not implementing and why nothing may be checked
against a declaration.

So the check is by **execution**: `conformance/functions` calls every function
in this list on both engines, and a function with no branch throws rather than
answering. See `test_function_surface.py` and `FunctionSurfaceTest`.
"""

from __future__ import annotations

import re
from functools import lru_cache

from app.modules.forms.xlsform.datatypes import FORM_IR_SPEC_FILE, SpecsUnavailable, specs_dir

#: In the §4.3 table and not a function: `if` is an operator with lazy branches
#: (it cannot be a function — both arms would evaluate), and the table lists it
#: for the reader's convenience. Named here rather than filtered silently,
#: because "this one is different" is exactly the kind of exception that grows
#: into a hole nobody can see.
OPERATORS_IN_THE_FUNCTION_TABLE = frozenset({"if"})


@lru_cache(maxsize=1)
def spec_functions() -> frozenset[str]:
    """Every function name in the Form IR spec's §4.3 table.

    The `if` row is excluded — see [OPERATORS_IN_THE_FUNCTION_TABLE].
    """
    text = (specs_dir() / FORM_IR_SPEC_FILE).read_text()
    try:
        table = text.split("### 4.3 Functions", 1)[1].split("#### 4.3.1", 1)[0]
    except IndexError as exc:  # pragma: no cover - a spec without §4.3 is broken
        raise SpecsUnavailable(
            f"{FORM_IR_SPEC_FILE} has no '### 4.3 Functions' table to read"
        ) from exc

    found: set[str] = set()
    for line in table.splitlines():
        if not line.startswith("| `"):
            continue
        # The first column can hold several names on one row:
        # `upper` / `lower` / `trim`, and `int` / `dec` / `str`.
        found.update(re.findall(r"`([a-z_]+)`", line.split("|")[1]))
    if not found:
        raise SpecsUnavailable(f"parsed no functions out of {FORM_IR_SPEC_FILE} §4.3")
    return frozenset(found - OPERATORS_IN_THE_FUNCTION_TABLE)
