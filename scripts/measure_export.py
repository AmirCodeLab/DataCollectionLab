#!/usr/bin/env python3
"""What an export costs at real scale, across several form versions.

    python scripts/measure_export.py                      # 3000 submissions
    python scripts/measure_export.py --submissions 8000 --villages 37852
    python scripts/measure_export.py --keep                # leave the db behind

Meant to be run and published whatever it says, like
`scripts/measure_datasets_on_device.sh`. §3.2's numbers were only believable
because the first cut was reported at 1,589 ms.

**The shape measured is the one that actually happens**, which is not the big
one. A project six months in has v1, v2 and v3 of its form in the same export,
each pinned to its own dataset version (§3.2), so one run resolves codes
through three separate 38,000-row lists. That is strictly more work than one
version at scale and nothing had exercised it.

Reported per format, because the writers differ in kind and not only in degree:
CSV streams rows out, XLSX builds a workbook, and `.dta`/`.sav` build a pandas
frame and then **read the file back** to verify every column's type. Time and
peak memory are reported separately on purpose — streaming and caching are
different fixes, and knowing which number is the problem decides which one.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import gc
import pathlib
import random
import resource
import sys
import time
import tracemalloc
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

MEASURE_DB = "dcp_measure_export"
PROJECT_ID = "01PROJMEASURE"
ENVIRONMENT_ID = "01ENVMEASURE"
DEVICE_ID = "dev_measure"
USER_ID = "usr_measure"

#: Tanzania's actual shape, and the UCL form's own three cascading questions.
REGIONS = 26
DISTRICTS = 166

WALL_CLOCK = dt.datetime(2026, 9, 3, 9, 0, tzinfo=dt.UTC)

SWAHILI = ["Nyamburi", "Mtakuja", "Kijiji", "Mwanza", "Bagamoyo", "Ng'ombe",
           "Mkuranga", "Chalinze", "Songea", "Ilala", "Msasani", "Kigoma"]


def _url(database: str) -> str:
    from app.core.config import get_settings

    parts = urlsplit(get_settings().database_url)
    return urlunsplit(parts._replace(scheme="postgresql+asyncpg", path=f"/{database}"))


def _admin_dsn() -> str:
    from app.core.config import get_settings

    parts = urlsplit(get_settings().database_url)
    return urlunsplit(parts._replace(scheme="postgresql", path="/postgres"))


def _villages(count: int, generation: int) -> list[dict[str, Any]]:
    """One dataset version. `generation` renames a slice, as a real list does."""
    rng = random.Random(20260903 + generation)
    rows = []
    for index in range(count):
        name = f"{SWAHILI[index % len(SWAHILI)]} {rng.choice(['Kati', 'Mpya', 'Kaskazini', 'Juu'])}"
        if generation > 1 and index % 50 == 0:
            name = f"{name} (mpya {generation})"  # a rename between versions
        rows.append(
            {
                "code": f"V{index:06d}",
                "name": name,
                "district_id": f"D{index % DISTRICTS:04d}",
                "region_id": f"TZ{index % REGIONS:02d}",
                "population": str(rng.randint(200, 40000)),
                "ward": f"Kata {index % 900}",
                "notes": "",
                "unused_column": "x" * 20,
            }
        )
    return rows


def _regions() -> list[dict[str, Any]]:
    return [{"code": f"TZ{i:02d}", "name": f"Mkoa wa {SWAHILI[i % len(SWAHILI)]} {i}"}
            for i in range(REGIONS)]


def _districts() -> list[dict[str, Any]]:
    return [{"code": f"D{i:04d}", "name": f"Wilaya ya {SWAHILI[i % len(SWAHILI)]} {i}",
             "region_id": f"TZ{i % REGIONS:02d}"} for i in range(DISTRICTS)]


def _form_ir(version: int) -> dict[str, Any]:
    """v1 -> v2 adds a question, v2 -> v3 adds another. The realistic drift."""
    def dataset_select(field: str, key: str, value: str) -> dict[str, Any]:
        return {
            "type": "question", "id": field, "dataType": "select_one",
            "label": {"en": field.replace("_", " ").title()},
            "choices": {"kind": "dataset", "dataset": key,
                        "valueColumn": value, "labelColumn": {"en": "name"}},
        }

    children: list[dict[str, Any]] = [
        dataset_select("region_id", "regions", "code"),
        dataset_select("district_id", "districts", "code"),
        dataset_select("village", "villages", "code"),
        {"type": "question", "id": "plot_area", "dataType": "decimal",
         "label": {"en": "Plot area"}},
        {"type": "question", "id": "surveyed_on", "dataType": "date",
         "label": {"en": "Surveyed on"}},
        {"type": "question", "id": "remarks", "dataType": "text",
         "label": {"en": "Remarks"}},
        {"type": "repeat", "id": "stems", "label": {"en": "Stems"}, "children": [
            {"type": "question", "id": "circumference", "dataType": "decimal",
             "label": {"en": "Circumference"}},
            {"type": "question", "id": "species", "dataType": "text",
             "label": {"en": "Species"}},
        ]},
    ]
    if version >= 2:
        children.append({"type": "question", "id": "canopy_cover", "dataType": "integer",
                         "label": {"en": "Canopy cover"}})
    if version >= 3:
        children.append({"type": "question", "id": "soil_type", "dataType": "select_one",
                         "label": {"en": "Soil type"},
                         "choices": {"kind": "inline", "items": [
                             {"value": "clay", "label": {"en": "Clay"}},
                             {"value": "loam", "label": {"en": "Loam"}}]}})
    return {"irVersion": "0.1", "formId": "biomass", "version": version,
            "title": {"en": "Biomass plot"}, "defaultLanguage": "en",
            "languages": ["en"], "children": children}


async def seed(url: str, *, submissions: int, villages: int, versions: int) -> None:
    from sqlalchemy import text as sql
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.ulid import new_ulid
    from app.modules.entities import service as entities
    from app.modules.forms import service as forms
    from app.modules.forms.schemas import DatasetPin
    from app.modules.projects.models import Device, Environment, Project
    from app.modules.submissions.models import Submission, SubmissionOp

    engine = create_async_engine(url)
    version_ids: dict[int, str] = {}
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            async with session.begin():
                session.add(Project(id=PROJECT_ID, name="Measure", slug="measure"))
                await session.flush()
                session.add(Environment(id=ENVIRONMENT_ID, project_id=PROJECT_ID,
                                        kind="production"))
                session.add(Device(id=DEVICE_ID, project_id=PROJECT_ID,
                                   user_id=USER_ID, platform="android"))

            # One dataset version per form version — the whole point of the run.
            for generation in range(1, versions + 1):
                started = time.perf_counter()
                async with session.begin():
                    pins = []
                    for key, rows in (("regions", _regions()),
                                      ("districts", _districts()),
                                      ("villages", _villages(villages, generation))):
                        published = await entities.publish_dataset_version(
                            session, project_id=PROJECT_ID, dataset_key=key,
                            rows=rows, key_column="code")
                        pins.append(DatasetPin(key=key,
                                               dataset_version_id=published.dataset_version_id))
                    await session.flush()
                    form = await forms.publish_version(
                        session, project_id=PROJECT_ID, ir=_form_ir(generation),
                        datasets=pins)
                    version_ids[generation] = form.id
                print(f"  seeded form v{generation} + 3 dataset versions "
                      f"({villages:,} villages) in {time.perf_counter() - started:.1f}s")

            # Submissions spread across the versions, oldest getting the most —
            # a project accumulates history under versions it has moved on from.
            weights = [3, 2, 1][:versions]
            spread: list[int] = []
            for generation, weight in zip(range(1, versions + 1), weights, strict=True):
                spread += [generation] * weight
            rng = random.Random(7)
            started = time.perf_counter()
            counter = 0
            for batch_start in range(0, submissions, 500):
                async with session.begin():
                    for index in range(batch_start, min(batch_start + 500, submissions)):
                        generation = spread[index % len(spread)]
                        submission_id = f"sub_{index:06d}"
                        session.add(Submission(
                            id=submission_id, project_id=PROJECT_ID,
                            environment_id=ENVIRONMENT_ID,
                            form_version_id=version_ids[generation],
                            origin_device_id=DEVICE_ID, created_by=USER_ID,
                            status="finalized"))
                        village = rng.randrange(villages)
                        answers: list[tuple[str, Any]] = [
                            ("region_id", f"TZ{village % REGIONS:02d}"),
                            ("district_id", f"D{village % DISTRICTS:04d}"),
                            ("village", f"V{village:06d}"),
                            ("plot_area", round(rng.uniform(0.1, 9.9), 3)),
                            ("surveyed_on", f"2026-0{rng.randint(1, 9)}-1{rng.randint(0, 9)}"),
                            ("remarks", "Alifika mapema; mvua kidogo."),
                        ]
                        if generation >= 2:
                            answers.append(("canopy_cover", rng.randint(0, 100)))
                        if generation >= 3:
                            answers.append(("soil_type", rng.choice(["clay", "loam"])))
                        for stem in range(3):
                            answers.append((f"stems[i{stem + 1}].circumference",
                                            round(rng.uniform(10, 200), 1)))
                            answers.append((f"stems[i{stem + 1}].species", "Brachystegia"))
                        for path, value in answers:
                            counter += 1
                            session.add(SubmissionOp(
                                id=new_ulid(), submission_id=submission_id,
                                op_kind="set", path=path, value=value,
                                device_id=DEVICE_ID, counter=counter,
                                wall_clock=WALL_CLOCK))
                        counter += 1
                        session.add(SubmissionOp(
                            id=new_ulid(), submission_id=submission_id,
                            op_kind="finalize", device_id=DEVICE_ID, counter=counter,
                            wall_clock=WALL_CLOCK))
            print(f"  seeded {submissions:,} submissions ({counter:,} ops) "
                  f"in {time.perf_counter() - started:.1f}s")
            async with session.begin():
                await session.execute(sql("ANALYZE"))
    finally:
        await engine.dispose()


async def measure(url: str, fmt: str, shape: str, limit: int) -> dict[str, Any]:
    # The question that decides seconds versus hours: is a code resolved to a
    # name once per dataset VERSION, or once per cell? Counted rather than read
    # off the source, because the source is what you would be checking.
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import app.modules.export.service as export_service
    import app.modules.export.shape as shape_module
    from app.modules.export.service import export_form
    from app.modules.export.shape import Shape
    from app.modules.export.writers import Format

    tally = {"row_fetches": 0, "rows_materialised": 0, "label_lookups": 0}
    real_rows = export_service.dataset_rows_for_submissions  # type: ignore[attr-defined]
    real_label = shape_module._label

    async def counting_rows(session_: Any, ids: Any, key: str) -> Any:
        found = await real_rows(session_, ids, key)
        tally["row_fetches"] += 1
        seen: set[int] = set()
        for rows in found.values():
            if id(rows) not in seen:      # the same list is shared, not copied
                seen.add(id(rows))
                tally["rows_materialised"] += len(rows)
        return found

    def counting_label(*args: Any, **kwargs: Any) -> Any:
        tally["label_lookups"] += 1
        return real_label(*args, **kwargs)

    # Patched on the module that CALLS it, which is the only place a patch
    # takes effect — and reached with setattr because it is an import there,
    # not part of that module's own surface.
    export_service.dataset_rows_for_submissions = counting_rows  # type: ignore[attr-defined,assignment]
    shape_module._label = counting_label

    gc.collect()
    engine = create_async_engine(url)
    before_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    tracemalloc.start()
    started = time.perf_counter()
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session, session.begin():
            bundle = await export_form(
                session,
                form_key="biomass",
                shape=cast(Shape, shape),
                fmt=cast(Format, fmt),
                limit=limit,
            )
        elapsed = time.perf_counter() - started
        assert bundle is not None
        archive = bundle.to_zip()
        total = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        await engine.dispose()
        export_service.dataset_rows_for_submissions = real_rows  # type: ignore[attr-defined]
        shape_module._label = real_label

    # `tracemalloc` sees Python allocations only, which is most of the CSV and
    # XLSX cost and *not* the numpy arrays a .dta or .sav builds. `ru_maxrss` is
    # the process high-water mark: it never falls, so it is only meaningful for
    # the first format in a process — run one format per invocation when the RSS
    # of a specific writer is the question.
    after_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    scale = 1 if sys.platform == "darwin" else 1024  # ru_maxrss: bytes on macOS
    return {
        "format": fmt, "shape": shape,
        "build_s": elapsed, "total_s": total,
        "peak_mb": peak / 1e6,
        "rss_mb": after_rss * scale / 1e6,
        "rss_delta_mb": max(after_rss - before_rss, 0) * scale / 1e6,
        "zip_mb": len(archive) / 1e6,
        "files": {name: len(data) for name, data in bundle.files},
        "rows": sum(len(t.rows) for t in bundle.tables),
        "versions": bundle.manifest.form_versions,
        "columns": sum(len(t.columns) for t in bundle.tables),
        **tally,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submissions", type=int, default=3000)
    parser.add_argument("--villages", type=int, default=37852)
    parser.add_argument("--versions", type=int, default=3)
    parser.add_argument("--formats", default="csv,xlsx,dta,sav")
    parser.add_argument("--shape", default="long")
    # Deliberately settable: DEFAULT_LIMIT is a number somebody picked, and
    # this script is how it stops being a guess.
    parser.add_argument("--limit", type=int, default=100_000)
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--reuse", action="store_true", help="skip seeding")
    arguments = parser.parse_args()

    import asyncpg
    from alembic import command
    from alembic.config import Config

    url = _url(MEASURE_DB)

    async def prepare() -> None:
        conn = await asyncpg.connect(_admin_dsn(), timeout=5)
        try:
            await conn.execute(f"DROP DATABASE IF EXISTS {MEASURE_DB} WITH (FORCE)")
            await conn.execute(f"CREATE DATABASE {MEASURE_DB}")
        finally:
            await conn.close()

    if not arguments.reuse:
        asyncio.run(prepare())
        cfg = Config(str(REPO_ROOT / "backend" / "alembic.ini"))
        cfg.set_main_option("script_location", str(REPO_ROOT / "backend" / "migrations"))
        cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(cfg, "head")
        print(f"seeding {arguments.versions} form versions, "
              f"{arguments.villages:,} villages each")
        asyncio.run(seed(url, submissions=arguments.submissions,
                         villages=arguments.villages, versions=arguments.versions))

    print()
    print(f"{'format':>7} {'shape':>5} {'build s':>9} {'+zip s':>8} "
          f"{'py MB':>8} {'rss MB':>8} {'zip MB':>8} {'rows':>8}")
    results = []
    for fmt in arguments.formats.split(","):
        found = asyncio.run(measure(url, fmt, arguments.shape, arguments.limit))
        results.append(found)
        print(f"{found['format']:>7} {found['shape']:>5} {found['build_s']:>9.2f} "
              f"{found['total_s'] - found['build_s']:>8.2f} {found['peak_mb']:>8.1f} "
              f"{found['rss_mb']:>8.0f} {found['zip_mb']:>8.2f} {found['rows']:>8,}")

    print()
    for found in results:
        print(f"  {found['format']}: " + ", ".join(
            f"{name} {size / 1e6:.2f} MB" for name, size in found["files"].items()))
    print()
    first = results[0]
    print(f"  form versions in the export: {first['versions']}")
    print(f"  columns across all tables:   {first['columns']}")
    print()
    print("  label resolution")
    print(f"    dataset row fetches:      {first['row_fetches']:>12,}"
          "   (one per dataset key, not per submission)")
    print(f"    rows materialised:        {first['rows_materialised']:>12,}")
    print(f"    per-cell label lookups:   {first['label_lookups']:>12,}"
          "   (each an O(1) dict hit)")
    if first["label_lookups"]:
        ratio = first["rows_materialised"] / first["label_lookups"]
        print(f"    rows read per lookup:     {ratio:>12.2f}"
              "   (>>1 means cached; ~1 would mean a scan per cell)")

    if not arguments.keep:
        async def drop() -> None:
            conn = await asyncpg.connect(_admin_dsn(), timeout=5)
            try:
                await conn.execute(f"DROP DATABASE IF EXISTS {MEASURE_DB} WITH (FORCE)")
            finally:
                await conn.close()
        asyncio.run(drop())
    else:
        print(f"\n  database kept: {MEASURE_DB} (re-run with --reuse)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
