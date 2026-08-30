-- DCP database schema v0.1 — media capture
-- Specs: specs/encryption-envelope-v0.1.md §6, specs/sync-protocol-v0.1.md §9
--
-- Applied after 001_initial.sql. Together the files in this directory are the
-- NORMATIVE schema; tests/test_migrations.py executes them in name order and
-- asserts `alembic upgrade head` produces exactly the same thing.
--
-- A separate file rather than an edit to 001, because 001 is a migration that
-- self-hosted installations have already run. Rewriting it would make the
-- normative schema disagree with every database in the field.

-- ===========================================================================
-- MEDIA
-- ===========================================================================

-- Who captured the file, and which field it answers.
--
-- `field_path` is plaintext in every security mode, and that is not a leak
-- being introduced here: an operation's `path` already travels in the clear
-- (envelope §3.1 — the server learns which fields were answered, never their
-- values). Storing it makes a pending file nameable in the console before the
-- op it belongs to has arrived.
ALTER TABLE media
    ADD COLUMN device_id  text REFERENCES device (id) ON DELETE RESTRICT,
    ADD COLUMN field_path text;

-- Envelope §6: "Each media file gets its OWN content key, independent of the
-- operation key." The 001 foreign key pointed `media.content_key_id` at
-- submission_content_key, which cannot hold a media key: that table is
-- UNIQUE (submission_id, device_id) by design — one operation key per device
-- per submission — and one device routinely captures several files into one
-- submission. The column stays, as the media key's own id (the wrap AAD is
-- project_key_id || content_key_id, so unwrapping needs it), and the wraps
-- live in media_wrapped_key below.
ALTER TABLE media DROP CONSTRAINT media_content_key_id_fkey;

-- The media key wrapped once per active project key, exactly as an operation
-- content key is (envelope §4.3, §4.4). Sizes checked here for the same reason
-- submission_wrapped_key checks them: a 31-byte "X25519 public key" is a
-- corrupt row that would only be discovered by the person trying to recover
-- the data, years later.
CREATE TABLE media_wrapped_key (
    media_id            text NOT NULL REFERENCES media (id) ON DELETE CASCADE,
    project_key_id      text NOT NULL REFERENCES project_key (id) ON DELETE RESTRICT,
    ephemeral_public    bytea NOT NULL,
    nonce               bytea NOT NULL,
    wrapped_key         bytea NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (media_id, project_key_id),
    CONSTRAINT media_wrapped_key_sizes_check
        CHECK (octet_length(ephemeral_public) = 32
               AND octet_length(nonce) = 12
               AND octet_length(wrapped_key) = 48)
);

-- One row per chunk that has landed. `media_upload_session.received_chunks` is
-- a count and a count cannot resume an upload: chunks may arrive in any order,
-- and a client that reconnects has to be told exactly which indexes to skip
-- rather than re-sending everything after the first gap.
--
-- `chunk_hash` is over the bytes AS STORED, which for encrypted media is
-- ciphertext. Nothing here ever hashes plaintext (envelope §6).
CREATE TABLE media_chunk (
    media_id        text NOT NULL REFERENCES media (id) ON DELETE CASCADE,
    chunk_index     integer NOT NULL,
    size_bytes      integer NOT NULL,
    chunk_hash      text NOT NULL,
    storage_key     text NOT NULL,
    received_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (media_id, chunk_index),
    CONSTRAINT media_chunk_index_check CHECK (chunk_index >= 0),
    CONSTRAINT media_chunk_size_check CHECK (size_bytes > 0)
);

-- The console's "which files are still missing" view, and the resolution check
-- for an op that referenced media before the file arrived.
CREATE INDEX media_submission_idx ON media (submission_id, status);

-- ===========================================================================
-- PROJECT MEDIA POLICY
-- ===========================================================================

-- Per-project capture settings, fetched by devices alongside the crypto config
-- and cached for however long the device is next offline.
--
-- Compression is a project decision rather than a device one because it trades
-- evidentiary quality against bandwidth, and only the study knows which side it
-- is on: a housing-condition survey over 2G wants 1024px at quality 60; a
-- clinical wound-progression study wants the sensor's own pixels.
--
-- The GPS threshold is here for a sharper reason. A phone indoors will happily
-- report a 2 km "fix", and a point that wrong is worse than a missing one —
-- it is wrong with the same authority as a good one, and nothing downstream can
-- tell them apart. The client refuses a fix worse than this rather than storing
-- it quietly (see the capture path in shared/core).
ALTER TABLE project
    ADD COLUMN media_image_max_dimension integer NOT NULL DEFAULT 1600,
    ADD COLUMN media_image_quality       integer NOT NULL DEFAULT 80,
    ADD COLUMN media_gps_max_accuracy_m  integer NOT NULL DEFAULT 50,
    ADD CONSTRAINT project_media_image_max_dimension_check
        CHECK (media_image_max_dimension BETWEEN 320 AND 8192),
    ADD CONSTRAINT project_media_image_quality_check
        CHECK (media_image_quality BETWEEN 1 AND 100),
    ADD CONSTRAINT project_media_gps_max_accuracy_check
        CHECK (media_gps_max_accuracy_m BETWEEN 1 AND 10000);
