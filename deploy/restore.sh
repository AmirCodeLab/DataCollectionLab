#!/usr/bin/env bash
# Restore the platform database from a dump made by `backup.sh`.
#
# DESTRUCTIVE: it drops the target database first. That is the point — a
# restore that only ever runs onto an empty machine has not been rehearsed
# where it will be used.
#
# The order matters and is not obvious:
#
#   1. The `dcp_app` login role must exist BEFORE the restore, because the
#      dump carries GRANTs to it and `pg_restore` will report every one of
#      them as an error if the role is missing — and then hand you a database
#      whose policies are in place and whose application cannot connect.
#   2. Terminate connections, then drop. A single held session makes DROP
#      DATABASE fail, and on a real server that session is the API.
#   3. Restore, then verify. `--exit-on-error` so a partial restore is a
#      failure rather than a database that is almost right.
set -euo pipefail

DUMP="${1:?usage: restore.sh <dump-file> [database]}"
: "${PGHOST:=localhost}"
: "${PGPORT:=5432}"
: "${PGUSER:=dcp}"
TARGET="${2:-${PGDATABASE:-dcp}}"

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

if [ -n "${DCP_PG_CONTAINER:-}" ]; then
    psql_admin() { psql --no-password -U "$PGUSER" -d postgres "$@"; }
    psql_target() { psql --no-password -U "$PGUSER" -d "$TARGET" "$@"; }
else
    psql_admin() { psql --no-password -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d postgres "$@"; }
    psql_target() { psql --no-password -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$TARGET" "$@"; }
fi

if [ "$(psql_admin -tAc "SELECT count(*) FROM pg_roles WHERE rolname = 'dcp_app'")" != "1" ]; then
    echo "FAILED: the dcp_app role does not exist on this cluster." >&2
    echo "Run scripts/db_app_role.sql as the owner first; roles are cluster-wide" >&2
    echo "and are not in the dump. Restoring without it produces a database the" >&2
    echo "application cannot connect to." >&2
    exit 1
fi

echo "dropping and recreating ${TARGET} on ${PGHOST}:${PGPORT}"
psql_admin -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
               WHERE datname = '${TARGET}' AND pid <> pg_backend_pid()" > /dev/null
psql_admin -c "DROP DATABASE IF EXISTS ${TARGET} WITH (FORCE)"
psql_admin -c "CREATE DATABASE ${TARGET} OWNER ${PGUSER}"

echo "restoring ${DUMP}"
if [ -n "${DCP_PG_CONTAINER:-}" ]; then
    docker exec -i "$DCP_PG_CONTAINER" pg_restore --no-password --exit-on-error \
        --dbname "$TARGET" --username "$PGUSER" < "$DUMP"
else
    pg_restore --no-password --exit-on-error --dbname "$TARGET" \
        --host "$PGHOST" --port "$PGPORT" --username "$PGUSER" "$DUMP"
fi

echo "verifying"
psql_target -tAc "
    SELECT 'alembic       ' || coalesce(max(version_num), 'MISSING') FROM alembic_version
    UNION ALL SELECT 'submissions   ' || count(*)::text FROM submission
    UNION ALL SELECT 'ops           ' || count(*)::text FROM submission_op
    UNION ALL SELECT 'devices       ' || count(*)::text FROM device
    UNION ALL SELECT 'policies      ' || count(*)::text FROM pg_policies WHERE schemaname = 'public'
    UNION ALL SELECT 'forced RLS    ' || count(*)::text FROM pg_class
        WHERE relrowsecurity AND relforcerowsecurity"
echo "restored. Now make a handset sync against it — that is the half a dump cannot prove."
