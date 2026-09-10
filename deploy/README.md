# deploy

What it takes to run this somewhere that is not a laptop.

This directory was an empty `.gitkeep` from the initial commit until
10 September 2026, while the repository README described it as "Docker Compose
and deployment tooling". It now holds the two things that were actually needed
first, and they are here because they were **used**, not because they were
written.

| | |
|---|---|
| `backup.sh` | Dump the platform database, and read the dump's table of contents back before calling it a backup |
| `restore.sh` | Drop, recreate and restore. Destructive on purpose — a restore only ever rehearsed onto an empty machine has not been rehearsed |

Both take `DCP_PG_CONTAINER` to route through `docker exec` when the Postgres
client is only inside the container.

**The drill is `docs/restore-drill-2026-09-10.md`** — a database with sixteen
submissions in it, dumped, destroyed, restored, and then synced into from a
handset that had synced with its predecessor. Read the runbook at the end of it
before running `restore.sh` in anger. Two things in it are not obvious: the
`dcp_app` login role is cluster-wide and is not in the dump, and a *rebuild* is
not a *restore* — after a rebuild every device that synced with the old
database is stranded (defect 21).

## What is not here yet

Named so the absence is a decision rather than an oversight, and all of it is
gate 1 in `docs/gate1-provisioning.md`:

- **A production compose file.** `docker-compose.yml` at the repository root is
  the development stack: Postgres with the password `dcp`, no TLS, ports bound
  to the host.
- **TLS, DNS, and where the server runs.** An operator's decision, not this
  repository's.
- **Provisioning.** There is still no way to create an organisation outside
  `scripts/seed_dev.py`, which refuses to run outside development. That is what
  gate 1 builds.
- **A schedule.** `backup.sh` is a script, not a cron job. What runs it, how
  often, and where the dumps go is a hosting decision that depends on the
  answers above.

## Key custody is not in here

It is `docs/key-custody.md`, and it is a procedure rather than tooling: the
server never holds a project's private key, so no backup of the server contains
one and no restore recovers one. Read it before creating a project in an
encrypting mode.
