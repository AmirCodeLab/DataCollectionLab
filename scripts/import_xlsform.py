#!/usr/bin/env python3
"""Import an XLSForm locally, and write the report somebody can be sent.

    python scripts/import_xlsform.py survey.xlsx
    python scripts/import_xlsform.py survey.xlsx --out reports/
    python scripts/import_xlsform.py survey.xlsx --ir household.json
    python scripts/import_xlsform.py survey.xlsx --datasets ./csvs/

A `select_one_from_file` names a CSV that ships *beside* the workbook, so the
directory holding the .xlsx is searched by default and `--datasets` points
somewhere else. Nothing is guessed at: a file the survey sheet names and this
cannot find is reported by name, because a question whose list did not arrive
has no options at all and looks exactly like one that does.

Runs the same importer the API does, in the same process — not a reimplementation
and not an HTTP call. A second code path here would be a second set of answers
about what a form becomes, and the one a form author was shown would be whichever
they happened to use.

Exits 1 when the form has errors, so this is usable in a build. The IR is still
written when asked for: the author needs every problem in one pass, and a form
they can look at is how they find the next one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.modules.forms.xlsform import IMPORTER_VERSION  # noqa: E402
from app.modules.forms.xlsform.datatypes import SpecsUnavailable  # noqa: E402
from app.modules.forms.xlsform.importer import (  # noqa: E402
    CoverageHole,
    ImportFailed,
    import_workbook,
)
from app.modules.forms.xlsform.report import render_html, render_markdown  # noqa: E402

_SEVERITY_MARK = {"error": "ERROR  ", "warning": "warning", "info": "note   "}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import an XLSForm and report what did not survive.",
    )
    parser.add_argument("workbook", type=pathlib.Path, help="the .xlsx to import")
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        help="directory to write <name>-import-report.md and .html into",
    )
    parser.add_argument("--ir", type=pathlib.Path, help="write the Form IR to this file")
    parser.add_argument(
        "--datasets",
        type=pathlib.Path,
        help="directory holding the companion .csv files (default: beside the workbook)",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="print only the summary, not every diagnostic"
    )
    arguments = parser.parse_args()

    if not arguments.workbook.is_file():
        print(f"no such file: {arguments.workbook}", file=sys.stderr)
        return 2

    companion_dir = arguments.datasets or arguments.workbook.parent
    if arguments.datasets and not arguments.datasets.is_dir():
        print(f"no such directory: {arguments.datasets}", file=sys.stderr)
        return 2
    # Every CSV in the directory is offered, not only the ones the form names.
    # The importer is what decides which are wanted — and it reports a file
    # supplied that nothing asked for, which is how a rename on one side of the
    # pair gets noticed instead of showing up as a missing list.
    companions = {
        path.name: path.read_bytes()
        for path in sorted(companion_dir.glob("*.csv"))
        if path.is_file()
    }

    data = arguments.workbook.read_bytes()
    try:
        result = import_workbook(data, companions=companions)
    except ImportFailed as failure:
        print(f"{arguments.workbook.name}: {failure}", file=sys.stderr)
        return 2
    except SpecsUnavailable as failure:
        # Refusing rather than guessing which types a device can collect: both
        # defaults are a lie an author would act on.
        print(f"cannot import: {failure}", file=sys.stderr)
        return 2
    except CoverageHole as failure:
        print(f"IMPORTER BUG: {failure}", file=sys.stderr)
        return 3

    name = arguments.workbook.name
    if not arguments.quiet:
        for diagnostic in result.diagnostics:
            where = str(diagnostic.ref) if diagnostic.ref else "-"
            print(f"  {_SEVERITY_MARK[diagnostic.severity]}  {where:52}  {diagnostic.message}")
        if result.diagnostics:
            print()

    counts = {
        severity: sum(1 for d in result.diagnostics if d.severity == severity)
        for severity in ("error", "warning", "info")
    }
    print(f"{name}: {result.questions} question(s) from {result.survey_rows} survey row(s)")
    for dataset in result.datasets:
        print(
            f"  dataset {dataset.key:<24} {dataset.row_count:>7,} rows  "
            f"{len(dataset.columns_used)}/{len(dataset.columns)} columns read  "
            f"{dataset.checksum[:19]}…"
        )
    print(
        f"  {counts['error']} error(s), {counts['warning']} warning(s), {counts['info']} note(s)"
    )
    print(
        f"  coverage: {result.coverage['cells']} non-empty cells, all accounted for"
        " (a cell that produced nothing and went unreported fails the import)"
    )
    instrumentation = result.instrumentation
    if instrumentation.unsupported_functions or instrumentation.unsupported_types:
        print(
            "  needed and missing: "
            + ", ".join(
                f"{k}()×{v}" for k, v in sorted(instrumentation.unsupported_functions.items())
            )
            + (" " if instrumentation.unsupported_functions else "")
            + ", ".join(f"{k}×{v}" for k, v in sorted(instrumentation.unsupported_types.items()))
        )

    if arguments.out:
        arguments.out.mkdir(parents=True, exist_ok=True)
        stem = arguments.workbook.stem
        markdown = arguments.out / f"{stem}-import-report.md"
        markdown.write_text(
            render_markdown(result, source_name=name, form_id=result.form["formId"])
        )
        page = arguments.out / f"{stem}-import-report.html"
        page.write_text(render_html(result, source_name=name, form_id=result.form["formId"]))
        print(f"  report: {markdown}")
        print(f"          {page}")

    if arguments.ir:
        arguments.ir.parent.mkdir(parents=True, exist_ok=True)
        arguments.ir.write_text(json.dumps(result.form, indent=2, ensure_ascii=False) + "\n")
        print(f"  IR:     {arguments.ir}")

    print(f"  source sha256: {hashlib.sha256(data).hexdigest()}")
    print(f"  importer:      {IMPORTER_VERSION}")

    if result.publishable:
        print("\nThis form can be published.")
        return 0
    print("\nThis form CANNOT be published until the errors above are resolved.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
