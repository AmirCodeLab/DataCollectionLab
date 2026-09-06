#!/usr/bin/env bash
#
# Does a dataset version's published row order survive to a device?
#
# Form IR §2.3's `rowSource` creates one repeat instance per dataset row, so the
# order an enumerator reads a household in is the order the sample lists it in.
# §3.1 does not yet promise that order, and this script is why.
#
# It runs the device's own schema — `shared/core/.../db/datasets.sq`, the table
# definitions and the two write paths copied verbatim — against plain SQLite,
# and prints the order a device would read after a first sync and after one
# delta. Plain SQLite rather than the app because the behaviour under test is
# SQLite's, not Kotlin's: which rowids `INSERT ... SELECT` and
# `INSERT OR REPLACE` assign.
#
# The fixture publishes a household head-first, so published order and key order
# are deliberately DIFFERENT. That is the whole design of it: the guard that
# already exists on the server side
# (`test_rows_page_resumes_from_its_cursor_and_says_when_it_is_done`) publishes
# V000…V249, where the two coincide — so it would pass against a store that
# sorted by key, and it is not evidence about this.
#
# Prints PASS/FAIL per stage and exits non-zero if any stage lost the order.
# Expected to FAIL until docs/known-defects.md 16 is closed. Run it after.

set -euo pipefail

command -v sqlite3 >/dev/null || { echo "sqlite3 not found"; exit 2; }

published="m3 m1 m2 m4"   # the sample's own order: head of household first

read_order() {  # $1 = version id
    sqlite3 "$db" \
        "SELECT group_concat(record_key, ' ') FROM (
             SELECT record_key FROM dataset_row
             WHERE dataset_version_id = '$1' ORDER BY rowid);"
}

db=$(mktemp -t dcp_row_order)
trap 'rm -f "$db"' EXIT

sqlite3 "$db" <<'SQL'
-- shared/core/src/commonMain/sqldelight/com/dcp/core/db/datasets.sq, verbatim.
CREATE TABLE dataset_row (
    dataset_version_id TEXT NOT NULL,
    record_key TEXT NOT NULL,
    data_json TEXT NOT NULL,
    PRIMARY KEY (dataset_version_id, record_key)
);
SQL

# --- Stage 1: first sync. `appendRows` inserts each page in the order the
# server sent it, and the server sends `ORDER BY dataset_record.ordinal`.
for key in $published; do
    sqlite3 "$db" "INSERT OR REPLACE INTO dataset_row VALUES ('v1','$key','{}');"
done

after_sync=$(read_order v1)

# --- Stage 2: `applyDelta(seed = true)` — `copyRowsToVersion`, no ORDER BY.
sqlite3 "$db" "INSERT OR REPLACE INTO dataset_row(dataset_version_id, record_key, data_json)
               SELECT 'v2', record_key, data_json FROM dataset_row
               WHERE dataset_version_id = 'v1';"
after_seed=$(read_order v2)

# --- Stage 3: the delta's one changed row — `insertRow`, INSERT OR REPLACE.
# Read the order after each stage rather than at the end: the two losses are
# independent, and one masks the other if both have run.
sqlite3 "$db" "INSERT OR REPLACE INTO dataset_row VALUES ('v2','m1','{\"n\":\"changed\"}');"
after_change=$(read_order v2)

status=0
check() {  # $1 = stage name, $2 = the order read at that stage
    local got=$2
    if [ "$got" = "$published" ]; then
        printf 'PASS  %-28s %s\n' "$1" "$got"
    else
        printf 'FAIL  %-28s %s   (published: %s)\n' "$1" "$got" "$published"
        status=1
    fi
}

echo "The device reads with ORDER BY r.rowid — datasets.sq, all three read queries."
echo
check "after first sync"        "$after_sync"
check "after the delta's seed"  "$after_seed"
check "after one changed row"   "$after_change"

echo
if [ "$status" -ne 0 ]; then
    echo "Published order lost. Form IR §2.3 'Order', docs/known-defects.md 16."
fi
exit "$status"
