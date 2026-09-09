-- 013: the columns a sample's composite key was composed from (A4).
--
-- A sample is published against a key composed from several columns under
-- Form IR §3.1's escaping rule, and an export that wants to split the key
-- back needs to know which columns, in which order. Recorded on the dataset,
-- once, by the upload that composed it. NULL for a dataset published against
-- a single column of its own (every dataset before item 2).

ALTER TABLE dataset ADD COLUMN key_columns text[];
