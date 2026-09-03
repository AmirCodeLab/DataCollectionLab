-- Dataset rows keep the order they were published in (Form IR §3.2).
--
-- `dataset_record.id` is a ULID and ULIDs generated in a loop are not in
-- insertion order — the timestamp is shared and the random tail is not. Paging
-- a version by id is therefore stable and *scrambled*: a device receives 38,000
-- villages in an order nobody chose, and an enumerator scrolls a list whose
-- author sorted it carefully.
--
-- The CSV's own order is the order the list is offered in, so it has to be a
-- column rather than an accident of the key. It doubles as the paging cursor:
-- an integer within an immutable version, which is a cheaper and more obvious
-- thing to resume from than a ULID.

ALTER TABLE dataset_record ADD COLUMN ordinal INTEGER NOT NULL DEFAULT 0;

-- The paging walk: one version, in publication order. Covers the cursor
-- comparison and the ordering together, so a page is an index range rather
-- than a sort.
CREATE UNIQUE INDEX dataset_record_ordinal_idx
    ON dataset_record (dataset_version_id, ordinal);
