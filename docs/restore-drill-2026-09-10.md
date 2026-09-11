# Restore drill, 10 September 2026

A dump is not a backup until it has been read back, and a restored database is
not a restored system until a handset can sync into it. This is the record of
both being done, with a database that had real rows in it, using the scripts
in `deploy/` rather than commands typed for the occasion.

Written because `deploy/` had held one empty `.gitkeep` since the initial
commit while the README described it as "Docker Compose and deployment
tooling", and because the alternative to doing this is finding out during
fieldwork.

---

## What was in the database

The development database after Phase 3's six items and their runs — not a
fixture, the real accumulated state of five end-to-end walks:

| | |
|---|---|
| `alembic_version` | 0016 |
| Organisations / people / projects | 1 / 8 / 1 |
| Submissions | 16 |
| Ops | 48 |
| Devices | 24 |
| Quality flags / reviews | 1 / 1 |
| Row-level security policies | 53 |
| Tables with RLS forced | 47 |

Encrypted answers: none. This project is in `standard` mode, so what follows
proves nothing about restoring a `project_e2e` database — and there is nothing
extra to prove, because the server holds no key either way. See
`docs/key-custody.md`.

## What was run

```bash
export DCP_PG_CONTAINER=datacollectionlab-postgres-1
./deploy/backup.sh backups/
./deploy/restore.sh backups/dcp-20260910T153302Z.dump
```

The dump is 208 KB, custom format, 490 entries in its table of contents.
`backup.sh` reads the table of contents back before reporting success, so a
file `pg_restore` cannot open is a failure at the moment it is written rather
than at the moment it is needed.

`restore.sh` terminated the open connections, dropped the database, recreated
it and restored. **The API was stopped first** — a held session makes
`DROP DATABASE` fail, and on a real server that session is the API.

## What came back

```
alembic       0016
submissions   16
ops           48
devices       24
policies      53
forced RLS    47
```

Every count matches. Three things beyond the counts were checked, because
each is a way a restore can look right and not be:

**The grants survived.** `dcp_app` still holds `SELECT, INSERT, UPDATE,
DELETE` on `submission`. This is the one that would have been silent: the
policies would all be in place and the application simply could not connect.

**The policies still bite.** Querying `platform_organization` as `dcp_app`
with no principal set returns **0 rows** — not an error, and not the row. That
zero is row-level security working, and it is what the restored database
should say.

**The sequence came back at the right value.** `sync_stream_seq.last_value` is
48 and the highest `server_seq` in `submission_op` is 48. A sequence restored
behind its data would give the next op a `server_seq` a device has already
pulled past, and that op would never reach anybody — silently, and only for the
work collected right after the restore.

## Then a handset

The half a dump cannot prove.

**Signed in already, synced against the pre-restore database.** Tapped Sync
work: *"All changes synced. Last sync 2026-09-10 10:43."* The cursor it holds
is still valid, because a restore returns the same rows with the same
`server_seq` values — which is exactly the difference between a **restore** and
a **rebuild**. Defect 21 is about the rebuild case, where the new database has
never issued the cursor the device sends and the device reports success while
pulling nothing. A restore does not meet that defect. A reseeded database does,
and the runbook below says so.

**Then new work, to prove the database is writable and the sequence is sound.**
A new Household Survey with `enumerator_name` = "After the restore", saved and
synced:

| | before | after |
|---|---|---|
| Submissions | 16 | 17 |
| Highest `server_seq` | 48 | 49 |

The new answer is in `submission_state`. The restored database accepted work
from a device that had synced with its predecessor, and numbered it correctly.

## What did not work the first time

**`pg_dump` is not on this machine.** Only the container has a Postgres client.
The first version of `backup.sh` assumed one on `PATH` and would have meant
running the drill with commands other than the ones committed — which defeats
the drill. Both scripts now take `DCP_PG_CONTAINER` and route through
`docker exec`, and say in their headers why.

That is the only thing that failed, and it failed in the tooling rather than in
the restore.

## The runbook, from this drill

1. **Stop the API.** `DROP DATABASE` fails on a held connection.
2. **Check the `dcp_app` role exists** on the target cluster. Roles are
   cluster-wide and are not in the dump. `restore.sh` refuses without it,
   because restoring first would produce a database whose policies are perfect
   and whose application cannot log in. On a fresh cluster run
   `scripts/db_app_role.sql` as the owner first.
3. **Restore, verify, start the API.**
4. **Sync one handset before telling anybody it is done.** If it says "All
   changes synced" and pulled nothing, check whether this was a restore or a
   rebuild — see below.
5. **After a *rebuild* rather than a restore** — a reseeded or recreated
   database — every device that synced with the old one is stranded and must
   have its app data cleared. That is defect 21 and it has no fix today.

## What this drill did not cover

- **The object store.** Media is in MinIO/S3 and is backed up there. A
  submission's answers came back; its photographs were not part of this.
- **A restore onto a different machine or a fresh cluster.** Same database
  server throughout. The `dcp_app` role check in `restore.sh` is the part that
  would matter there and it was not exercised.
- **Point-in-time recovery.** This is a full dump and a full restore. Anything
  collected between the dump and the failure is lost, and at pilot scale the
  answer to that is how often the dump runs.
- **A `project_e2e` database.** No encrypted answers were in it.
