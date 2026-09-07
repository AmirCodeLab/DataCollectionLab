-- 007_form_draft_test_cases.sql — an author's test cases live with the draft.
--
-- NORMATIVE. migrations/versions/0007_form_draft_test_cases.py transcribes
-- this into Alembic operations; tests/test_migrations.py asserts the two agree,
-- and if they ever disagree this file wins.
--
-- ============================================================================
-- A test case is not a conformance vector, and must not be stored as one
-- ============================================================================
--
-- The shape is close enough to be tempting: a test case is an ordered list of
-- steps — set an answer, add a row, delete a row — with expectations, which is
-- exactly conformance/README.md's step kinds. It goes here and not in
-- conformance/vectors because the two are unlike things:
--
--   A vector is normative, is owned by this repository, compares two engines,
--   and changes only with a spec change (rule 3).
--
--   A test case is owned by the author, asserts about one form, and is
--   SUPPOSED to change when the author changes their form. It carries what the
--   author expects to be true — the skip pattern four screens later that used
--   to work — and it is replayed against the draft after every edit.
--
-- Mixing them means the vector count stops meaning what it means, rule 3 stops
-- being enforceable, and generate_vectors.py — which had to be taught not to
-- delete files it did not write (break 82) — acquires a class of file it cannot
-- recognise. The one legitimate crossing is manual and deliberate: an author's
-- test case that turns out to expose an engine disagreement is rewritten BY
-- HAND as a vector, in a commit that says so.
--
-- The server stores and returns these. It runs nothing: the cases run in the
-- builder, through the same engine the handset runs (docs/phase3-item0-builder-scope.md §4).
-- A column and not a table, because a test case has no identity apart from the
-- draft it belongs to and is saved, versioned (by `revision`) and discarded
-- with it.

ALTER TABLE form_draft
    ADD COLUMN test_cases JSONB NOT NULL DEFAULT '[]'::jsonb;

COMMENT ON COLUMN form_draft.test_cases IS
    'The author''s test cases for this draft: steps and expectations, replayed '
    'in the builder after every edit. Owned by the author, about this form, '
    'expected to change with it. Never a conformance vector; never stored as one.';
