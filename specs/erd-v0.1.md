# Database Schema (ERD) v0.1

**Status:** Draft — Phase 0
**DDL:** `backend/migrations/schema/001_initial.sql`
**Validated by:** `backend/tests/test_schema.py` (PostgreSQL's own parser via libpg_query)
**Depends on:** Sync Protocol v0.1, Encryption Envelope v0.1, Form IR v0.1

---

## 1. Tenancy and isolation

**Decided 7 September 2026: one shared schema, isolation by row-level
security set from the connection.** This section replaced schema-per-tenant
in its own commit, with the reason below, the way Form IR §6.2 and §10.3 were
changed — a decision, not an edit.

Two table families remain:

| Prefix | Scope | Contents |
|---|---|---|
| `platform_*` | Global | Organisations, user accounts, org membership, sessions |
| everything else | Operational, every organisation in the same tables | Projects, forms, submissions, everything operational |

**Isolation is a policy in the database, not a filter in a query.** Every
table in the schema has row-level security *enabled and forced*, with at least
one policy. Three tables carry `organization_id` and are the roots every
policy resolves through: `project` for everything operational
(`form → project`, `submission → project`, `submission_op → submission →
project`, …; a child's policy reads `project_id IN (SELECT id FROM project)`
and inherits), `platform_user` — **a user belongs to one organisation**
(pilot scope §3.1) and is as tenant-scoped as a submission — and `role`,
because a custom role is an organisation's own (pilot scope §3.5) and a
system-role table shared across tenants would be a second isolation model
living beside the first, one of which gets forgotten; the standard roles are
seeded per organisation at its creation, six rows duplicated being cheaper
than an exception to the rule. A test enforces both halves: exactly those
three carry `organization_id`, and no table lacks row-level security, FORCE,
or a policy.

**The coverage test fails closed.** It enumerates `pg_tables`; a table it
does not know with no policy is a failure, not a skip. The one exemption is
`alembic_version`, named in the test with the reason: Alembic owns it, it
holds no tenant data, and the application never reads it.

**There is one connection factory** (`app/infrastructure/database.py`), and
an AST lint in the shape of `test_form_version_has_one_writer.py` fails on
any `create_async_engine`, `asyncpg.connect` or `postgresql://` literal
outside it, naming the file and line. A second connection is a route around
every policy above — an export script with its own engine is exactly the
"one report nobody thought of" — so it is refused where it is written, not
found where it leaks. `migrations/env.py` is the named exemption: migrations
run as the owner, by design.

**Cross-organisation login is resolved before authentication, never by an
unrestricted table.** With a principal of nothing the application role can
see no user, so the login flow must know the organisation before it reads
`platform_user`: from the hostname (per-customer hostnames, as SurveyCTO
does) or from an organisation identifier in the login form, set on the
connection as `app.org_slug` so that one organisation row becomes visible and
its id becomes `app.org_id`. This deployment is single-tenant with
provisioning deliberately unbuilt, so the slug is the deployment's one
organisation; **multi-tenant provisioning has to deliver the resolution, and
nothing may be built in the meantime that reads a user without an
organisation** — an unrestricted table "temporarily" is the shape the
private-key fallback would have shipped in.

The policies read the principal from the connection:

```
app.org_id            the organisation the session belongs to
app.user_id           the person
app.scope_kind        'organization' | 'project' | 'team' — the widest live grant
app.visible_user_ids  comma-joined: the people whose work this principal may see
```

set by one layer (`app/infrastructure/database.py`) from the authenticated
session, and by nothing else. **An absent principal is no access.** A policy
compares through `coalesce(current_setting(name, true), '') <> ''` and never
through `IS NOT NULL`, because a setting that has been set once in a session
reads back as `''` for the rest of it, not NULL (probed 7 September 2026; see
§1.1). A query with no principal set returns nothing, never everything, and a
test holds that on a fresh connection and on a reused one.

**The application connects as a non-owner, non-superuser role.** A superuser
is exempt from row-level security and `FORCE` does not change that (probed:
the owner role, a superuser, read every row with FORCE on). The isolation test
asserts `NOT rolsuper` on its own connection before any other assertion; a
suite connecting as the owner would pass every isolation test whether or not
isolation worked.

### 1.1 The principal is transaction-local, never session-level

The settings above are set with `SET LOCAL` or `set_config(…, true)` inside
the request's transaction, and never at session level. This is a rule with
evidence, not a preference. Probed on 7 September 2026 through SQLAlchemy's
asyncpg pool with one connection: a principal set with `is_local => true` was
gone when the next request took the same connection (the setting read `''`,
the policy returned zero rows); a principal set at session level
(`is_local => false`) rode the connection into the next request and showed it
another person's row. There is no reset step to optimise away, because the
transaction's end is the reset; a session-level set anywhere reintroduces the
leak. `docs/phase3-item1-login-permissions.md` §5.1 has the probe in full.

### 1.2 What this replaced, and what changed the answer

v0.1 as first written chose **schema-per-tenant**: one PostgreSQL schema per
organisation, the connection's `search_path` deciding which `submission` the
word names, and tenant tables carrying no `organization_id` so that a query
which omitted a filter could not reach another customer's rows. The rationale
was sound for the requirement it had: one forgotten `WHERE organization_id`
in one report leaks another customer's data, and a schema boundary cannot be
forgotten.

**What changed is the requirement.** The ERD chose schema-per-tenant before
scope authorization was one: the pilot scope (§3.5, §4.2) requires that a
supervisor sees only their own team — their sample, their enumerators, their
submissions, their rows in an export — and that this be a *scope* a query
cannot skip, not a filter applied in the UI. A `search_path` cannot help
inside a schema; the forgotten-`WHERE` failure the original rationale named
recurs one level down, between two supervisors of the same organisation, on
the first export nobody thought of. Row-level security answers that, and once
it is there it answers the organisation boundary too, with the same
mechanism, the same connection layer, and the same test. Schema-per-tenant on
top of it would be two mechanisms for one property, the second paid for in
per-schema migrations, provisioning, and — since the runtime never actually
set a `search_path` — a table move out of `public` that was about to be
scheduled.

What the decision costs, stated: a policy is evaluated on every query, and a
child table's policy is a subselect chain to `project` (indexes on
`project_id` throughout, which the schema mostly has); and the whole property
now rests on the application role never being the owner, which the test
asserts first. It was never otherwise — a superuser could always name another
schema — so this is not new exposure, only a named one. Enterprise and
self-hosted deployments keep a dedicated database or installation
(architecture §15), which is a stronger boundary than either mechanism.

SurveyCTO provisions a whole VM per customer. Row-level security in a shared
database gives an organisation and a team the same guarantee at a fraction of
the cost, and gives it to the export as well as the screen.

## 2. Primary keys are client-generated ULIDs

Every primary key is `text` holding a ULID, generated by whichever client
creates the row — **not** by the database.

This is forced by offline-first. A device creates submissions, operations and
media while disconnected. Those rows must have identity immediately: operations
reference their submission, media references its operation, and the whole batch
uploads days later. A server-generated `bigserial` cannot provide identity to a
device that has never contacted the server.

ULIDs over UUIDv4 because they sort by creation time, which keeps index
locality reasonable on the largest tables.

A test asserts no primary key uses a serial type.

## 3. The submission model

Three tables, deliberately separate.

```
submission_op          append-only log of every operation      ← source of truth
submission_state       materialised current state (JSONB)      ← derived, rebuildable
submission_snapshot    periodic fold, to bound replay          ← derived, rebuildable
```

**`submission_op` is never updated or deleted.** It is simultaneously the sync
mechanism and the correction audit trail — the review workflow's "who changed
what, when, and why" comes from this table for free. Rewriting a row would
destroy evidence.

`submission_state` is a cache. It can be dropped and recomputed from the log at
any time. Keeping it separate means the read path for dashboards never touches
the append-only table.

Trying to make one table serve as log, current state and export source is the
obvious first design and it fails at all three.

### 3.1 Two uniqueness constraints that matter

```sql
UNIQUE (content_key_id, nonce)   -- AES-GCM nonce reuse is catastrophic
UNIQUE (device_id, counter)      -- ordering depends on counters never repeating
```

Both are cheap indexes that remove whole failure classes at the database level,
independent of client correctness. The first is the last line of defence if a
device's counter is broken; the second enforces the sync protocol's ordering
guarantee.

### 3.2 The pull cursor is a server arrival sequence

`submission_op` and `tombstone` share one sequence, `sync_stream_seq`, in a
`server_seq` column. The sync pull cursor (Sync Protocol §5) is a single
integer over both streams, so a client resumes ops and tombstones with one
number and `sync_cursor.cursor_value` stays a `bigint`.

`server_seq` answers exactly one question — *what has this client not pulled
yet*. Conflict resolution orders by `(counter, device_id)` and never by
`server_seq` or `wall_clock`; arrival order at the server carries no semantic
meaning.

Known limitation, accepted for v0.1: a transaction that commits late can make
its `server_seq` visible after a higher value has already been pulled, so a
client polling at exactly the wrong moment can miss a row until its next pull
from an earlier cursor. The push path keeps transactions short to shrink the
window; a watermark-based fix is a v0.2 question.

### 3.3 Plaintext and ciphertext side by side

`submission_op` carries both `value` (jsonb) and `value_ciphertext` (bytea),
with a check constraint that exactly one is populated along with its key and
nonce.

This is not indecision. A project in `field_level` mode encrypts only fields
marked sensitive, so a single submission legitimately contains both encrypted
and plaintext operations.

## 4. Forms are immutable once published

`form_version` rows are never updated. Editing a form creates a new version with
a new `ir_checksum`. `form_deployment` maps a version into an environment.

Every submission references a `form_version_id`, never a `form_id` alone. A
submission is always re-validated against the exact version it was collected
under — never the latest. Without this, changing a constraint retroactively
invalidates historical data.

## 5. Case and Visit are separate tables

A `case_record` is a unit of assigned work. A `visit` is one collection event
against it. A case has many visits.

Collapsing these into one row is the shortcut that makes longitudinal studies
and repeat inspections impossible later. Round 2 of a panel survey is a second
visit against the same case, linked to the same entity, with its own submission.

## 6. Media has no foreign key to `submission_op`

`media.op_id` is a plain text column, deliberately not a foreign key.

An operation referencing a media file is accepted before the file has finished
uploading — that is what makes resumable media upload possible on a bad network.
A foreign key would reject valid operations whose media has not arrived yet.

A test enforces the absence of this constraint so nobody "fixes" it later.

## 7. Tombstones

Deletion is a fact to be propagated, not an absence to be inferred. The
`tombstone` table carries deletions of submissions, repeat instances, cases,
entities and media, with `expires_at` for the retention window (minimum 90 days
per the sync spec).

Without tombstones, a device that was offline during a deletion resurrects the
deleted record on its next sync.

## 8. Transactional outbox

`outbox_event` is written in the same transaction as the state change that
produced it, then published by a worker. This gives exactly-once semantics
without a message broker.

Kafka or NATS remain deferred until volume or organisational boundaries justify
them. A partial index on unpublished rows keeps the poll query cheap.

## 9. Geography

PostGIS `geography(Point, 4326)` on `entity` and `case_record`, for geofence
validation, spatial case assignment and distance-based fraud heuristics
(impossible travel speed between submissions).

`geography` rather than `geometry` because the queries are real-world distances
across potentially large areas, and correctness matters more than the
performance difference at our scale.

## 10. What is NOT in v0.1

Deliberate omissions, so their absence is not mistaken for oversight:

| Omitted | Why | When |
|---|---|---|
| Partitioning on `submission_op` | Needs real volume data to partition sensibly | When a project exceeds ~10M ops |
| Materialised views for analytics | Parquet + DuckDB is the plan, not in-database views | V1 |
| Full-text search indexes | Postgres FTS added when the record browser is built | Phase 1 |
| Workforce tables (attendance, incentives) | Module is V1.5 | V1.5 |
| Dataset-to-form attachment mapping | Needs the dataset sync design first | Phase 1 |
| Row-level security policies | Schema isolation covers the tenant boundary; RLS would cover intra-tenant roles | V1 |

## 11. Validation

`backend/tests/test_schema.py` parses the DDL with **PostgreSQL's own grammar**
(libpg_query via pglast) and asserts:

- the file is valid PostgreSQL
- every foreign key points at a table that exists
- every table has a primary key
- no primary key uses a serial type
- the nonce and counter uniqueness constraints exist
- `submission_op` has both value columns plus the all-or-nothing check
- `media` hashes ciphertext, not plaintext
- key sizes match X25519 and AES-GCM
- no tenant table carries `organization_id`
- `media` has no foreign key to `submission_op`

Verified by deliberately breaking two things — removing the nonce constraint and
pointing a foreign key at a non-existent table — and confirming both fail.

## 12. Open questions

- Whether `submission_state.data` should be encrypted in `project_e2e` mode, or omitted entirely (currently it would be unpopulated, since the server cannot fold encrypted ops)
- Retention policy mechanics: hard delete versus tombstone-and-purge
- Whether `entity.attributes` needs a JSONB schema constraint or stays free-form
- Index strategy for the record browser once query patterns are known
