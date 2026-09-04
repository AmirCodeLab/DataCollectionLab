#!/usr/bin/env python3
"""Fail if source code exists in this repository and no gate reads it.

    python scripts/check_every_directory_is_gated.py            # local
    python scripts/check_every_directory_is_gated.py --strict   # what CI runs

`check_ci_runs_every_suite.py` answers *"is every suite run?"*. This answers the
question one layer out and nothing was asking: **"is every directory covered?"**

The two are different, and the gap between them is where this repository has
just been caught for the fifth time. CI runs `ruff check .` and `mypy app` from
`backend/`, so `scripts/` and `conformance/` had **never been linted or type
checked** — not once. That is `scripts/seed_dev.py`, `dev_project_key.py`,
`import_xlsform.py` (the same importer the API uses, run from a terminal),
`generate_api_contract.py` (which decides what the committed contract says) and
every conformance vector generator. Real code doing real work, outside every
gate, and it read as covered because the CI job is called "backend (ruff, mypy,
pytest)" and is green.

When they were finally checked: 3 ruff errors and 602 mypy errors, including a
wrong return annotation in the function-matrix generator that had been there
since it was written.

## The shape of the check

The list of *gates* is read from `.github/workflows/ci.yml`, so the check tracks
what CI actually does rather than what somebody wrote down. The list of *source*
is enumerated from disk. Every source directory must be either covered by a gate
or named in `ACKNOWLEDGED` below with a reason.

**Anything unclassified is a failure, never a pass** — the same meta-rule the
suites guard carries, for the same reason. A new language, a new top-level
directory, or a Python package appearing outside the checked roots fails here
until somebody either covers it or writes down why not. An exemption with a
reason is a decision; an exemption by omission is the hole this file exists to
close.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"

#: Directories that hold no source of their own.
SKIP = {
    ".git", ".github", ".gradle", ".idea", ".kotlin", ".ruff_cache", ".mypy_cache",
    ".pytest_cache", "__pycache__", "node_modules", "build", "dist", ".venv",
    "venv", "gradle", "reports", "var", "docs", "specs", "deploy", "web-forms",
    "dcp_backend.egg-info", "site-packages",
}

#: Extension -> the kind of gate that must read it.
LANGUAGES = {
    ".py": "python",
    ".kt": "kotlin",
    ".ts": "typescript",
    ".tsx": "typescript",
}

#: Source that no gate reads, each with the reason it is out and what closing it
#: would take. Being on this list is a decision somebody made and can be argued
#: with; being absent from it is a hole nobody knew about.
#:
#: A row here is NOT permission to leave it forever. It is the difference
#: between a gap that is recorded and a gap that is invisible, which is the
#: whole distinction `docs/known-defects.md` exists to keep.
ACKNOWLEDGED: dict[str, str] = {
    "kotlin": (
        "No ktlint, detekt or spotless is configured at all, so docs/project-conventions.md's "
        "'official style, explicit visibility on public API' is enforced by "
        "nobody. Adding one is a real change with a large first diff and it "
        "belongs in its own commit. The Kotlin *tests* do run (see "
        "check_ci_runs_every_suite.py); it is the style and static analysis "
        "that have no gate."
    ),
    "python:backend/tests": (
        "ruff covers it; mypy does not. `mypy tests` reports 212 errors across "
        "21 files, almost all missing annotations on test functions. Worth "
        "doing and too large to bundle with the fix that found it."
    ),
    "python:backend/migrations": (
        "ruff covers it; mypy does not. Alembic's generated `upgrade`/"
        "`downgrade` stubs are untyped by construction and the revision files "
        "are append-only history — typing them retroactively buys little."
    ),
}


def gates() -> dict[str, list[str]]:
    """The gates CI actually runs, as absolute roots, keyed by `language:kind`.

    Parsed from the workflow rather than listed here, so the check tracks what
    CI does. A step's `working-directory` is what its paths are relative to,
    which is the detail that hid this bug: `ruff check .` reads as "everything"
    and means "everything under `backend/`".
    """
    text = WORKFLOW.read_text()
    found: dict[str, list[str]] = {
        "python:lint": [], "python:types": [],
        "typescript:lint": [], "typescript:types": [],
    }
    directory = "."
    for raw in text.splitlines():
        working = re.search(r"working-directory:\s*(\S+)", raw)
        if working:
            directory = working.group(1)
        line = raw.strip()

        for tool, key in (("ruff check", "python:lint"), ("mypy", "python:types")):
            command = re.search(rf"run:\s*{tool}\s+(.*)$", line)
            if command:
                for target in command.group(1).split():
                    if not target.startswith("-"):
                        found[key].append(str((REPO / directory / target).resolve()))

        # npm scripts take no path: the gate covers its working directory.
        for script, key in (("lint", "typescript:lint"), ("typecheck", "typescript:types")):
            if re.search(rf"run:\s*npm run {script}\s*$", line):
                found[key].append(str((REPO / directory).resolve()))
    return found


def source_directories() -> dict[str, set[pathlib.Path]]:
    """Every directory holding source, by language."""
    found: dict[str, set[pathlib.Path]] = {}
    for path in REPO.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP for part in path.relative_to(REPO).parts):
            continue
        language = LANGUAGES.get(path.suffix)
        if language is None:
            continue
        found.setdefault(language, set()).add(path.parent)
    return found


def _acknowledged(language: str, relative: pathlib.Path) -> bool:
    """True when this directory, or a directory above it, is excused by name."""
    if language in ACKNOWLEDGED:
        return True
    candidate = relative
    while True:
        if f"{language}:{candidate}" in ACKNOWLEDGED:
            return True
        if candidate == candidate.parent:
            return False
        candidate = candidate.parent


def covered_by(directory: pathlib.Path, roots: list[str]) -> bool:
    return any(
        directory == pathlib.Path(root) or pathlib.Path(root) in directory.parents
        for root in roots
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true",
                        help="a missing workflow is a failure, not a skip")
    arguments = parser.parse_args()

    if not WORKFLOW.exists():
        print("ERROR  no .github/workflows/ci.yml — there is nothing to check "
              "against, which is failure 1 in check_ci_runs_every_suite.py",
              file=sys.stderr)
        return 1 if arguments.strict else 0

    checks = gates()
    sources = source_directories()
    problems: list[str] = []

    print("Source directories, and the gates that read them:\n")
    for language in sorted(sources):
        for directory in sorted(sources[language]):
            relative = directory.relative_to(REPO)
            excused = _acknowledged(language, relative)

            if f"{language}:lint" not in checks:
                # A language with no gate defined at all.
                state = "NO GATE"
            else:
                linted = covered_by(directory, checks[f"{language}:lint"])
                typed = covered_by(directory, checks[f"{language}:types"])
                state = ("lint + types" if linted and typed
                         else "lint only" if linted
                         else "types only" if typed
                         else "NOTHING")

            if state != "lint + types" and not excused:
                problems.append(
                    f"{relative} ({language}) is gated by {state.lower()} — add it "
                    "to the lint/type commands in ci.yml, or to ACKNOWLEDGED "
                    "with a reason"
                )
            note = "  (acknowledged)" if excused and state != "lint + types" else ""
            print(f"  {str(relative):<40} {language:<11} {state}{note}")

    print("\nAcknowledged gaps:")
    for key, reason in sorted(ACKNOWLEDGED.items()):
        print(f"  {key}: {reason.split('.')[0]}.")

    if problems:
        print("\nFAIL", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1

    print("\nEvery source directory is read by a gate, or acknowledged with a "
          f"reason ({sum(len(v) for v in sources.values())} directories).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
