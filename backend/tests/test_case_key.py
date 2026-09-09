"""The composite key's escaping rule (Form IR §3.1), including the collisions
the rule exists to prevent — break 8 of item 2's analysis."""

from __future__ import annotations

import pytest

from app.modules.entities.case_key import CaseKeyRefused, compose, key_of, split


@pytest.mark.parametrize(
    "parts",
    [
        ["A", "B", "C"],
        ["A|B"],
        ["A", "|B"],
        ["A|", "B"],
        ["A\\", "B"],
        ["A\\|", "B"],
        ["\\", "|", "\\|", "|\\"],
        ["settlement 12", "structure/3", "hh 0007"],
        ["   spaced   ", "Case"],
    ],
)
def test_split_is_the_inverse_of_compose(parts: list[str]) -> None:
    assert split(compose(parts)) == parts


def test_the_collisions_the_rule_exists_for_do_not_collide() -> None:
    """One column holding `A|B` and two columns holding `A`, `B`: different
    rows, different keys. And the pair a doubled pipe would have merged."""
    assert compose(["A|B"]) != compose(["A", "B"])
    assert compose(["A|", "B"]) != compose(["A", "|B"])
    assert compose(["A|B"]) == "A\\|B"
    assert compose(["A", "B"]) == "A|B"


def test_the_composed_form_is_what_the_specification_says() -> None:
    assert compose(["A\\", "B|C"]) == "A\\\\|B\\|C"


def test_a_part_with_no_identity_refuses_the_row_naming_the_column() -> None:
    with pytest.raises(CaseKeyRefused) as refused:
        key_of(
            {"settlementCode": "S1", "structureId": "  ", "hhId": "7"},
            ["settlementCode", "structureId", "hhId"],
        )
    assert refused.value.column == "structureId"
    with pytest.raises(CaseKeyRefused):
        key_of({"settlementCode": "S1"}, ["settlementCode", "structureId"])


def test_a_key_is_the_cells_values_exactly_in_the_named_order() -> None:
    row = {"settlementCode": "S1 ", "structureId": 3, "hhId": "0007"}
    assert key_of(row, ["settlementCode", "structureId", "hhId"]) == "S1 |3|0007"
    assert key_of(row, ["hhId", "settlementCode"]) == "0007|S1 "
