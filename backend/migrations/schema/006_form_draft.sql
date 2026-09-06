-- 006_form_draft.sql — somewhere to keep a form that is not published yet.
--
-- NORMATIVE. migrations/versions/0006_form_draft.py transcribes this into
-- Alembic operations; tests/test_migrations.py asserts the two agree, and if
-- they ever disagree this file wins.
--
-- ============================================================================
-- What is deliberately NOT in this table, and why that is the design
-- ============================================================================
--
-- No `version`. No `ir_checksum`. No `published_at`, no `published_by`, no
-- `status`. There is no column here that can be set to mean "this is now a
-- version", because the failure this table invites is somebody promoting a
-- draft row into `form_version` directly and skipping `check_publishable`.
--
-- A comment saying "don't do that" is what the previous version of this design
-- had. The pattern that has actually worked in this repository every other time
-- is removing the shortcut rather than documenting it, so the shortcut is not
-- expressible: a draft has no identity a version needs, and moving one into
-- `form_version` means constructing that identity — the version number from the
-- sequence, the checksum from the IR — which is `publish_version` and nothing
-- else. `tests/test_form_version_has_one_writer.py` holds the other half: the
-- ORM model is constructed in exactly one function, and a second construction
-- site fails CI with its file and line.
--
-- Form IR §2.3, and docs/phase3-item0-builder-scope.md §6: the builder gets no
-- route of its own into `form_version`. The export work already found what a
-- second route costs — two callers disagreeing about which version a submission
-- belongs to (breaks 40, 42, 61).
--
-- One draft per form, so `form_id` is the whole key. Branching and
-- draft-of-draft versioning are out of v1 deliberately: they are cheap to add
-- and expensive to remove once authors rely on them.

CREATE TABLE form_draft (
    form_id     TEXT PRIMARY KEY REFERENCES form (id) ON DELETE CASCADE,

    -- The document being edited. Not validated here: a draft is allowed to be
    -- a form that does not compile, which is most of what editing one is.
    ir          JSONB       NOT NULL,

    -- Optimistic concurrency. One draft per form and more than one author is
    -- last-write-wins unless something stops it, and "somebody's afternoon
    -- silently discarded" is not a failure anyone reports as a bug — they
    -- assume they forgot to save.
    revision    INTEGER     NOT NULL DEFAULT 1,

    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by  TEXT,

    -- A draft holds a form definition and an author's test answers, never a
    -- respondent's. That is what makes it safe to store mutable and
    -- unencrypted, and it is worth stating so nobody reasons from the name to
    -- "drafts of submissions".
    CONSTRAINT form_draft_revision_positive CHECK (revision >= 1)
);

COMMENT ON TABLE form_draft IS
    'Unpublished form IR, one row per form. A draft becomes a version only '
    'through POST /forms/versions, which compiles and runs check_publishable. '
    'This table carries no version, checksum or published state on purpose: '
    'there is nothing here to promote.';
