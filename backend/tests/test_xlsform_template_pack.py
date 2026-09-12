"""The pack we send a partner says what this platform actually does.

`docs/xlsform-template/` is the one artefact in this repository whose audience
is somebody outside it, and it is the one that went stale without anything going
red. `dcp-xlsform-roster-example.xlsx` was written while rosters were refused;
the refusal lifted on 5 September 2026, `docs/xlsform-template.md` §5 was
rewritten to say rosters work, and the **workbook** still announced in its own
first row that "This form is REFUSED by the importer today" and carried the
title "(not importable yet)". The importer reported 0 errors and 0 warnings on
it the whole time.

Nothing could have caught that, because the claim lived in a binary nobody
diffs. So the workbooks are generated now — `scripts/generate_xlsform_template.py`
— and these tests are what make that worth doing:

- the committed workbooks are what the generator produces, **compared cell by
  cell** rather than byte by byte, because a .xlsx is a zip and its bytes move
  for reasons that are not content;
- both import with **0 errors and 0 warnings**, which is the sentence the doc
  makes to a partner in §1;
- the template really does contain every collectable type, so "the workbook is
  the reference for the exact spelling" is true rather than aspirational;
- and the field-list group really does become one screen, because that claim is
  the newest one in the pack and the one a partner will write an emitter
  against.
"""

from __future__ import annotations

import io
import pathlib
import sys
from typing import Any

import openpyxl
import pytest

from app.modules.form_engine.screens import build_screen_plan
from app.modules.forms.xlsform import datatypes
from app.modules.forms.xlsform.importer import import_workbook

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PACK = REPO_ROOT / "docs" / "xlsform-template"
TEMPLATE = PACK / "dcp-xlsform-template.xlsx"
ROSTER = PACK / "dcp-xlsform-roster-example.xlsx"

sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _cells(data: bytes) -> dict[str, list[tuple[Any, ...]]]:
    book = openpyxl.load_workbook(io.BytesIO(data), read_only=True)
    return {
        sheet.title: [tuple("" if c is None else c for c in row) for row in sheet.values]
        for sheet in book.worksheets
    }


def _companions() -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(PACK.glob("*.csv"))}


def _regenerated(tmp_path: pathlib.Path) -> pathlib.Path:
    import generate_xlsform_template

    argv = sys.argv
    sys.argv = ["generate_xlsform_template.py", "--out", str(tmp_path)]
    try:
        assert generate_xlsform_template.main() == 0
    finally:
        sys.argv = argv
    return tmp_path


@pytest.mark.parametrize("name", ["dcp-xlsform-template.xlsx", "dcp-xlsform-roster-example.xlsx"])
def test_the_committed_workbook_is_what_the_generator_produces(
    name: str, tmp_path: pathlib.Path
) -> None:
    """A hand-edit to the binary fails here, which is the whole point.

    Cell by cell, not byte by byte: openpyxl writes a zip, and a zip's bytes
    depend on the moment it was written. A byte comparison would fail on every
    machine and be switched off within a week, which is the failure mode
    `docs/project-conventions.md` calls a gate that goes red at random.
    """
    generated = _regenerated(tmp_path) / name
    assert _cells((PACK / name).read_bytes()) == _cells(generated.read_bytes()), (
        f"{name} differs from scripts/generate_xlsform_template.py. Regenerate it "
        "rather than editing the workbook: the last hand-edit is why this test exists."
    )


def test_districts_csv_is_what_the_generator_produces(tmp_path: pathlib.Path) -> None:
    generated = _regenerated(tmp_path) / "districts.csv"
    assert (PACK / "districts.csv").read_text() == generated.read_text()


@pytest.mark.parametrize("path", [TEMPLATE, ROSTER], ids=lambda p: p.name)
def test_the_pack_imports_with_no_errors_and_no_warnings(path: pathlib.Path) -> None:
    """§1 of the doc promises exactly this, in bold, to somebody outside."""
    result = import_workbook(path.read_bytes(), companions=_companions())
    loud = [d for d in result.diagnostics if d.severity in ("error", "warning")]
    assert loud == [], [f"{d.severity}: {d.message}" for d in loud]
    assert result.publishable


def test_the_template_uses_every_type_a_client_can_collect() -> None:
    """"The template uses every one of them, so the workbook is the reference
    for the exact spelling" — §2. That sentence is only true while it is.

    It fails in both directions on purpose. A type entering the registry with no
    row in the template makes the template incomplete; a type in the template
    that has left the registry makes it wrong.
    """
    result = import_workbook(TEMPLATE.read_bytes(), companions=_companions())

    used = set()

    def walk(nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            if node.get("type") == "question" and node.get("calculate") is None:
                data_type = node.get("dataType")
                if isinstance(data_type, str):
                    used.add(data_type)
            walk(node.get("children", []))

    walk(result.form.get("children", []))
    assert used == set(datatypes.collectable_types()), {
        "missing from the template": sorted(set(datatypes.collectable_types()) - used),
        "in the template and not collectable": sorted(used - set(datatypes.collectable_types())),
    }


def test_the_field_list_group_really_is_one_screen() -> None:
    """The newest claim in the pack, and the one an emitter is written against.

    Until 12 September 2026 the importer discarded `appearance`, so this
    workbook would have produced three screens while the documentation beside it
    said one.
    """
    result = import_workbook(TEMPLATE.read_bytes(), companions=_companions())
    plan = build_screen_plan(result.form)
    shared = [s for s in plan.screens if s.group_id == "screening"]
    assert len(shared) == 1
    assert shared[0].question_ids == ("consent", "visit_number", "listed_head_name")


def test_the_roster_is_one_screen_with_an_instance_plan_behind_it() -> None:
    """§11.3, and §5 of the doc: one screen in the count whatever it holds."""
    result = import_workbook(ROSTER.read_bytes(), companions=_companions())
    plan = build_screen_plan(result.form)
    assert [s.kind for s in plan.screens].count("repeat") == 1
    assert len(plan.instance_plans["members"]) == 4
