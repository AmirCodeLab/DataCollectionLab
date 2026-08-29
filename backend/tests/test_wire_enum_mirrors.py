"""The database CHECK constraints are the single source of truth for the
closed-value sets on the wire; everything else is a hand-written mirror.

Until the OpenAPI contract exists (Phase 0 deliverable 4) the console's
TypeScript types and the backend's Pydantic `Literal`s are copied by hand from
`migrations/schema/001_initial.sql`. That copy drifts silently: adding a status
to the constraint and to Python leaves the console rendering a value it has no
type for, and dropping one leaves the console offering a filter the database
rejects. These tests make the drift a test failure instead.

When the generated OpenAPI client lands, the TypeScript half of this goes away —
the schema-to-Python half stays.
"""

import pathlib
import re
import typing

import pglast
import pytest
from pglast import ast

from app.modules.submissions.schemas import SubmissionStatus
from app.modules.sync.schemas import OpKind

REPO = pathlib.Path(__file__).resolve().parents[2]
SCHEMA = REPO / "backend" / "migrations" / "schema" / "001_initial.sql"
CONSOLE_TYPES = REPO / "web" / "src" / "api" / "types.ts"


@pytest.fixture(scope="module")
def parsed():
    return pglast.parse_sql(SCHEMA.read_text())


def check_constraint_values(parsed, name: str) -> set[str]:
    """The string literals in `CHECK (col IN ('a', 'b', ...))`, by constraint name.

    Parsed rather than regexed: a text search would also match the value in a
    neighbouring comment or DEFAULT and would miss a constraint reformatted
    across lines.
    """
    for stmt in parsed:
        node = stmt.stmt
        if not isinstance(node, ast.CreateStmt):
            continue
        for element in node.tableElts or ():
            if not isinstance(element, ast.Constraint) or element.conname != name:
                continue
            expr = element.raw_expr
            assert isinstance(expr, ast.A_Expr), f"{name} is not a simple IN expression"
            assert expr.kind == pglast.enums.parsenodes.A_Expr_Kind.AEXPR_IN, (
                f"{name} is no longer an IN list — this test reads one"
            )
            return {const.val.sval for const in expr.rexpr}
    raise AssertionError(f"no CHECK constraint named {name} in {SCHEMA.name}")


def console_const_array(name: str) -> set[str]:
    """The members of an `export const NAME = [...] as const;` array in types.ts."""
    source = CONSOLE_TYPES.read_text()
    match = re.search(
        rf"export const {re.escape(name)}\s*=\s*\[(.*?)\]\s*as const;",
        source,
        re.DOTALL,
    )
    assert match, f"no `export const {name} = [...] as const;` in {CONSOLE_TYPES}"
    values = re.findall(r'"([^"]*)"', match.group(1))
    assert values, f"{name} in {CONSOLE_TYPES} parsed as empty"
    return set(values)


def assert_mirrors(*, allowed: set[str], mirror: set[str], source: str) -> None:
    missing = sorted(allowed - mirror)
    extra = sorted(mirror - allowed)
    assert not (missing or extra), (
        f"{source} has drifted from {SCHEMA.name}: "
        f"missing {missing or 'nothing'}, unknown to the database {extra or 'nothing'}"
    )


def test_python_submission_status_mirrors_the_check_constraint(parsed):
    assert_mirrors(
        allowed=check_constraint_values(parsed, "submission_status_check"),
        mirror=set(typing.get_args(SubmissionStatus)),
        source="app.modules.submissions.schemas.SubmissionStatus",
    )


def test_console_submission_statuses_mirror_the_check_constraint(parsed):
    assert_mirrors(
        allowed=check_constraint_values(parsed, "submission_status_check"),
        mirror=console_const_array("SUBMISSION_STATUSES"),
        source="SUBMISSION_STATUSES in web/src/api/types.ts",
    )


def test_python_op_kind_mirrors_the_check_constraint(parsed):
    assert_mirrors(
        allowed=check_constraint_values(parsed, "submission_op_kind_check"),
        mirror=set(typing.get_args(OpKind)),
        source="app.modules.sync.schemas.OpKind",
    )


def test_console_op_kind_mirrors_the_check_constraint(parsed):
    """The console spells this as a union, not an array — read the union members."""
    source = CONSOLE_TYPES.read_text()
    match = re.search(r"export type OpKind\s*=(.*?);", source, re.DOTALL)
    assert match, f"no `export type OpKind` in {CONSOLE_TYPES}"
    assert_mirrors(
        allowed=check_constraint_values(parsed, "submission_op_kind_check"),
        mirror=set(re.findall(r'"([^"]*)"', match.group(1))),
        source="OpKind in web/src/api/types.ts",
    )
