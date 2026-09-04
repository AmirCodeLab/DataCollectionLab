#!/usr/bin/env python3
"""Export a form's submissions to CSV or XLSX.

    python scripts/export_submissions.py household --out exports/
    python scripts/export_submissions.py household --format xlsx --shape wide
    python scripts/export_submissions.py household --format dta   # Stata
    python scripts/export_submissions.py household --format sav   # SPSS
    python scripts/export_submissions.py household --status approved --language sw

Nothing left this system in any format before item 5, which blocked every
customer. This is the first way out: it runs the same exporter the console will,
in the same process, against the database the server uses. A second code path
here would be a second answer about what a submission becomes, and the one a
customer got would be whichever they happened to use.

Two shapes, and the default is the one to analyse:

  **long** (default) — one file per repeat beside the parent file, each repeat
  row keyed by `submission_id` and the **stable** `instance_id`. Join on that.
  **wide** — one row per submission with repeats flattened into positional
  columns. It is what people expect and ask for, and a position is not an
  identity: Form IR §2.3 resolves it against the current ordered list, so
  `members_1_name` can be a different person in this file and the next one. The
  manifest says so on its face.

A CSV, .dta or .sav bundle carries `manifest.json`; an .xlsx carries a
`_manifest` sheet instead, because an .xlsx travels on its own and an export
that is partly unreadable and does not say so is worse than one that fails.

For `.dta` and `.sav` the manifest is not optional reading. Stata caps a
variable name at 32 characters, so some columns are stored under a shortened
name; and a column that holds an unreadable value is stored as **text** where it
would otherwise be numeric, because a numeric column cannot carry the
`ENCRYPTED` token and writing it as missing is the failure the token exists to
prevent. Both are printed below and both are in the manifest per column.

Exit 3 means an answer will not fit the format asked for — in practice a value
over SPSS's 32,767-byte maximum for a `.sav`. It is refused rather than
truncated, and the message names the formats that do hold it (a `.dta` stores
anything over 2,045 bytes as a Stata `strL`, so it always does).
"""

from __future__ import annotations

import argparse
import asyncio
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.modules.export.service import (  # noqa: E402
    DEFAULT_LIMIT,
    ExportTooLarge,
    export_form,
)
from app.modules.export.statistical import ValueTooLong  # noqa: E402
from app.modules.export.writers import Bundle  # noqa: E402


async def run(arguments: argparse.Namespace) -> Bundle | None:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            async with session.begin():
                return await export_form(
                    session,
                    form_key=arguments.form,
                    project_id=arguments.project,
                    environment_id=arguments.environment,
                    status=arguments.status,
                    language=arguments.language,
                    shape=arguments.shape,
                    fmt=arguments.format,
                    limit=arguments.limit,
                )
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export a form's submissions to CSV or XLSX."
    )
    parser.add_argument("form", help="the form key, as an op carries it")
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("exports"))
    parser.add_argument("--format", choices=("csv", "xlsx", "dta", "sav"), default="csv")
    parser.add_argument("--shape", choices=("long", "wide"), default="long")
    parser.add_argument("--language", help="label language; the form's default otherwise")
    parser.add_argument("--project", help="restrict to one project id")
    parser.add_argument("--environment", help="restrict to one environment id")
    parser.add_argument("--status", help="restrict to one submission status")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    arguments = parser.parse_args()

    try:
        bundle = asyncio.run(run(arguments))
    except ExportTooLarge as refused:
        print(f"ERROR  {refused}", file=sys.stderr)
        return 2
    except ValueTooLong as refused:
        # Refused, never truncated. Shortening an answer to fit a file format is
        # the silent data loss this whole exporter is built against.
        print(f"ERROR  {refused}", file=sys.stderr)
        return 3

    if bundle is None:
        print(f"ERROR  no form with key {arguments.form!r}", file=sys.stderr)
        return 1

    arguments.out.mkdir(parents=True, exist_ok=True)
    for name, content in bundle.files:
        (arguments.out / name).write_bytes(content)
        print(f"  wrote {arguments.out / name}  ({len(content):,} bytes)")

    manifest = bundle.manifest
    print(f"\n{manifest.submission_count} submission(s), {manifest.shape} shape")
    print(f"form versions: {', '.join(str(v) for v in manifest.form_versions)}")

    unreadable = [
        column
        for table in manifest.tables
        for column in table.columns
        if column.unreadable is not None
    ]
    if unreadable:
        # Said here as well as in the manifest, because a customer who does not
        # open the manifest is exactly the one who needs telling.
        print(f"\n{len(unreadable)} column(s) contain values this server cannot read:")
        for column in unreadable:
            keys = ", ".join(column.openable_by) or "NOBODY — wrapped to no key"
            print(f"  {column.column:24} {column.unreadable:24} openable by: {keys}")

    every = [column for table in manifest.tables for column in table.columns]
    renamed = [column for column in every if column.stored_as != column.column]
    if renamed:
        print(f"\n{len(renamed)} column(s) stored under a shortened name:")
        for column in renamed:
            print(f"  {column.column:38} -> {column.stored_as}")

    retyped = [column for column in every if column.storage_changed_because]
    if retyped:
        # The one an analyst has to know about: a do-file that summarizes this
        # column works against an export with nothing encrypted in it and does
        # nothing here, and the difference is not in the form.
        print(f"\n{len(retyped)} column(s) are stored as text but declared otherwise:")
        for column in retyped:
            print(
                f"  {column.stored_as:30} {column.declared_storage_type} -> "
                f"{column.storage_type}  ({column.storage_changed_because})"
            )

    if manifest.unmapped:
        print("\nvalues in storage that no version of this form has a field for:")
        for path, submissions in manifest.unmapped.items():
            print(f"  {path}  ({len(submissions)} submission(s))")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
