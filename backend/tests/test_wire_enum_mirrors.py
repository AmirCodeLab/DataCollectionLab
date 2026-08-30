"""The database CHECK constraints are the single source of truth for the closed
value sets on the wire. This is where that source meets the Python type.

The chain used to have two hand-copied links and now has one:

    001_initial.sql  --(this test)-->  Literal  --(generated)-->  openapi.json
                                                --(generated)-->  types.ts

Everything to the right of the `Literal` is produced by
`scripts/generate_api_contract.py` and checked byte for byte in CI, so a value
added to a `Literal` reaches the console or it fails the build. What no
generator can see is the step on the left: the database constraint and the
Python type are written by different hands in different languages, and adding a
status to one and not the other leaves an API that offers a filter the database
rejects, or a database row the API has no type for.

The console half of this file is gone. It read `SUBMISSION_STATUSES` and the
`OpKind` union out of `web/src/api/types.ts` with a regex, because that file was
hand-written and could drift on its own. It is generated now, and a test that
parses a generated file is testing the generator by proxy — badly, with a regex.
`tests/test_openapi_contract.py` tests it directly instead.
"""

import pathlib
import typing

import pglast
import pytest
from pglast import ast

from app.modules.projects.schemas import DevicePlatform, KeyRole, SecurityMode
from app.modules.submissions.schemas import SubmissionStatus
from app.modules.sync.schemas import OpKind, TombstoneSubject

REPO = pathlib.Path(__file__).resolve().parents[2]
SCHEMA = REPO / "backend" / "migrations" / "schema" / "001_initial.sql"


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


def literal_members(alias: typing.Any) -> set[str]:
    """The members of a PEP 695 `type X = Literal[...]` alias.

    `.__value__` is the step a plain `X = Literal[...]` did not need. It is
    worth the extra call: a named alias is what gives the OpenAPI document one
    entry per closed set instead of the same six strings inlined at every use.
    """
    return set(typing.get_args(alias.__value__))


def assert_mirrors(*, allowed: set[str], mirror: set[str], source: str) -> None:
    missing = sorted(allowed - mirror)
    extra = sorted(mirror - allowed)
    assert not (missing or extra), (
        f"{source} has drifted from {SCHEMA.name}: "
        f"missing {missing or 'nothing'}, unknown to the database {extra or 'nothing'}"
    )


def test_submission_status_mirrors_the_check_constraint(parsed):
    assert_mirrors(
        allowed=check_constraint_values(parsed, "submission_status_check"),
        mirror=literal_members(SubmissionStatus),
        source="app.modules.submissions.schemas.SubmissionStatus",
    )


def test_op_kind_mirrors_the_check_constraint(parsed):
    assert_mirrors(
        allowed=check_constraint_values(parsed, "submission_op_kind_check"),
        mirror=literal_members(OpKind),
        source="app.modules.sync.schemas.OpKind",
    )


def test_security_mode_mirrors_the_check_constraint(parsed):
    """Which mode a project runs in is fixed at creation and cannot be changed.

    A mode the database accepts but the wire type does not is a project the API
    cannot describe; one the wire type offers but the database rejects is a
    project creation that fails at the last step.
    """
    assert_mirrors(
        allowed=check_constraint_values(parsed, "project_security_mode_check"),
        mirror=literal_members(SecurityMode),
        source="app.modules.projects.schemas.SecurityMode",
    )


def test_key_role_mirrors_the_check_constraint(parsed):
    """Roles decide who a content key gets wrapped to (envelope §4.1, §4.3)."""
    assert_mirrors(
        allowed=check_constraint_values(parsed, "project_key_role_check"),
        mirror=literal_members(KeyRole),
        source="app.modules.projects.schemas.KeyRole",
    )


def test_device_platform_mirrors_the_check_constraint(parsed):
    """A platform the database rejects is a device that cannot register at all."""
    assert_mirrors(
        allowed=check_constraint_values(parsed, "device_platform_check"),
        mirror=literal_members(DevicePlatform),
        source="app.modules.projects.schemas.DevicePlatform",
    )


def test_tombstone_subject_mirrors_the_check_constraint(parsed):
    """A client pulls tombstones for subjects it does not handle yet (sync §5).

    So the wire type has to name every subject the database can store, not
    just the two the server writes today — a client that meets an unknown
    `subjectType` should skip that row, and it cannot skip what its own types
    say cannot exist.
    """
    assert_mirrors(
        allowed=check_constraint_values(parsed, "tombstone_subject_check"),
        mirror=literal_members(TombstoneSubject),
        source="app.modules.sync.schemas.TombstoneSubject",
    )
