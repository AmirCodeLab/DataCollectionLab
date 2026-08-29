"""Validates the SQL schema using PostgreSQL's own parser (libpg_query).

This does not need a running database. It catches syntax errors, broken foreign
key targets, and the structural invariants the specs depend on.
"""

import pathlib

import pglast
import pytest
from pglast import ast

SCHEMA = pathlib.Path(__file__).resolve().parents[1] / "migrations" / "schema" / "001_initial.sql"
SQL = SCHEMA.read_text()


@pytest.fixture(scope="module")
def parsed():
    return pglast.parse_sql(SQL)


@pytest.fixture(scope="module")
def tables(parsed):
    """table name -> {column name -> column node}"""
    out = {}
    for stmt in parsed:
        node = stmt.stmt
        if isinstance(node, ast.CreateStmt):
            columns = {}
            for element in node.tableElts or ():
                if isinstance(element, ast.ColumnDef):
                    columns[element.colname] = element
            out[node.relation.relname] = columns
    return out


def _constraints(node):
    for element in node.tableElts or ():
        if isinstance(element, ast.Constraint):
            yield element
        if isinstance(element, ast.ColumnDef):
            yield from element.constraints or ()


@pytest.fixture(scope="module")
def create_stmts(parsed):
    return [s.stmt for s in parsed if isinstance(s.stmt, ast.CreateStmt)]


def test_schema_is_valid_postgresql(parsed):
    """If this fails the file is not valid PostgreSQL — the parser is the real one."""
    assert len(parsed) > 0


def test_every_foreign_key_points_at_a_real_table(create_stmts, tables):
    known = set(tables)
    problems = []
    for node in create_stmts:
        for constraint in _constraints(node):
            if constraint.contype == pglast.enums.parsenodes.ConstrType.CONSTR_FOREIGN:
                target = constraint.pktable.relname
                if target not in known:
                    problems.append(f"{node.relation.relname} -> {target}")
    assert problems == [], f"foreign keys with no target table: {problems}"


def test_every_table_has_a_primary_key(create_stmts):
    missing = []
    for node in create_stmts:
        has_pk = any(
            c.contype == pglast.enums.parsenodes.ConstrType.CONSTR_PRIMARY
            for c in _constraints(node)
        )
        if not has_pk:
            missing.append(node.relation.relname)
    assert missing == [], f"tables without a primary key: {missing}"


def test_primary_keys_are_client_generatable_text_not_serial(create_stmts):
    """Devices create submissions, ops and media offline and must name them
    before the server has seen them. A serial primary key makes that impossible.

    Checks the parsed column types, not the raw text — the word "serial" appears
    in an explanatory comment and a text search would match it there.
    """
    offenders = []
    for node in create_stmts:
        for element in node.tableElts or ():
            if not isinstance(element, ast.ColumnDef):
                continue
            is_pk = any(
                c.contype == pglast.enums.parsenodes.ConstrType.CONSTR_PRIMARY
                for c in (element.constraints or ())
            )
            if not is_pk:
                continue
            type_name = ".".join(n.sval for n in element.typeName.names)
            if "serial" in type_name.lower():
                offenders.append(f"{node.relation.relname}.{element.colname}: {type_name}")
    assert offenders == [], f"serial primary keys block offline creation: {offenders}"


# -- invariants the specs depend on ---------------------------------------


def test_submission_op_enforces_nonce_uniqueness(tables):
    """Encryption spec 4.5: AES-GCM fails catastrophically on nonce reuse, so
    the database must reject a duplicate (content_key_id, nonce)."""
    assert "UNIQUE (content_key_id, nonce)" in SQL


def test_submission_op_enforces_counter_uniqueness_per_device():
    """Sync spec 3: ordering is by (counter, device_id); a device must never
    reuse a counter."""
    assert "UNIQUE (device_id, counter)" in SQL


def test_submission_op_has_both_plaintext_and_ciphertext_columns(tables):
    """field_level mode uses both across different ops in one submission."""
    op = tables["submission_op"]
    assert "value" in op
    assert "value_ciphertext" in op
    assert "content_key_id" in op
    assert "nonce" in op


def test_submission_op_encryption_columns_are_all_or_nothing():
    assert "submission_op_encryption_check" in SQL


def test_media_hash_column_is_named_for_ciphertext(tables):
    """Encryption spec 6: hashing plaintext would let the server confirm that
    two submissions contain the same file."""
    assert "ciphertext_hash" in tables["media"]
    assert "plaintext_hash" not in tables["media"]


def test_project_key_public_key_is_x25519_sized():
    assert "octet_length(public_key) = 32" in SQL


def test_wrapped_key_sizes_are_constrained():
    assert "octet_length(ephemeral_public) = 32" in SQL
    assert "octet_length(nonce) = 12" in SQL
    assert "octet_length(wrapped_key) = 48" in SQL


def test_security_mode_matches_the_encryption_spec():
    for mode in ("standard", "field_level", "project_e2e"):
        assert f"'{mode}'" in SQL


def test_op_kinds_match_the_sync_spec():
    for kind in ("set", "unset", "repeat_add", "repeat_delete", "finalize", "reopen"):
        assert f"'{kind}'" in SQL


def test_media_does_not_foreign_key_to_submission_op(create_stmts):
    """An op referencing media is accepted before the file arrives, so a FK
    would reject valid operations."""
    for node in create_stmts:
        if node.relation.relname != "media":
            continue
        for constraint in _constraints(node):
            if constraint.contype == pglast.enums.parsenodes.ConstrType.CONSTR_FOREIGN:
                assert constraint.pktable.relname != "submission_op"


def test_tenant_tables_have_no_organization_id_column(tables):
    """Isolation is at the schema level. An org_id column would invite a query
    that forgets to filter on it."""
    offenders = [
        name
        for name, cols in tables.items()
        if not name.startswith("platform_") and "organization_id" in cols
    ]
    assert offenders == [], f"tenant tables carrying organization_id: {offenders}"


def test_visit_is_separate_from_case(tables):
    """A case can have many visits; collapsing them breaks longitudinal work."""
    assert "visit" in tables
    assert "case_id" in tables["visit"]
    assert "sequence" in tables["visit"]


def test_form_version_is_uniquely_versioned_per_form():
    assert "UNIQUE (form_id, version)" in SQL


def test_environment_kinds_are_constrained():
    for kind in ("development", "staging", "production"):
        assert f"'{kind}'" in SQL
