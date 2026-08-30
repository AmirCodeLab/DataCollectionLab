#!/usr/bin/env python3
"""Fail if a test suite exists in this repository and CI does not run it.

Three times a suite has existed here and not been running:

  1. `.github/workflows/ci.yml` was never committed at all, so the conformance
     gate, the crypto vectors and the migration round-trip had never run on a
     push — every quality signal was a person remembering `./scripts/status.sh`.
  2. `npm run lint` exited 0 with no eslint config, for weeks.
  3. `:clients:composeApp:jvmTest` was absent from the kotlin job, so the
     shared UI had no watcher at all.

Each time, the repository read as though it were covered. That is the specific
harm: a suite nobody runs is not neutral, it is a false claim of coverage, and
it is invisible precisely because green is what you expect to see.

So this is not a lint. It answers one question — *is there a test in this repo
that CI does not run?* — and it answers it by enumerating suites from the
sources rather than from a list somebody maintains. A list would drift the same
way the suites did.

## What it checks

Two directions, because a coverage claim can be false either way:

  **Unwatched** — a suite exists on disk and no CI command runs it. The stated
  failure, and the one that has actually happened three times.

  **Hollow** — CI runs something that has no tests in it. That is failure 2's
  shape: the step is green, the log looks right, and nothing was checked. A
  passing step over an empty suite is the paperwork of having been tested.

And one meta-rule: anything this script cannot classify is a **failure**, never
a pass. A guard that silently ignores what it does not recognise decays into
the thing it was written to prevent — it would have said "all clear" about a
`composeApp/src/jvmTest` it had never heard of.

## How each ecosystem is enumerated

  **Gradle** — statically, from test source directories that contain test
  files. Deliberately not from `./gradlew tasks`: this build declares nine test
  tasks and only three have any sources, so the task list would demand CI run
  `:clients:desktopApp:test` (empty) and `:shared:core:iosSimulatorArm64Test`
  (needs a macOS runner). A *task* existing is not a suite existing; test files
  on disk are.

  **pytest** — dynamically, with `--collect-only`. The full collection is
  compared against the union of what each pytest command in ci.yml collects, so
  the marker split (`-m db` / `-m "not db"`) is verified to cover every test
  rather than assumed to. Marker algebra is not something to reason about
  statically; pytest already knows the answer, so it is asked.

  **vitest** — dynamically, with `vitest list`. Compared against the test files
  on disk, so a file that falls outside the `include` glob is caught. That is
  the same class of bug as the missing Gradle task, one config layer down.

## Running it

    python scripts/check_ci_runs_every_suite.py            # local
    python scripts/check_ci_runs_every_suite.py --strict   # what CI runs

`--strict` is the difference that matters. Without it, a dynamic check whose
toolchain is missing is reported as SKIPPED. With it, a skip is a failure —
because "we could not check" reported as green is the whole problem this file
exists about.

Needs PyYAML (`pip install pyyaml`). Parsing the workflow by regex was the
alternative and it is not one: this file must not be the next thing that is
subtly wrong and looks fine.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CI_FILE = ROOT / ".github" / "workflows" / "ci.yml"

# A directory under `src/` is a test source set if it is `test` or ends in
# `Test`. Each one maps to the Gradle task that runs it. An entry mapping to
# None is a suite no Linux CI runner can execute; it is still reported, and it
# still fails, because "nobody runs it" is true whatever the reason.
TEST_SOURCE_SETS: dict[str, str | None] = {
    "test": "{project}:test",
    "jvmTest": "{project}:jvmTest",
    # commonTest compiles into every target's test binary. jvmTest is the one a
    # Linux runner can execute, so that is what CI is required to run.
    "commonTest": "{project}:jvmTest",
    "androidHostTest": "{project}:testAndroidHostTest",
    "androidUnitTest": "{project}:testDebugUnitTest",
    "iosTest": None,
    "iosSimulatorArm64Test": None,
    "androidDeviceTest": None,
    "androidInstrumentedTest": None,
}

CANNOT_RUN_ON_LINUX = {
    "iosTest": "needs a macOS runner and an iOS simulator",
    "iosSimulatorArm64Test": "needs a macOS runner and an iOS simulator",
    "androidDeviceTest": "needs an emulator or a connected device",
    "androidInstrumentedTest": "needs an emulator or a connected device",
}

TEST_FILE_SUFFIXES = (".kt", ".java")


# --------------------------------------------------------------------------
# The workflow
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CiCommand:
    """One shell line CI runs, with the directory it runs in."""

    job: str
    step: str
    workdir: str
    line: str

    def __str__(self) -> str:
        return f"{self.job} / {self.step}"


def read_ci_commands() -> list[CiCommand]:
    try:
        import yaml
    except ModuleNotFoundError:
        sys.exit(
            "This script parses the workflow as YAML and PyYAML is not installed.\n"
            "  pip install pyyaml"
        )

    if not CI_FILE.exists():
        # Failure 1, and the one shape this script cannot catch from inside CI:
        # with no workflow there is no job to run it. It is caught locally and
        # by scripts/status.sh, which is why both of those exist.
        sys.exit(f"There is no {CI_FILE.relative_to(ROOT)}. Nothing in this repo is watched.")

    workflow = yaml.safe_load(CI_FILE.read_text())
    commands: list[CiCommand] = []
    for job_id, job in (workflow.get("jobs") or {}).items():
        job_dir = ((job.get("defaults") or {}).get("run") or {}).get("working-directory", ".")
        for step in job.get("steps") or []:
            run = step.get("run")
            if not run:
                continue
            workdir = step.get("working-directory", job_dir)
            name = step.get("name", "(unnamed step)")
            for line in run.splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    commands.append(CiCommand(job_id, name, workdir, line))
    return commands


# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------


@dataclass
class Report:
    rows: list[tuple[str, str, str]] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    skips: list[str] = field(default_factory=list)

    def ok(self, suite: str, size: str, run_by: str) -> None:
        self.rows.append((suite, size, run_by))

    def fail(self, message: str) -> None:
        self.failures.append(message)

    def skip(self, message: str) -> None:
        self.skips.append(message)


# --------------------------------------------------------------------------
# Gradle
# --------------------------------------------------------------------------


def gradle_projects() -> list[str]:
    settings = (ROOT / "settings.gradle.kts").read_text()
    return re.findall(r'include\("(:[^"]+)"\)', settings)


def project_dir(project: str) -> Path:
    return ROOT / project.lstrip(":").replace(":", "/")


def has_test_files(directory: Path) -> int:
    return sum(
        1
        for path in directory.rglob("*")
        if path.is_file() and path.suffix in TEST_FILE_SUFFIXES
    )


def runs_gradle_task(commands: list[CiCommand], task: str) -> CiCommand | None:
    # Bounded so `:shared:core:jvmTest` is not matched by a longer task name
    # that merely starts with it.
    pattern = re.compile(re.escape(task) + r"(?![\w:-])")
    for command in commands:
        if "gradlew" in command.line and pattern.search(command.line):
            return command
    return None


def check_gradle(commands: list[CiCommand], report: Report) -> None:
    required: dict[str, Path] = {}

    for project in gradle_projects():
        src = project_dir(project) / "src"
        if not src.is_dir():
            continue
        for entry in sorted(src.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name != "test" and not entry.name.endswith("Test"):
                continue  # a main source set

            if entry.name not in TEST_SOURCE_SETS:
                report.fail(
                    f"{entry.relative_to(ROOT)} is a test source set this script does not "
                    f"know. Add '{entry.name}' to TEST_SOURCE_SETS with the Gradle task "
                    f"that runs it — an unrecognised suite must not read as a covered one."
                )
                continue

            count = has_test_files(entry)
            if count == 0:
                continue  # a directory with no tests in it is not a suite

            template = TEST_SOURCE_SETS[entry.name]
            if template is None:
                why = CANNOT_RUN_ON_LINUX.get(entry.name, "no CI runner can execute it")
                report.fail(
                    f"{entry.relative_to(ROOT)} holds {count} test file(s) and nothing runs "
                    f"them: {why}. Either add a job that can, or delete the suite — leaving "
                    f"it is a coverage claim nothing backs."
                )
                continue

            required[template.format(project=project)] = entry

    for task, source in sorted(required.items()):
        command = runs_gradle_task(commands, task)
        if command is None:
            report.fail(
                f"{source.relative_to(ROOT)} holds {has_test_files(source)} test file(s) and "
                f"no CI step runs {task}. Add it to the kotlin job."
            )
        else:
            report.ok(task, f"{has_test_files(source)} files", str(command))

    # The other direction: a Gradle test task CI runs that has nothing in it.
    for command in commands:
        if "gradlew" not in command.line:
            continue
        for token in shlex.split(command.line):
            if not token.startswith(":") or not re.search(r"[Tt]est", token):
                continue
            if token not in required:
                report.fail(
                    f"{command} runs {token}, which has no test sources. A green step over "
                    f"an empty suite is the paperwork of having been tested."
                )


# --------------------------------------------------------------------------
# pytest
# --------------------------------------------------------------------------


def collect_pytest(workdir: Path, args: list[str]) -> set[str] | None:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", *args],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode not in (0, 5):  # 5 == collected nothing
        return None
    return {
        line.strip()
        for line in result.stdout.splitlines()
        if "::" in line and not line.startswith(" ")
    }


def check_pytest(commands: list[CiCommand], report: Report, strict: bool) -> None:
    backend = ROOT / "backend"
    if not backend.is_dir():
        return

    everything = collect_pytest(backend, [])
    if everything is None:
        message = "pytest could not collect — install the backend (pip install -e '.[dev]')"
        report.fail(message) if strict else report.skip(message)
        return

    covered: set[str] = set()
    runners: list[str] = []
    for command in commands:
        tokens = shlex.split(command.line)
        if "pytest" not in tokens:
            continue
        args = [t for t in tokens[tokens.index("pytest") + 1 :] if t != "-v"]
        collected = collect_pytest(ROOT / command.workdir, args)
        if collected is None:
            report.fail(f"{command} is a pytest command whose collection failed: {command.line}")
            continue
        covered |= collected
        runners.append(f"{command} ({len(collected)})")

    if not runners:
        report.fail("No CI step runs pytest, and backend/tests exists.")
        return

    missing = everything - covered
    if missing:
        shown = "\n      ".join(sorted(missing)[:10])
        more = "" if len(missing) <= 10 else f"\n      ... and {len(missing) - 10} more"
        report.fail(
            f"{len(missing)} backend test(s) are collected by pytest and by no CI command. "
            f"The marker split does not cover them:\n      {shown}{more}"
        )
    else:
        report.ok("backend/tests", f"{len(everything)} tests", " + ".join(runners))


# --------------------------------------------------------------------------
# vitest
# --------------------------------------------------------------------------


def check_vitest(commands: list[CiCommand], report: Report, strict: bool) -> None:
    web = ROOT / "web"
    if not (web / "package.json").is_file():
        return

    on_disk = {
        os.path.relpath(path, web)
        for pattern in ("src/**/*.test.ts", "src/**/*.test.tsx")
        for path in glob.glob(str(web / pattern), recursive=True)
    }
    if not on_disk:
        return

    runner = next(
        (c for c in commands if c.workdir.rstrip("/").endswith("web") and "npm test" in c.line),
        None,
    )
    if runner is None:
        report.fail(
            f"web has {len(on_disk)} test file(s) and no CI step runs `npm test` in it."
        )
        return

    if not (web / "node_modules").is_dir():
        message = "vitest could not list — run `npm ci` in web/"
        report.fail(message) if strict else report.skip(message)
        return

    result = subprocess.run(
        ["npx", "vitest", "list", "--run"],
        cwd=web,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if result.returncode != 0:
        report.fail(f"`vitest list` failed in web/:\n{result.stderr.strip()[:500]}")
        return

    collected = {
        line.split(" > ")[0].strip()
        for line in result.stdout.splitlines()
        if " > " in line
    }
    missing = on_disk - collected
    if missing:
        report.fail(
            f"{len(missing)} web test file(s) exist and vitest does not collect them — check "
            f"`test.include` in web/vite.config.ts:\n      " + "\n      ".join(sorted(missing))
        )
    else:
        report.ok("web (vitest)", f"{len(on_disk)} files", str(runner))


# --------------------------------------------------------------------------
# npm scripts
# --------------------------------------------------------------------------


def check_npm_scripts(commands: list[CiCommand], report: Report) -> None:
    """Every `npm run X` in CI names a script that exists, and lint has a config.

    The second half is failure 2 exactly: `npm run lint` ran eslint, eslint
    found no configuration, and eslint at the time exited 0. eslint 9 refuses
    instead, so this is belt-and-braces — but the belt is one line and the
    failure it guards lasted weeks.
    """
    import json

    package = ROOT / "web" / "package.json"
    if not package.is_file():
        return
    scripts = json.loads(package.read_text()).get("scripts", {})

    for command in commands:
        tokens = shlex.split(command.line)
        if tokens[:2] != ["npm", "run"] or len(tokens) < 3:
            continue
        name = tokens[2]
        if name not in scripts:
            report.fail(f"{command} runs `npm run {name}`, which web/package.json does not define.")
        elif "eslint" in scripts[name] and not list((ROOT / "web").glob("eslint.config.*")):
            report.fail(
                f"{command} runs eslint and web/ has no eslint.config.* — "
                f"a lint with no configuration checks nothing."
            )


# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat a check that could not run as a failure (what CI passes)",
    )
    args = parser.parse_args()

    commands = read_ci_commands()
    report = Report()

    check_gradle(commands, report)
    check_pytest(commands, report, args.strict)
    check_vitest(commands, report, args.strict)
    check_npm_scripts(commands, report)

    if report.rows:
        width = max(len(row[0]) for row in report.rows)
        size = max(len(row[1]) for row in report.rows)
        print("Suites, and the CI step that runs each:\n")
        for suite, count, run_by in report.rows:
            print(f"  {suite:<{width}}  {count:>{size}}  <-  {run_by}")
        print()

    for message in report.skips:
        print(f"SKIPPED: {message}")
    if report.skips:
        print("  (--strict turns these into failures; CI passes --strict.)\n")

    if report.failures:
        print(f"{len(report.failures)} problem(s):\n")
        for message in report.failures:
            print(f"  - {message}")
        print()
        return 1

    print(f"Every suite found is run by CI ({len(report.rows)} suites).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
