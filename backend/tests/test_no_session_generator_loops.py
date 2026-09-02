"""No `async for` over a generator that yields a database session.

This is a lint, written as a test because ruff has no rule for it and the
failure it prevents is silent.

## The trap

```python
async def _session(url):
    async with maker() as session, session.begin():
        yield session          # <- suspended here forever

async for session in _session(url):
    session.add(Project(...))
    break                       # <- nothing after the yield ever runs
```

Breaking — or returning — out of the loop leaves the generator parked at its
`yield`. The `async with` never exits, so `session.begin()` never commits and
the engine is never disposed. The write is simply discarded.

Nothing about that looks wrong at the call site, and the symptom appears
somewhere else entirely: this exact shape made a fixture's project insert
vanish, and surfaced as a foreign-key violation in a different test, in a
different file, against a row that had apparently just been created.

A context manager cannot be exited without its `__aexit__`, so the fix is
`async with _session(url) as session:` and the rule is: **a helper that hands
out a session is an `@asynccontextmanager`, never a bare async generator you
iterate.**

The one legitimate exception is a FastAPI dependency (`app/api/deps.py`,
`app/infrastructure/database.py`), which must be a generator because that is
the protocol FastAPI drives — and FastAPI runs it to completion. Those are not
iterated by our own code, so they are not what this checks for.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

#: `async for <name> in <something>(...)` where the iterable is a call. A plain
#: `async for row in cursor` is fine; it is the call that signals a generator
#: somebody wrote and will abandon.
_ASYNC_FOR_CALL = re.compile(r"^\s*async for\s+\w+\s+in\s+(\w+)\s*\(")

#: Names that mean "this yields a session". Deliberately a small list rather
#: than a clever inference: the check is worth having only if a reader can see
#: at a glance what it will and will not catch.
_SESSION_NAMES = ("session", "_session", "db", "_db", "scratch_db", "make_session")


def _python_files() -> list[pathlib.Path]:
    roots = (REPO_ROOT / "backend", REPO_ROOT / "scripts", REPO_ROOT / "conformance")
    found: list[pathlib.Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        found += [
            path
            for path in root.rglob("*.py")
            if ".venv" not in path.parts
            and "__pycache__" not in path.parts
            # This file quotes the forbidden shape in its own docstring, which
            # is the point of it. Excluded by path rather than by trying to
            # parse out strings and comments: a lint that needs a parser to
            # avoid itself is a lint nobody will keep.
            and path.resolve() != pathlib.Path(__file__).resolve()
        ]
    return found


def test_no_async_for_over_a_session_generator() -> None:
    offenders: list[str] = []
    for path in _python_files():
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            match = _ASYNC_FOR_CALL.match(line)
            if not match:
                continue
            called = match.group(1)
            if called.lower().lstrip("_") in {n.lstrip("_") for n in _SESSION_NAMES}:
                offenders.append(
                    f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()}"
                )

    assert not offenders, (
        "`async for` over a session generator abandons it at the yield: no "
        "commit, no dispose, and the write silently disappears. Use "
        "`async with _session(...) as session:` and make the helper an "
        "@asynccontextmanager.\n\n  " + "\n  ".join(offenders)
    )


def test_this_lint_can_actually_see_the_shape_it_forbids() -> None:
    """A lint that matches nothing is indistinguishable from a clean repo.

    So the pattern is exercised against the exact line that caused the bug,
    rather than trusted because the suite is green.
    """
    caught = _ASYNC_FOR_CALL.match("        async for session in _session(dataset_db):")
    assert caught is not None and caught.group(1) == "_session"

    # ...and does not fire on ordinary async iteration.
    assert _ASYNC_FOR_CALL.match("        async for row in cursor:") is None
    assert _ASYNC_FOR_CALL.match("        async for chunk in response.aiter_bytes():") is None
