-- How a form version got here, and what did not survive the trip.
--
-- Six months after an import somebody asks "why does this form not have the
-- question I put in the spreadsheet?". Today the only answer is a report file
-- that was emailed once and is now in nobody's inbox. These columns make the
-- question answerable from the database that holds the form.
--
-- Kept ON the version rather than in a side table because it is a property of
-- that immutable row: version 3 was imported from one file with one set of
-- warnings, and version 4 from another. A separate table would need its own
-- rule about which import belongs to which version, and would get it wrong the
-- first time somebody re-imported.
--
-- All nullable: a form published through POST /forms/versions with hand-written
-- IR was not imported at all, and NULL is the honest record of that. An empty
-- report would claim an import happened and found nothing wrong.

ALTER TABLE form_version
    -- The file's own name, as the person who uploaded it knew it. Not a path:
    -- the file is not kept, and a path would point at nothing.
    ADD COLUMN import_source_name TEXT,
    -- SHA-256 of the uploaded bytes, so "is this the same spreadsheet?" is
    -- answerable without keeping the spreadsheet. Two versions with the same
    -- digest came from the same file, whatever it was called that day.
    ADD COLUMN import_source_sha256 TEXT,
    -- Every diagnostic, exactly as the API returned it — severity, code,
    -- message, sheet, row, column, cell value. JSONB rather than the rendered
    -- report because the rendering is a presentation choice that will change
    -- and the findings are the record.
    ADD COLUMN import_report JSONB,
    -- Which importer produced it. A form imported before a bug was fixed has
    -- warnings that mean something different from the same warnings today, and
    -- without this there is no way to tell those apart.
    ADD COLUMN import_importer_version TEXT,
    ADD COLUMN imported_at TIMESTAMPTZ;

-- Either a version was imported or it was not; a half-recorded import is a
-- worse answer than none, because it looks like a complete one.
ALTER TABLE form_version
    ADD CONSTRAINT form_version_import_complete_check CHECK (
        (import_source_name IS NULL
            AND import_source_sha256 IS NULL
            AND import_report IS NULL
            AND import_importer_version IS NULL
            AND imported_at IS NULL)
        OR
        (import_source_name IS NOT NULL
            AND import_source_sha256 IS NOT NULL
            AND import_report IS NOT NULL
            AND import_importer_version IS NOT NULL
            AND imported_at IS NOT NULL)
    );

-- "Which of our forms came from a spreadsheet, and which were hand-written?"
-- is the question a partial index answers cheaply, and it is asked whenever
-- somebody is deciding whether an importer change is safe to make.
CREATE INDEX form_version_imported_idx
    ON form_version (imported_at DESC)
    WHERE imported_at IS NOT NULL;
