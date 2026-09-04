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
from app.modules.export.statistical import plan_columns
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
            # The types Q3 is about: each survives a CSV trivially and has
            # somewhere to go wrong in a .dta or a .sav.
            {
                "type": "question",
                "id": "interview_date",
                "dataType": "date",
                "label": {"en": "Date of interview"},
            },
            {
                "type": "question",
                "id": "started_time",
                "dataType": "time",
                "label": {"en": "Time started"},
            },
            {
                "type": "question",
                "id": "visited_at",
                "dataType": "datetime",
                "label": {"en": "Visited at"},
            },
            {
                "type": "question",
                "id": "literate",
                "dataType": "boolean",
                "label": {"en": "Respondent is literate"},
            },
            {
                "type": "question",
                "id": "crops",
                "dataType": "select_multiple",
                "label": {"en": "Crops grown"},
                "choices": {
                    "kind": "inline",
                    "items": [
                        {"value": "maize", "label": {"en": "Maize"}},
                        {"value": "beans", "label": {"en": "Beans"}},
                        {"value": "cassava", "label": {"en": "Cassava"}},
                    ],
                },
            },
            {
                "type": "question",
                "id": "remarks",
                "dataType": "text",
                "label": {"en": "Enumerator remarks"},
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
    """The whole pipeline, as `service.export_form` assembles it without a database."""
    plan = build_plan(forms)
    tables = build_tables(plan, records, shape=shape, base_name="household")  # type: ignore[arg-type]
    stored = None
    if fmt in ("dta", "sav"):
        stored = {t.name: plan_columns(t.columns, t.rows) for t in tables}
    manifest = build_manifest(
        plan,
        tables,
        records,
        form_id="household",
        form_title="Household survey",
        language="en",
        shape=shape,  # type: ignore[arg-type]
        ciphertext_fields=ciphertext_fields or {},
        stored=stored,
    )
    return write_bundle(tables, manifest, fmt=fmt, stored=stored)


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
                set_op("interview_date", "2026-09-03"),
                set_op("started_time", "09:25:13"),
                # A UTC offset. Neither .dta nor .sav can store one, which is
                # why a datetime is written as text and a date is not.
                set_op("visited_at", "2026-09-03T09:25:13+03:00"),
                # `False`, not `True`: a boolean read back as the float 0.0
                # is the one that goes wrong, and `True` would not show it.
                set_op("literate", False),
                set_op("crops", ["maize", "cassava"]),
                set_op("remarks", 'She asked us to come back "next week", if possible.'),
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
                set_op("literate", True),
                set_op("interview_date", "2026-09-04"),
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


@pytest.mark.parametrize("fmt", ["csv", "xlsx", "dta", "sav"])
def test_a_long_export_reads_back_as_the_submissions_it_came_from(
    three_households: list[SubmissionRecord], form: CompiledForm, fmt: Format
) -> None:
    """Export, re-import, compare — for every value, in **every** format.

    Running it over CSV alone would prove almost nothing about the two
    statistical formats, which is where the types actually are: a decimal that
    loses precision, a date that arrives as a string, a boolean that comes back
    as `0.0`, a missing value that arrives as `nan` rather than empty. All four
    are invisible to a CSV round trip and all four are real.

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

# --- what a statistical format adds, and what it can lose -----------------


def test_a_columns_type_changes_with_the_data_and_the_manifest_says_so() -> None:
    """The mistake that passes every test, for this format.

    readstat types a column from the values it holds, so one unreadable
    interview turns `income` from a numeric column into a text one — and
    `100.0` into the string `"100.0"`. Every single-export test is internally
    consistent either way; the defect only exists *between* two exports of the
    same form. A do-file that says `summarize income` works one week and does
    nothing the next, and what differs is which interviews were encrypted.

    It cannot be fixed by choosing a type, because both types are correct: a
    numeric column cannot hold the token, and writing the token as missing is
    the failure item 5 names. What it can be is **stated** — so this asserts the
    change happens, that the manifest records it in the export where it did, and
    that the export where it did not says the declared type instead of staying
    silent.
    """
    form = CompiledForm(household_ir())
    common = [set_op("consent", "yes"), Op("repeat_add", path="members[a1]")]

    readable = record(
        "sub_plain", [*common, set_op("members[a1].income", 100.0), Op("finalize")], form=form
    )
    encrypted = record(
        "sub_secret", [*common, secret_op("members[a1].income"), Op("finalize")], form=form
    )

    def income(bundle: Any) -> Any:
        return next(
            column
            for table in bundle.manifest.tables
            for column in table.columns
            if column.column == "income"
        )

    plain = income(bundle_of([readable], [form], fmt="dta"))
    secret = income(bundle_of([encrypted], [form], fmt="dta"))

    assert plain.storage_type == "numeric"
    assert secret.storage_type == "string"

    # Both say what they declared, so a reader can tell a column that changed
    # from one that was always text.
    assert plain.declared_storage_type == "numeric"
    assert secret.declared_storage_type == "numeric"
    assert plain.storage_changed_because is None
    assert "ENCRYPTED" in (secret.storage_changed_because or "")

    changed = bundle_of([encrypted], [form], fmt="dta").manifest.notes
    assert any("numeric one week and text the next" in note for note in changed)


def test_a_value_that_will_not_fit_its_column_is_refused_not_dropped() -> None:
    """The guard under the whole module, at the moment it can still be acted on.

    `plan_columns` is supposed to turn a column to text when it holds the token
    or a date that will not parse. If it ever stopped doing that, the tidy
    outcome would be to write the offending value as missing and keep the column
    numeric — a file with the right types, the right row count, and an answer
    quietly deleted. So the writer refuses instead, naming the column and the
    value, at both moments a type can go wrong: before writing, and after
    reading the file back.
    """
    from app.modules.export.plan import Column
    from app.modules.export.shape import Table
    from app.modules.export.statistical import StatColumn, TypeChanged, write_table

    def lying(name: str, storage: str) -> list[Any]:
        return [
            StatColumn(
                name=name,
                source=name,
                storage=storage,  # type: ignore[arg-type]
                declared_storage=storage,  # type: ignore[arg-type]
                changed_because=None,
                label=None,
            )
        ]

    numeric = Table(
        name="t",
        kind="submissions",
        columns=(Column(name="income", source="field", field_id="income", data_type="decimal"),),
        rows=((ENCRYPTED,), (100.0,)),
    )
    with pytest.raises(TypeChanged, match="numeric column cannot carry it"):
        write_table(numeric, lying("income", "numeric"), fmt="dta")

    dated = Table(
        name="t",
        kind="submissions",
        columns=(Column(name="seen_on", source="field", field_id="seen_on", data_type="date"),),
        rows=(("last tuesday",),),
    )
    with pytest.raises(TypeChanged, match="is not one"):
        write_table(dated, lying("seen_on", "date"), fmt="dta")


def test_an_unanswered_date_column_is_still_a_date_column() -> None:
    """Found by the read-back check, and it is why the check exists.

    readstat types a column of nothing but nulls as **string**, so a date
    question nobody answered produced a text column while the same question
    answered once produced a date column — the same form, two schemas, decided
    by the data. The read-back check caught it; nothing else would have, because
    every value in both files is correct.
    """
    form = CompiledForm(household_ir())
    blank = record("sub_blank", [set_op("consent", "yes"), Op("finalize")], form=form)

    described = {
        column.column: column
        for table in bundle_of([blank], [form], fmt="dta").manifest.tables
        for column in table.columns
    }
    assert described["interview_date"].storage_type == "date"
    assert described["interview_date"].storage_changed_because is None


def test_names_are_shortened_deterministically_and_never_merged() -> None:
    """Two questions must not become one column, and the file must say which.

    Stata caps a variable name at 32 characters and readstat does not enforce
    it — it will write a `.dta` that Stata refuses — so the shortening is ours.
    Two 37-character ids differing only at character 36 truncate to the same 32,
    which would be a silent merge of two questions' answers: one column, right
    type, right row count, wrong data.
    """
    from app.modules.export.statistical import NAME_LIMIT

    gross = "household_member_income_monthly_gross"
    net = "household_member_income_monthly_net"
    assert gross[:NAME_LIMIT] == net[:NAME_LIMIT], "the test data must actually collide"

    form = CompiledForm(
        household_ir(
            1,
            extra=[
                {"type": "question", "id": gross, "dataType": "decimal", "label": {"en": "G"}},
                {"type": "question", "id": net, "dataType": "decimal", "label": {"en": "N"}},
            ],
        )
    )
    one = record(
        "sub_long",
        [set_op(gross, 10.0), set_op(net, 4.0), Op("finalize")],
        form=form,
    )
    bundle = bundle_of([one], [form], fmt="dta")
    described = {
        column.column: column
        for table in bundle.manifest.tables
        for column in table.columns
    }

    stored = {described[gross].stored_as, described[net].stored_as}
    assert len(stored) == 2, f"two questions share one column: {stored}"
    assert all(len(name) <= NAME_LIMIT for name in stored)
    # The manifest is the only place the long name and the short one are tied
    # together, so an analysis written against the CSV can find its column.
    assert described[gross].stored_as != described[gross].column
    assert any("shortened name" in note for note in bundle.manifest.notes)

    read = read_bundle(bundle)
    assert read["sub_long"].top[gross] == 10.0
    assert read["sub_long"].top[net] == 4.0


def test_shortening_depends_on_the_form_and_not_on_the_data() -> None:
    """A do-file written last month has to find its columns this month.

    Names are claimed in plan order, and plan order is a function of the form
    versions alone — so two exports of one form, with different submissions in
    them, name every column identically. If the serial were assigned by which
    rows happened to arrive, a collision-resolved name would move.
    """
    long_a = "household_member_income_monthly_gross"
    long_b = "household_member_income_monthly_net"
    form = CompiledForm(
        household_ir(
            1,
            extra=[
                {"type": "question", "id": long_a, "dataType": "decimal", "label": {"en": "G"}},
                {"type": "question", "id": long_b, "dataType": "decimal", "label": {"en": "N"}},
            ],
        )
    )

    def names(ops: list[Op]) -> list[tuple[str, str]]:
        bundle = bundle_of([record("s", ops, form=form)], [form], fmt="dta")
        return [
            (column.column, column.stored_as)
            for table in bundle.manifest.tables
            for column in table.columns
        ]

    assert names([set_op(long_a, 1.0), Op("finalize")]) == names(
        [set_op(long_b, 2.0), set_op("consent", "yes"), Op("finalize")]
    )


def test_a_date_is_stored_natively_and_a_datetime_is_not() -> None:
    """The offset is part of a datetime's value, and neither format holds one.

    A date has no offset to lose, so it is written as a real Stata date — worth
    having, because a string date has to be parsed before it can be used. A
    datetime written natively would have to drop `+03:00` or shift the value,
    and both change when the interview happened.
    """
    from app.modules.export.plan import build_plan
    from app.modules.export.statistical import declared_storage

    form = CompiledForm(household_ir())
    columns = {column.name: column for column in build_plan([form]).parent}

    assert declared_storage(columns["interview_date"]) == "date"
    assert declared_storage(columns["visited_at"]) == "string"
    assert declared_storage(columns["received_at"]) == "string"
    assert declared_storage(columns["started_time"]) == "string"

    one = record(
        "sub_when",
        [
            set_op("interview_date", "2026-09-03"),
            set_op("visited_at", "2026-09-03T09:25:13+03:00"),
            Op("finalize"),
        ],
        form=form,
    )
    read = read_bundle(bundle_of([one], [form], fmt="dta"))
    assert read["sub_when"].top["interview_date"] == "2026-09-03"
    assert read["sub_when"].top["visited_at"] == "2026-09-03T09:25:13+03:00"


def test_a_long_answer_survives_a_dta_and_is_refused_by_a_sav() -> None:
    """Each format's own maximum, decided here rather than left to the library.

    A `.dta` promotes anything over 2,045 bytes to a `strL` and holds it whole,
    so a long remark is fine. A `.sav` cannot exceed SPSS's 32,767 bytes, and
    readstat will write past that without a word — so the exporter refuses,
    naming the column and the formats that do hold it. Truncating to fit would
    lose an answer to keep a file tidy; writing it anyway produces a file SPSS
    may not open, silently. Neither is this exporter's trade to make.
    """
    from app.modules.export.statistical import ValueTooLong

    form = CompiledForm(household_ir())
    long_remark = record(
        "sub_essay",
        [set_op("remarks", "s" * 40000), Op("finalize")],
        form=form,
    )

    read = read_bundle(bundle_of([long_remark], [form], fmt="dta"))
    assert read["sub_essay"].top["remarks"] == "s" * 40000

    with pytest.raises(ValueTooLong, match="32,767") as refused:
        bundle_of([long_remark], [form], fmt="sav")
    assert refused.value.column == "remarks"
    assert refused.value.found == 40000
    # The useful half of a refusal: what to do instead.
    assert "dta" in str(refused.value)


def test_the_string_limit_is_counted_in_bytes_and_not_characters() -> None:
    """20,000 Arabic characters are 40,000 bytes, and the format counts bytes.

    A character-counted check waves this straight through and produces the
    out-of-spec `.sav` the byte check exists to prevent. This platform is RTL
    and Swahili from the start, so it is the ordinary case and not an edge one.
    """
    from app.modules.export.statistical import ValueTooLong

    form = CompiledForm(household_ir())
    arabic = record(
        "sub_arabic",
        [set_op("remarks", "ش" * 20000), Op("finalize")],
        form=form,
    )
    assert len("ش" * 20000) == 20000, "under SPSS's limit if you count characters"
    assert len(("ش" * 20000).encode()) == 40000, "over it in the bytes it stores"

    with pytest.raises(ValueTooLong) as refused:
        bundle_of([arabic], [form], fmt="sav")
    assert refused.value.found == 40000

    # …and the .dta takes it, because a strL is 2 GB.
    read = read_bundle(bundle_of([arabic], [form], fmt="dta"))
    assert read["sub_arabic"].top["remarks"] == "ش" * 20000


def test_the_manifest_states_both_string_limits() -> None:
    """An export that quietly cannot hold something must say so on its face."""
    from app.modules.export.manifest import STRING_LIMIT_NOTE

    form = CompiledForm(household_ir())
    one = record("sub_note", [set_op("remarks", "short"), Op("finalize")], form=form)

    assert STRING_LIMIT_NOTE in bundle_of([one], [form], fmt="dta").manifest.notes
    assert STRING_LIMIT_NOTE not in bundle_of([one], [form], fmt="csv").manifest.notes
