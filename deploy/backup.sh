#!/usr/bin/env bash
# Back up the platform database.
#
# A dump is not a backup until it has been read back. `restore.sh` is the other
# half and `docs/restore-drill-2026-09-10.md` is the record of the two being
# run against a database with real rows in it.
#
# What this dumps and what it does not:
#
#   * The database, whole, in PostgreSQL's custom format — schema, data,
#     ownership and the GRANTs the policies rest on. `pg_restore` needs the
#     custom format to restore selectively and to parallelise.
#   * NOT the `dcp_app` login role. Roles live in the cluster, not the
#     database, so a restore onto a fresh cluster needs
#     `scripts/db_app_role.sql` run first. The restore script checks.
#   * NOT the object store. Media lives in S3/MinIO and is backed up there;
#     a submission's answers are in Postgres and its photographs are not.
#   * NOT any private key. There has never been one on the server to dump —
#     see docs/key-custody.md, which is the half of this that is a procedure.
set -euo pipefail

: "${PGHOST:=localhost}"
: "${PGPORT:=5432}"
: "${PGUSER:=dcp}"
: "${PGDATABASE:=dcp}"
OUT_DIR="${1:-backups}"

# The Postgres client tools, wherever they are. On a server they are on PATH.
# On a machine that only has the compose stack they are inside the container,
# and refusing to run there would mean this drill was rehearsed with commands
# other than the ones committed — which is the failure the drill exists to
# avoid. Set DCP_PG_CONTAINER to route through `docker exec`.
if [ -n "${DCP_PG_CONTAINER:-}" ]; then
    pg_dump()    { docker exec -i "$DCP_PG_CONTAINER" pg_dump "$@"; }
    pg_restore() { docker exec -i "$DCP_PG_CONTAINER" pg_restore "$@"; }
    psql()       { docker exec -i "$DCP_PG_CONTAINER" psql "$@"; }
elif ! command -v pg_dump > /dev/null; then
    echo "No pg_dump on PATH. Install the PostgreSQL 16 client, or set" >&2
    echo "DCP_PG_CONTAINER to the name of the running postgres container." >&2
    exit 1
fi

mkdir -p "$OUT_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$OUT_DIR/${PGDATABASE}-${STAMP}.dump"

echo "dumping ${PGUSER}@${PGHOST}:${PGPORT}/${PGDATABASE} -> ${OUT}"
if [ -n "${DCP_PG_CONTAINER:-}" ]; then
    # --file inside the container would write inside the container. Stream it.
    docker exec -i "$DCP_PG_CONTAINER" pg_dump --format=custom --no-password \
        --username "$PGUSER" "$PGDATABASE" > "$OUT"
else
    pg_dump --format=custom --no-password --file "$OUT" \
        --host "$PGHOST" --port "$PGPORT" --username "$PGUSER" "$PGDATABASE"
fi

# Read the table of contents back. A dump that pg_restore cannot list is a
# file, not a backup, and finding that out now costs one second.
if ! pg_restore --list < "$OUT" > "$OUT.toc" 2>/dev/null; then
    echo "FAILED: pg_restore cannot read ${OUT}" >&2
    exit 1
fi

echo "wrote $(du -h "$OUT" | cut -f1) to ${OUT}"
echo "$(grep -c . "$OUT.toc") entries in the table of contents"
