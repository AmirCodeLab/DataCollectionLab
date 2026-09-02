-- Datasets become usable: per-row hashes, and the binding from a form version
-- to the dataset versions it was published against.
--
-- `dataset`, `dataset_version` and `dataset_record` have existed since 001 and
-- nothing has ever written to them. Two columns and one table are what they
-- were missing.

-- The row's own content hash: SHA-256 over canonical_json(data), the same
-- serialisation the encryption envelope uses (§5.1) rather than a second one
-- invented here. Two servers must produce the same bytes for the same row or
-- every delta is spurious, and that rule already exists with a conformance
-- vector behind it.
--
-- This is deliberately over the WHOLE row, not over the columns a form uses.
-- It answers one cheap question — "did anything about this row change" — and
-- is therefore version-independent and cacheable. It is NOT what decides
-- whether a device is sent a delta: an edit to a column no form references
-- changes this hash and must not cost a 50k-row list a transfer over a field
-- connection. That is stage two, a comparison of the projection onto the
-- columns the device's forms actually reference, and it is computed at diff
-- time from the rows this narrows down.
ALTER TABLE dataset_record
    ADD COLUMN row_hash TEXT NOT NULL DEFAULT '';

-- Delta computation reads (record_key, row_hash) for a whole version and never
-- touches `data` until it knows which rows to look at. On 50k rows that is the
-- difference between reading an index and reading the table.
CREATE INDEX dataset_record_version_hash_idx
    ON dataset_record (dataset_version_id, record_key, row_hash);

-- Which dataset version a form version was published against.
--
-- The IR names a dataset by KEY — `"dataset": "districts"` (Form IR §3) — and a
-- key is not a version. Resolving it at read time would mean a draft opened
-- against form v1 seeing whatever districts happens to be newest, which is the
-- same mistake as validating a v1 answer against v2's choice list: the answers
-- were given against a list that no longer exists, and nothing would say so.
--
-- So the key is resolved ONCE, at publish, and pinned here. A form version is
-- immutable and so is its view of its data. The resolver above this table takes
-- a submission and a dataset key and has no version parameter to get wrong —
-- the same shape as forms.service.compiled_form_for_submission (break 30, 40).
CREATE TABLE form_version_dataset (
    form_version_id TEXT NOT NULL REFERENCES form_version(id) ON DELETE CASCADE,
    -- The key as the IR spells it, which is what a `choices.dataset` says.
    dataset_key TEXT NOT NULL,
    dataset_version_id TEXT NOT NULL REFERENCES dataset_version(id) ON DELETE RESTRICT,
    PRIMARY KEY (form_version_id, dataset_key)
);

-- RESTRICT above, not CASCADE, and that is the point of writing it down: a
-- dataset version that a published form version still references must not be
-- deletable. Deleting it would leave a form whose choice lists cannot be
-- resolved and whose already-collected answers cannot be explained.

-- "Which form versions still need this dataset version?" is what retention asks,
-- on the server and, in the same shape, on the device.
CREATE INDEX form_version_dataset_version_idx
    ON form_version_dataset (dataset_version_id);
