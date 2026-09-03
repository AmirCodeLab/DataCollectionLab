"""Export, held to two invariants rather than to a list of cases.

docs/project-conventions.md item 5 names two mistakes that pass every test somebody would think
to write, and both are shaped the same way: the file is the right size, the
columns are the right names, the types are all correct, and the numbers are
wrong. A suite of "does this column come out right" cannot see either. So the
suite is built around two properties instead:

  **Round trip.** Export, read the files back, compare against the projection
  the submission produced. `cells.canonical_value` is the right-hand side — it
  says what a value becomes after a trip through a format with no types — so
  the comparison fails on defects and not on CSV having one empty cell.

  **Cross-form agreement.** Every long-form row's parent exists exactly once in
  the wide export, and the multiset of (submission, instance) pairs matches the
  op log's. A flattening error breaks this. A wrong column does not.

The cases below the invariants are the two specific mistakes item 5 predicts —
a non-relevant field's retained value reaching the file, and a repeat keyed on
position — plus the encryption rules, because a blank where an unreadable value
should be is the third failure with no symptom.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest

from app.modules.export.cells import ENCRYPTED, canonical_value
from app.modules.export.manifest import WIDE_POSITION_NOTE, build_manifest
from app.modules.export.plan import build_plan
from app.modules.export.readback import NotRoundTrippable, read_bundle
from app.modules.export.shape import SubmissionRecord, build_tables
from app.modules.export.writers import Format, write_bundle
from app.modules.form_engine.projection import project_for_export
from app.modules.form_engine.runtime import CompiledForm
from app.modules.submissions.fold import fold_ops

# --- the form ------------------------------------------------------------


def _lit(value: Any) -> dict[str, Any]:
    return {"op": "lit", "value": value}


def _ref(path: str) -> dict[str, Any]:
    return {"op": "ref", "path": path}


YES_NO = {
    "kind": "inline",
    "items": [
        {"value": "yes", "label": {"en": "Yes", "sw": "Ndiyo"}},
        {"value": "no", "label": {"en": "No", "sw": "Hapana"}},
    ],
}


def household_ir(version: int = 1, *, extra: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """A form with everything the export has to get right, and nothing else.

    A repeat, a question gated on an earlier answer, an aggregate over the
    repeat, a coded answer that needs a name beside it, and a structured value.
    """
    return {
        "irVersion": "0.1",
        "formId": "household",
        "version": version,
        "title": {"en": "Household survey"},
        "defaultLanguage": "en",
        "languages": ["en", "sw"],
        "children": [
            {
                "type": "question",
                "id": "consent",
                "dataType": "select_one",
                "label": {"en": "Consent given", "sw": "Ridhaa"},
                "choices": YES_NO,
            },
            {
                "type": "question",
                "id": "children",
                "dataType": "integer",
                "label": {"en": "Children in the household"},
                "relevant": {"op": "eq", "args": [_ref("consent"), _lit("yes")]},
            },
            {
                "type": "repeat",
                "id": "members",
                "label": {"en": "Household members"},
                "children": [
                    {
                        "type": "question",
                        "id": "name",
                        "dataType": "text",
                        "label": {"en": "Name"},
                    },
                    {
                        "type": "question",
                        "id": "income",
                        "dataType": "decimal",
                        "label": {"en": "Monthly income"},
                        "sensitive": True,
                    },
                ],
            },
            {
                "type": "question",
                "id": "total_income",
                "dataType": "decimal",
                "label": {"en": "Total income"},
                "calculate": {
                    "op": "call",
                    "fn": "sum",
                    "args": [_ref("members[].income")],
                },
            },
            {
                "type": "question",
                "id": "dwelling",
                "dataType": "geopoint",
                "label": {"en": "Dwelling location"},
            },
            *(extra or []),
        ],
    }


# --- a synthetic op log --------------------------------------------------


@dataclass
class Op:
    """The columns a fold reads. The ORM row is the other implementation."""

    op_kind: str
    path: str | None = None
    value: Any = None
    value_ciphertext: bytes | None = None
    content_key_id: str | None = None
    wall_clock: datetime = datetime(2026, 9, 3, 9, 0, tzinfo=UTC)
    server_seq: int = 0


def _sequenced(ops: list[Op]) -> list[Op]:
    for index, op in enumerate(ops, start=1):
        op.server_seq = index
    return ops


def set_op(path: str, value: Any) -> Op:
    return Op("set", path=path, value=value)


def secret_op(path: str, content_key_id: str = "ck_1") -> Op:
    return Op(
        "set", path=path, value_ciphertext=b"\x00" * 24, content_key_id=content_key_id
    )


def record(
    submission_id: str,
    ops: list[Op],
    *,
    form: CompiledForm,
    labels: dict[str, dict[str, str]] | None = None,
    status: str = "finalized",
) -> SubmissionRecord:
    fold = fold_ops(_sequenced(ops))
    return SubmissionRecord(
        submission_id=submission_id,
        form_key=form.form_id,
        form_version=form.version,
        status=status,
        device_id="dev_1",
        created_by="usr_1",
        started_at=datetime(2026, 9, 3, 8, 0, tzinfo=UTC),
        finalized_at=datetime(2026, 9, 3, 9, 0, tzinfo=UTC),
        received_at=datetime(2026, 9, 3, 9, 5, tzinfo=UTC),
        projection=project_for_export(
            form,
            stored=fold.data,
            instances=fold.instances,
            unreadable=fold.unreadable.keys(),
        ),
        labels=labels or {"consent": {"yes": "Yes", "no": "No"}},
    )


def bundle_of(
    records: list[SubmissionRecord],
    forms: list[CompiledForm],
    *,
    shape: str = "long",
    fmt: Format = "csv",
    ciphertext_fields: dict[str, tuple[str, ...]] | None = None,
) -> Any:
    plan = build_plan(forms)
    tables = build_tables(plan, records, shape=shape, base_name="household")  # type: ignore[arg-type]
    manifest = build_manifest(
        plan,
        tables,
        records,
        form_id="household",
        form_title="Household survey",
        language="en",
        shape=shape,  # type: ignore[arg-type]
        ciphertext_fields=ciphertext_fields or {},
    )
    return write_bundle(tables, manifest, fmt=fmt)


@pytest.fixture
def form() -> CompiledForm:
    return CompiledForm(household_ir())


@pytest.fixture
def three_households(form: CompiledForm) -> list[SubmissionRecord]:
    """Three submissions: a full one, a refusal, and one with a deleted member."""
    return [
        record(
            "sub_full",
            [
                set_op("consent", "yes"),
                set_op("children", 3),
                Op("repeat_add", path="members[a1]"),
                set_op("members[a1].name", "Ada"),
                set_op("members[a1].income", 100),
                Op("repeat_add", path="members[b2]"),
                set_op("members[b2].name", "Ben, the elder"),
                set_op("members[b2].income", 250.5),
                set_op("dwelling", {"lat": -3.3869, "lon": 36.6829, "accuracy": 4.5}),
                Op("finalize"),
            ],
            form=form,
        ),
        record(
            "sub_refused",
            [
                # The enumerator typed a number, then the respondent refused.
                # §4.4 keeps that 3 in storage; export must not contain it.
                set_op("children", 3),
                set_op("consent", "no"),
                Op("finalize"),
            ],
            form=form,
        ),
        record(
            "sub_deleted",
            [
                set_op("consent", "yes"),
                Op("repeat_add", path="members[c3]"),
                set_op("members[c3].name", "Cara"),
                set_op("members[c3].income", 10),
                Op("repeat_add", path="members[d4]"),
                set_op("members[d4].name", "Dan"),
                set_op("members[d4].income", 20),
                # Cara was entered by mistake. Deleting her does not renumber
                # Dan in storage (§2.3), and must not renumber him here.
                Op("repeat_delete", path="members[c3]"),
                Op("finalize"),
            ],
            form=form,
        ),
    ]


# --- invariant 1: round trip ---------------------------------------------


@pytest.mark.parametrize("fmt", ["csv", "xlsx"])
def test_a_long_export_reads_back_as_the_submissions_it_came_from(
    three_households: list[SubmissionRecord], form: CompiledForm, fmt: Format
) -> None:
    """Export, re-import, compare — for every value, in both formats.

    The comparison is against `canonical_value`, which is the export's own
    statement of what a table can hold. Comparing against the raw value would
    fail on a CSV having one empty cell; comparing against whatever the reader
    produced would prove nothing at all.
    """
    read = read_bundle(bundle_of(three_households, [form], fmt=fmt))

    assert set(read) == {r.submission_id for r in three_households}
    for source in three_households:
        back = read[source.submission_id]
        assert back.form_version == source.form_version

        for field_id, value in source.projection.top.items():
            data_type = form.fields[field_id].data_type
            if data_type == "note":
                continue
            assert back.top.get(field_id) == canonical_value(value, data_type), (
                f"{source.submission_id}.{field_id} did not survive the round trip"
            )

        for repeat_id, rows in source.projection.repeats.items():
            instances = back.repeats.get(repeat_id, ())
            assert [i.instance_id for i in instances] == [r.instance_id for r in rows]
            for original, restored in zip(rows, instances, strict=True):
                for field_id, value in original.cells.items():
                    assert restored.cells.get(field_id) == canonical_value(
                        value, form.fields[field_id].data_type
                    )


def test_a_wide_export_says_it_cannot_be_read_back(
    three_households: list[SubmissionRecord], form: CompiledForm
) -> None:
    """The wide shape has no instance ids in it, and does not pretend otherwise.

    Inventing ids for positional rows would let the round trip pass over a file
    that has genuinely lost which member is which — which is the whole reason
    the manifest tells a reader to join on the long shape.
    """
    wide = bundle_of(three_households, [form], shape="wide")
    with pytest.raises(NotRoundTrippable):
        read_bundle(wide)
    assert WIDE_POSITION_NOTE in wide.manifest.notes


# --- invariant 2: cross-form agreement -----------------------------------


def test_every_long_row_has_exactly_one_parent_and_the_op_log_agrees(
    three_households: list[SubmissionRecord], form: CompiledForm
) -> None:
    """The invariant a flattening error breaks and a wrong column does not.

    Two halves. The first joins the shapes: a repeat row whose parent is absent
    from the wide export, or present twice, is a row filed under the wrong
    household — and every column in it would still be correct. The second
    anchors both to the op log, which is the only thing here that is not
    derived from the exporter.
    """
    long_bundle = bundle_of(three_households, [form], shape="long")
    wide_bundle = bundle_of(three_households, [form], shape="wide")

    wide_table = wide_bundle.tables[0]
    wide_at = [c.name for c in wide_table.columns].index("submission_id")
    parents = Counter(row[wide_at] for row in wide_table.rows)
    assert all(count == 1 for count in parents.values()), parents

    pairs: Counter[tuple[str, str]] = Counter()
    for table in long_bundle.tables:
        if table.kind != "repeat":
            continue
        names = [c.name for c in table.columns]
        submission_at, instance_at = (
            names.index("submission_id"),
            names.index("instance_id"),
        )
        for row in table.rows:
            submission_id = str(row[submission_at])
            assert parents[submission_id] == 1, (
                f"repeat row for {submission_id} has {parents[submission_id]} "
                "parent rows in the wide export"
            )
            pairs[(submission_id, str(row[instance_at]))] += 1

    assert pairs == _op_log_pairs(three_households)


def _op_log_pairs(records: list[SubmissionRecord]) -> Counter[tuple[str, str]]:
    """(submission, instance) straight off the projections, counted naively.

    Deliberately a second, plainer reading than the shaper's: it walks the
    projections rather than the tables, so an error in `build_tables` cannot
    hide in both.
    """
    found: Counter[tuple[str, str]] = Counter()
    for record_ in records:
        for rows in record_.projection.repeats.values():
            for row in rows:
                found[(record_.submission_id, row.instance_id)] += 1
    return found


# --- the two mistakes item 5 predicts ------------------------------------


def test_a_non_relevant_answer_is_retained_in_storage_and_absent_from_the_export(
    three_households: list[SubmissionRecord], form: CompiledForm
) -> None:
    """The default mistake, and the one item 5 says it would bet on.

    `sub_refused` typed 3 children and then answered "no" to consent. §4.4 says
    that 3 is **kept** — an enumerator correcting an earlier answer must not
    lose what they typed — and that export **excludes** it. An exporter reading
    `FormInstance.values` instead of `answers()` writes a household that said
    "no children" reporting the three it had typed before changing its mind, and
    every count, every type and every test still passes.
    """
    fold = fold_ops(
        _sequenced([set_op("children", 3), set_op("consent", "no")])
    )
    assert fold.data["children"] == 3, "storage must still hold the retained answer"

    refused = next(r for r in three_households if r.submission_id == "sub_refused")
    assert "children" not in refused.projection.top

    table = bundle_of(three_households, [form]).tables[0]
    at = {c.name: i for i, c in enumerate(table.columns)}
    row = next(r for r in table.rows if r[at["submission_id"]] == "sub_refused")
    assert row[at["children"]] is None


def test_a_repeat_row_is_keyed_on_the_stable_id_and_not_on_its_position(
    three_households: list[SubmissionRecord], form: CompiledForm
) -> None:
    """Deleting a member must not make the survivor somebody else.

    `sub_deleted` entered Cara (`c3`) and Dan (`d4`) and then deleted Cara.
    Dan's key is still `d4`. Keyed on position he would become instance 1 — the
    slot Cara had — so yesterday's export and today's disagree about who is who
    and a join between them is silently wrong with nothing to see.
    """
    table = next(
        t for t in bundle_of(three_households, [form]).tables if t.kind == "repeat"
    )
    names = [c.name for c in table.columns]
    rows = [
        dict(zip(names, row, strict=True))
        for row in table.rows
        if row[names.index("submission_id")] == "sub_deleted"
    ]

    assert [r["instance_id"] for r in rows] == ["d4"]
    assert [r["name"] for r in rows] == ["Dan"]
    # The position moved and the identity did not. Both are in the file, and
    # only one of them is a key.
    assert rows[0]["instance_index"] == 0


# --- what cannot be read, and what says so -------------------------------


def test_an_unreadable_value_is_a_token_and_never_a_blank() -> None:
    """`ENCRYPTED`, not empty, not `NA`, not `NULL`.

    Every statistical tool treats those three as missing and computes a mean
    over the rows that happen to be readable, without saying so. A token is a
    value no analysis can mistake for an absence — and here it also has to
    reach `total_income`, which is *computed* from three encrypted incomes and
    would otherwise export as a perfectly plausible 0.
    """
    form = CompiledForm(household_ir())
    encrypted = record(
        "sub_secret",
        [
            set_op("consent", "yes"),
            Op("repeat_add", path="members[a1]"),
            set_op("members[a1].name", "Ada"),
            secret_op("members[a1].income"),
            Op("finalize"),
        ],
        form=form,
    )

    bundle = bundle_of(
        [encrypted], [form], ciphertext_fields={"income": ("pk_alpha", "pk_beta")}
    )
    parent = bundle.tables[0]
    at = {c.name: i for i, c in enumerate(parent.columns)}
    assert parent.rows[0][at["total_income"]] == ENCRYPTED

    repeat = next(t for t in bundle.tables if t.kind == "repeat")
    repeat_at = {c.name: i for i, c in enumerate(repeat.columns)}
    assert repeat.rows[0][repeat_at["income"]] == ENCRYPTED
    assert repeat.rows[0][repeat_at["name"]] == "Ada"

    described = {
        column.column: column
        for table in bundle.manifest.tables
        for column in table.columns
    }
    assert described["income"].unreadable == "encrypted"
    assert described["income"].openable_by == ("pk_alpha", "pk_beta")
    # The distinction that matters when somebody asks why a total is a word:
    # nobody encrypted `total_income`, it was computed from something that was.
    assert described["total_income"].unreadable == "computed_from_encrypted"


def test_a_question_gated_on_an_unreadable_answer_is_kept_and_flagged() -> None:
    """Null coerces to true at the relevance boundary (§4.4), so the column stays.

    That is the safe direction — dropping it would delete answers on the
    strength of a value nobody here can read — but "kept" is then a guess, and
    the manifest says so instead of the file implying a certainty it has not got.
    """
    form = CompiledForm(household_ir())
    hidden = record(
        "sub_gated",
        [secret_op("consent"), set_op("children", 3), Op("finalize")],
        form=form,
    )
    assert hidden.projection.top["children"] == 3
    assert "children" in hidden.projection.relevance_uncertain

    bundle = bundle_of([hidden], [form], ciphertext_fields={"consent": ("pk_alpha",)})
    described = {
        column.column: column
        for table in bundle.manifest.tables
        for column in table.columns
    }
    assert described["children"].relevance_uncertain
    assert described["children"].unreadable is None


# --- versions, columns and names -----------------------------------------


def test_columns_are_the_union_of_every_version_and_each_says_which() -> None:
    """A field added in v2 does not erase v1's submissions, or pretend to be old."""
    v1 = CompiledForm(household_ir(1))
    v2 = CompiledForm(
        household_ir(
            2,
            extra=[
                {
                    "type": "question",
                    "id": "water_source",
                    "dataType": "text",
                    "label": {"en": "Water source"},
                }
            ],
        )
    )
    plan = build_plan([v2, v1])  # deliberately out of order
    columns = {column.name: column for column in plan.parent}

    assert plan.versions == (1, 2)
    assert columns["water_source"].versions == (2,)
    assert columns["consent"].versions == (1, 2)
    # Document order, oldest version first, later additions appended.
    names = [c.name for c in plan.parent if c.source == "field"]
    assert names.index("consent") < names.index("water_source")


def test_a_field_named_like_a_metadata_column_keeps_its_name() -> None:
    """The form author's identifier wins; ours is the one that moves.

    Analysis code is written against the column the form named. Refusing to
    export over a name collision would block a customer; renaming their column
    would break their scripts silently the next time they export.
    """
    form = CompiledForm(
        household_ir(
            1,
            extra=[
                {
                    "type": "question",
                    "id": "submission_status",
                    "dataType": "text",
                    "label": {"en": "Status of the dwelling"},
                }
            ],
        )
    )
    plan = build_plan([form])
    by_name = {column.name: column for column in plan.parent}

    assert by_name["submission_status"].source == "field"
    assert "submission_status_2" in by_name
    assert by_name["submission_status_2"].source == "meta"


def test_a_coded_answer_exports_the_code_and_the_name_beside_it() -> None:
    """`V000023` with no name in it is not something anybody can analyse."""
    form = CompiledForm(household_ir())
    one = record(
        "sub_named",
        [set_op("consent", "yes"), Op("finalize")],
        form=form,
        labels={"consent": {"yes": "Ndiyo", "no": "Hapana"}},
    )
    table = bundle_of([one], [form]).tables[0]
    at = {c.name: i for i, c in enumerate(table.columns)}

    assert table.rows[0][at["consent"]] == "yes"
    assert table.rows[0][at["consent_label"]] == "Ndiyo"


def test_a_structured_value_becomes_one_column_per_component(
    three_households: list[SubmissionRecord], form: CompiledForm
) -> None:
    """A `lat lon alt acc` string is something every analyst has to split first."""
    table = bundle_of(three_households, [form]).tables[0]
    at = {c.name: i for i, c in enumerate(table.columns)}
    row = next(r for r in table.rows if r[at["submission_id"]] == "sub_full")

    assert row[at["dwelling_lat"]] == pytest.approx(-3.3869)
    assert row[at["dwelling_lon"]] == pytest.approx(36.6829)
    assert row[at["dwelling_accuracy"]] == pytest.approx(4.5)
    assert row[at["dwelling_alt"]] is None


def test_csv_survives_a_comma_and_non_ascii(
    three_households: list[SubmissionRecord], form: CompiledForm
) -> None:
    """`Ben, the elder` is one cell, and Excel opens the file as UTF-8."""
    bundle = bundle_of(three_households, [form])
    repeat = next(name for name, _ in bundle.files if name.endswith("-members.csv"))
    content = dict(bundle.files)[repeat]

    assert content.startswith(b"\xef\xbb\xbf"), "no BOM: Excel will mangle Swahili"
    assert b'"Ben, the elder"' in content
    read = read_bundle(bundle)
    assert read["sub_full"].repeats["members"][1].cells["name"] == "Ben, the elder"
