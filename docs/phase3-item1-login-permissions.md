# Item 1 — login and permissions: the schema, before the code

**Status:** the schema (§2, §4, §7) and the connection layer (§2.3, §2.4) are
implemented and merged — 9 September 2026, PRs #40 and the one after it; §3
(sessions from a cookie) and §5's per-person scope are not yet. The document
is kept as written, as the decision record. The decisions it rests on are the ones in
`docs/phase3-pilot-scope.md` §3 from the design session plus the three below;
what this document adds is the DDL those decisions become, what in the
current schema and runtime has to move for them, and the questions the DDL
was written under assumptions for. Read §3 first; this does not restate it.

The shape is the one §11.3 of the Form IR took: decide the model in a
document, then write the migration as its transcription
(`migrations/schema/008_identity.sql`, NORMATIVE, with the Alembic file
transcribing it and `test_migrations.py` holding the two together).

## 0. The three answers, and what each changes

| Answer | What it changes here |
|---|---|
| **Tenancy first — the mechanism, not the provisioning.** The organisation resolved from the authenticated session, never a constant; a test proving a query cannot reach another organisation's rows; one organisation, no onboarding | §2: **one shared schema, row-level security from the connection** — ERD §1 as decided in PR #39, which replaced schema-per-tenant. No table move, no `search_path`, no per-schema migrations. The isolation test needs a second organisation *row* in the test database, and a fixture row is not provisioning — §2.4 says how |
| **HttpOnly, SameSite=Strict cookies, console and app alike.** A token in browser storage is the shape the private-key test exists to refuse | §3: `platform_session` holds a hash of an opaque token; the token lives in the cookie and nowhere the page can read. The KMP client can carry cookies — §3.3 says what is ours to write |
| **Device registration goes through the same approval gate.** A device may register but cannot push until bound to an active user | §4: `device.user_id` becomes nullable and a foreign key, binding happens at login, and push requires the session that binding created. The `dev_` hole closes because an unbound device has nothing to present |

And one question the answers put in front of the schema — *what would pass
every test?* — has its own section, §5, because the honest answer is a
permission check in the API layer, which passes every screen test and fails
the first export.

**Revised again the same evening**, after the answer that tenancy and scope
are one mechanism asked twice — set something on the connection, let the
database enforce it — with three things to hold to: FORCE on every table and
a test for it; the pool-return evidence in the spec, not only the register;
and a test that enumerates every table so a later migration cannot add an
open one. §5 is rewritten around the three probes that were run to write it.

**Fourth pass**, after reading ERD §1 against what §5 had chosen: the two
disagreed — schema-per-tenant in the spec, row-level security here — and two
documents disagreeing is not defensible. The decision is PR #39, ERD §1, in
its own commit with the reason: the ERD chose schema-per-tenant before scope
authorization was a requirement, and RLS is the mechanism that answers both.
§2 below is rewritten to it; the table move, the `search_path` layer and the
scratch schema are gone.

**Fifth pass**, four answers: users are tenant-scoped (`platform_user.organization_id`,
the same policy as everything else); roles too, seeded per organisation;
the coverage test fails closed with `alembic_version` the one named
exemption; a second connection is forbidden by an AST lint. And no bootstrap
escape for login: the organisation is resolved before authentication, from
the hostname or the login form, which for this single-tenant deployment is
its one organisation. The `SECURITY DEFINER` function of the fourth pass is
gone — it was the escape.

## 1. What exists today, plainly

| | Today |
|---|---|
| Authentication | **None, on any route.** Every handler takes a database session and nothing else (`app/api/v1/*`, `app/api/deps.py`) |
| The console | No login page, no session, no principal. `/forms/{id}` edits, publishes and deploys for whoever opens it |
| The handset | Registers a device (`POST /devices`, sync §4) and is attached to the deployment's single project. Its ops carry `actorId = "usr_local"` (`CoreFactory.kt`); the server files the device under `user_id = "usr_unassigned"` (`projects/service.py`). **Anything that knows a device id can push as it** |
| `platform_user` | Exists, `email NOT NULL UNIQUE`, `password_hash`, `mfa_secret`, status active / invited / suspended / deactivated. **No row has ever been written** |
| `platform_org_membership`, `project_member`, `team` | Exist, never written. `project_member.user_id` is text with no foreign key |
| Who-did-what columns | `submission.created_by`, `submission_op.actor_id`, `form_version.published_by`, `form_deployment.deployed_by`, `form_draft.updated_by`, `assignment.assigned_by`, `audit_event.actor_id`, `device.user_id` — all `text`, none a foreign key, all null or a placeholder |
| Tenancy | Until PR #39 the ERD said schema-per-tenant and `test_tenant_tables_have_no_organization_id_column` enforced the column half; **at runtime there was always one schema** — the seed writes `schema_name = "public"`, the engine sets no `search_path`. ERD §1 now says one schema with row-level security, which is what the runtime already is, minus the security |
| The database role | `dcp`, from `docker-compose.yml`, is the database's owner and a superuser. That matters in §5: a superuser is exempt from row-level security, so a test suite that connects as one cannot see whether isolation works |

## 2. Tenancy: the mechanism

### 2.1 One schema, one discriminator, policies everywhere

ERD §1 (PR #39): every organisation's operational rows live in the same
tables; `project.organization_id` is the one column that names an
organisation; every other operational table resolves its organisation through
its project; every table has row-level security enabled and forced with at
least one policy; the policies read a principal the connection layer sets
per transaction. Tenancy and scope are the same mechanism asked twice.

### 2.2 The DDL

```sql
-- The one discriminator. NOT NULL after the backfill: every project belongs
-- to an organisation, and the seed's organisation is the only one there is.
ALTER TABLE project ADD COLUMN organization_id text
    REFERENCES platform_organization (id) ON DELETE RESTRICT;
UPDATE project SET organization_id = (SELECT id FROM platform_organization ORDER BY created_at LIMIT 1);
ALTER TABLE project ALTER COLUMN organization_id SET NOT NULL;
CREATE INDEX project_organization_idx ON project (organization_id);
-- platform_organization.schema_name is no longer meaningful; dropped.
ALTER TABLE platform_organization DROP COLUMN schema_name;

-- The application's role. Not the owner, not a superuser: the owner runs
-- migrations; the application reads and writes, and is subject to every
-- policy below (§5.2 — a superuser is exempt from all of them, and the
-- owner is one).
CREATE ROLE dcp_app LOGIN PASSWORD :'app_password';
GRANT USAGE ON SCHEMA public TO dcp_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO dcp_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO dcp_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO dcp_app;

-- Row-level security on EVERY table, enabled and forced. The migration
-- enumerates pg_class rather than listing names, and
-- tests/test_every_table_is_forced.py holds the result — a table added by a
-- later migration with no policy is red in CI. The test fails closed: an
-- unknown table with no policy is a failure, not a skip. `alembic_version`
-- is the one exemption, named in the test: Alembic owns it, it holds no
-- tenant data, the application never reads it.
--
-- Three policy shapes, and every table carries exactly one of them:
--
-- (a) platform tables: the organisation. A user belongs to one organisation
--     (§3.1) and carries it directly — as tenant-scoped as a submission.
ALTER TABLE platform_user ADD COLUMN organization_id text
    REFERENCES platform_organization (id) ON DELETE RESTRICT;
-- (backfilled to the one organisation, then NOT NULL; and UNIQUE (organization_id, id)
--  so the membership below can reference the pair and never disagree with it)
ALTER TABLE platform_org_membership
    ADD CONSTRAINT platform_org_membership_same_org_fk
    FOREIGN KEY (organization_id, user_id) REFERENCES platform_user (organization_id, id);

CREATE POLICY org ON platform_organization
    -- Visible by id once the principal is set, or by slug while the login
    -- route is resolving it (§2.3) — the one row, either way.
    USING (id = coalesce(current_setting('app.org_id', true), '')
           OR slug = coalesce(current_setting('app.org_slug', true), ''));
CREATE POLICY org ON platform_user
    USING (organization_id = coalesce(current_setting('app.org_id', true), ''));
CREATE POLICY org ON platform_org_membership
    USING (organization_id = coalesce(current_setting('app.org_id', true), ''));
CREATE POLICY own ON platform_session
    USING (user_id = coalesce(current_setting('app.user_id', true), ''));

-- (b) project, the root: the organisation.
CREATE POLICY org ON project
    USING (organization_id = coalesce(current_setting('app.org_id', true), ''));

-- (c) everything under a project: inherits (b) through the subselect. This
--     is the default for a table nothing scopes more finely.
CREATE POLICY org ON form
    USING (project_id IN (SELECT id FROM project));
-- … and the same on environment, team, project_member, device, project_key,
--     form_draft, dataset, case_record, quality_rule, workflow_definition,
--     audit_event*, outbox_event*, sync_cursor (through device).
--     Tables two steps down chain once more:
CREATE POLICY org ON form_version
    USING (form_id IN (SELECT id FROM form));
--     (form_deployment, form_version_dataset, dataset_version, dataset_record,
--      assignment, visit, submission_*, media*, quality_flag, review,
--      workflow_instance, workflow_transition, tombstone, entity*)
--
--   * audit_event and outbox_event carry no project today; they gain
--     project_id in this migration (nullable, null = platform-level), and
--     a platform-level row is visible to organisation scope only.

-- Then, on the tables §5 scopes within an organisation, the scoped policy
-- REPLACES (c) — a row must satisfy both the organisation and the scope:
CREATE POLICY scope ON submission
    USING (project_id IN (SELECT id FROM project)
           AND (created_by = ANY (string_to_array(current_setting('app.visible_user_ids', true), ','))
                OR current_setting('app.scope_kind', true) = 'organization'));

-- And on every table, enabled and forced:
ALTER TABLE submission ENABLE ROW LEVEL SECURITY;
ALTER TABLE submission FORCE ROW LEVEL SECURITY;
-- … (every table; enumerated by the migration)
```

Policies are `USING` — read and write alike, so an insert into another
organisation's project is refused as an update of it would be. Every
comparison goes through `coalesce(…, '')` for the reason §5.2 records.

### 2.3 The connection layer

One place, `app/infrastructure/database.py`, the only place a session is
handed out (the conventions already say so):

```
request ──► session cookie ──► platform_session ──► user ──► org membership
                                                            │
                          SET LOCAL app.org_id           = …
                          SET LOCAL app.user_id          = …
                          SET LOCAL app.scope_kind       = …   (§5)
                          SET LOCAL app.visible_user_ids = …
```

`SET LOCAL`, inside the request's transaction, so a pooled connection carries
nothing to the next request (§5.1, the pool probe). The organisation is read
from the session, never from a constant; the seed's `schema_name = "public"`
goes with the column. A request with no session sets nothing, and a policy
that reads nothing admits nothing.

**Login resolves the organisation before it reads a user.** With a principal
of nothing the app role can see no `platform_user` row, and the answer is not
an unrestricted read — it is that the login request already knows which
organisation it is for. The connection layer sets `app.org_slug` from the
request's hostname (per-customer hostnames, the SurveyCTO shape) or from an
organisation identifier in the login form; the `platform_organization`
policy admits that one row by slug; its id becomes `app.org_id`; and the
user row is now visible under the ordinary policy. For this deployment —
single-tenant, provisioning deliberately unbuilt — the slug is the
deployment's one organisation, configured. **Multi-tenant provisioning has to
deliver the resolution** (ERD §1 records the constraint), and nothing is built
meanwhile that reads a user without an organisation.

**One connection factory, and a lint.** `tests/test_one_connection_factory.py`,
in the shape of `test_form_version_has_one_writer.py`: any
`create_async_engine`, `asyncpg.connect` or `postgresql://` literal in `app/`
or `scripts/` outside `app/infrastructure/database.py` fails, naming the file
and line. `migrations/env.py` is the named exemption (migrations run as the
owner). Two scripts fail it today — `scripts/export_submissions.py` and
`scripts/measure_export.py` each build their own engine — and that is the
finding, not a nuisance: an export with its own connection is the one report
nobody thought of, the exact shape §5 is about. They move onto the factory
with a principal in this item.

Migrations: unchanged. One schema, one version table, `migrations/env.py` as
it is. The two things that were about to be scheduled — a table move and a
per-schema migration loop — are not.

### 2.4 The test, and the second organisation it needs

`tests/test_tenant_isolation.py`, marked `db`:

1. The migrated database has the seed's organisation and project. The test
   inserts, **as the owner**, a second `platform_organization` row and a
   project under it. That is a fixture row, not provisioning: nothing creates
   it in the product, nothing can log into it, and the test deletes it.
2. A submission is inserted under each project, as the owner.
3. A session resolved to the seed organisation runs `select(Submission)` with
   **no filter**, as `dcp_app`. It sees its row and not the other. Resolved to
   the fixture organisation — by setting the principal directly, since no
   session can — it sees the reverse.
4. With **no principal**, on a fresh connection and on one that has carried a
   principal in an earlier transaction, `select(Submission)` returns **zero
   rows**, never everything — your break, run for real when the test exists.
5. The connection's role is asserted to be `dcp_app` and `NOT rolsuper`
   *before* step 3, so the test cannot pass by running as the owner.

The break: set the principal at session level in the connection layer, or
drop `FORCE` from `submission`. Step 3 fails.

## 3. Sessions: a cookie, a row, and nothing in the page

### 3.1 The DDL

```sql
CREATE TABLE platform_session (
    id                 text PRIMARY KEY,
    user_id            text NOT NULL REFERENCES platform_user (id) ON DELETE CASCADE,
    -- 'console' or 'app'. An app session names its device (§4) and a console
    -- session never does.
    kind               text NOT NULL,
    device_id          text,          -- FK added in §4
    -- The cookie carries an opaque random token; only its hash is stored, so
    -- a copy of this table logs nobody in.
    token_hash         text NOT NULL UNIQUE,
    created_at         timestamptz NOT NULL DEFAULT now(),
    last_used_at       timestamptz,
    expires_at         timestamptz NOT NULL,
    revoked_at         timestamptz,
    revoked_reason     text,
    CONSTRAINT platform_session_kind_check CHECK (kind IN ('console', 'app')),
    CONSTRAINT platform_session_device_check
        CHECK ((kind = 'app') = (device_id IS NOT NULL))
);
```

One table for both clients because revocation is one operation (architecture
§14: device and session revocation): revoking a device revokes its sessions,
deactivating a user revokes all of theirs, and a supervisor's "log that phone
out" is a row update.

### 3.2 The cookie

`Set-Cookie: dcp_session=<token>; HttpOnly; Secure; SameSite=Strict; Path=/api`.
No access token, no refresh token, no JavaScript-readable value: the session
row *is* the token's state, `last_used_at` slides the expiry, and a revoked
row refuses the next request. The private-key test's rule holds — the
console's tests already wrap `localStorage`, `sessionStorage`, IndexedDB and
every request; the login page's test asserts the token appears in none of
them and that the response's cookie carries `HttpOnly`.

Same origin: the console is served beside the API (Vite's proxy in
development, the same origin in a self-hosted install — `web/src/api/client.ts`
says so), so `SameSite=Strict` costs nothing and closes cross-site requests
without a CSRF token.

### 3.3 The KMP client, honestly

Ktor's client carries cookies (`HttpCookies` plugin) and its built-in storage
is **in memory** — a restart forgets the session. What is ours to write is a
`CookiesStorage` backed by the keystore-encrypted local database, one class,
and the app already has the store (`SubmissionStore`, SQLCipher, Keystore).
`SameSite` means nothing to a native client — there is no site — and the
cookie is simply carried back to the host that set it. The emulator talks to
`10.0.2.2:8000` directly and that is the host it is scoped to.

So: cookies work for the app, the persistence is small and ours, and there is
no reason to start from a header. If the persistent storage turns out to fight
Ktor's cookie plugin on some platform, that is the moment to decide, not now.

## 4. Devices: registered is not bound

```sql
ALTER TABLE device
    ALTER COLUMN user_id DROP NOT NULL,
    ADD COLUMN bound_at timestamptz,
    ADD CONSTRAINT device_user_fk
        FOREIGN KEY (user_id) REFERENCES platform_user (id) ON DELETE RESTRICT,
    ADD CONSTRAINT device_bound_check
        CHECK ((user_id IS NULL) = (bound_at IS NULL));
-- Existing rows hold 'usr_unassigned'; the migration sets them to NULL first.

ALTER TABLE platform_session
    ADD CONSTRAINT platform_session_device_fk
        FOREIGN KEY (device_id) REFERENCES device (id) ON DELETE CASCADE;
```

The flow, and why the gate falls out of the model rather than being a rule:

1. `POST /devices` stays unauthenticated and idempotent (sync §4). It creates
   a row that can do nothing.
2. `POST /auth/login { username, password, deviceId }` from the app. The
   membership must be `active` — `pending_approval` and `deactivated` are
   refused with that reason as the contract, the way `RegisterFailure` works
   today. Success sets `device.user_id`, `bound_at`, and creates an `app`
   session naming the device.
3. `POST /sync/push` and `GET /sync/pull` require an app session whose
   `device_id` equals the request's `deviceId`. A device that registered and
   never bound has no session; a session for another device does not match.
   The op's `actorId` becomes the session's user, and the server refuses an
   op whose `actorId` is not that user.

No second rule: the same `status = 'active'` that lets a person log in is the
one that lets their device push, because pushing *is* their session.

`platform_session.device_id` references an operational table from a platform
one; a session belongs to the platform, a device to the organisation, and a
session for a device the organisation no longer has goes with it.

## 5. What would pass every test

The question asked, answered before the DDL rather than after the first
export.

A permission check in the API layer — `require("submission.view")`, and a
`WHERE` in each service that lists — passes every screen test, because every
screen calls a service that filters. It fails the first report or export that
queries the table directly, and nobody notices, because the screens are all
correct. The pilot scope §4.2's sentence — "a filter can be forgotten in one
query; a scope cannot" — is true only if the scope is somewhere a query
cannot skip. That place is the database, and it is the same place tenancy
already lives: one mechanism, asked twice. Set the principal on the
connection; let row-level security enforce it.

```sql
-- The principal, as the connection sees it. Set by the connection layer, per
-- transaction, from the session (§5.2 says how); absent when there is none.
--   app.user_id           the person
--   app.scope_kind        'organization' | 'project' | 'team' — the widest live grant
--   app.visible_user_ids  comma-joined: the people whose work this principal may see

ALTER TABLE submission ENABLE ROW LEVEL SECURITY;
ALTER TABLE submission FORCE ROW LEVEL SECURITY;
CREATE POLICY scope ON submission
    USING (created_by = ANY (string_to_array(current_setting('app.visible_user_ids', true), ','))
           OR current_setting('app.scope_kind', true) = 'organization');
```

`submission` carries the scoped policy in item 1, as the mechanism's proof and
because it is the table every later item reads; item 2 puts the same policy on
`case_record`, `assignment`, `device` and `submission_op`; items 5 and 6
inherit it without a line of their own. Every other table carries the member
policy from §2.2. The API-layer `require(permission)` still exists — it is how
a screen is refused before it renders — but it is the courtesy, not the
guarantee.

### 5.1 Three probes, run on 7 September 2026

Against a scratch database on the development Postgres, as a superuser owner
(`dcp`, the role in `docker-compose.yml`) and a fresh non-superuser role; two
rows in a `submission` table, one per user, with the policy above.
`scripts/` will keep the probe once the tests exist; until then this table is
the evidence.

| Probe | Result |
|---|---|
| **The owner is a superuser, and a superuser bypasses everything.** Owner, no principal set, `ENABLE` only | 2 rows |
| Owner, no principal set, `FORCE` | **2 rows.** FORCE subjects the *owner* to policies; it does nothing to a *superuser*. `dcp` is both |
| App role, no principal set | 0 rows |
| App role, `app.visible_user_ids = usr_a` set with `set_config(…, true)` | 1 row, `s1` |
| **After that transaction ends**, `current_setting('app.visible_user_ids', true)` | **`''`, not NULL.** A custom setting that has been set once in a session reads back as the empty string for the rest of that session |
| App role, `app.scope_kind = organization` (local) | 2 rows |
| After that transaction, rows | 0 |
| **Pool return.** SQLAlchemy asyncpg pool of size 1. Request 1 sets the principal with `is_local => true`, sees 1 row. Request 2 on the same pooled connection | setting `''`, **0 rows** |
| Request 3 sets the principal with `is_local => false` (session level), sees 1 row. Request 4 on the same pooled connection | setting `'usr_b'`, **1 row — the leak** |

### 5.2 What the probes decide

- **The application never connects as the owner.** `FORCE` is not enough:
  the owner is a superuser, and the probe shows FORCE changing nothing for it.
  `dcp_app` (§2.2) is the only role the application and the test suite
  connect as, and the isolation test asserts `NOT rolsuper` on its own
  connection before any other assertion. A suite connecting as `dcp` passes
  every isolation test whether or not isolation works — the most exact
  instance of "what would pass every test" in this document.
- **The principal is set per transaction, `is_local => true`, and never at
  session level.** The pool-return probe is the whole reason: a session-level
  setting rode the pooled connection into the next request and showed it
  another person's row. A transaction-local one was gone. This is written
  into `specs/erd-v0.1.md` §1.1 as a rule with the probe as its evidence, so
  that the reset is never "optimised away" — there is no reset to remove,
  because the transaction's end is the reset.
- **Unset is `''` as often as it is NULL, and both mean no access.**
  `current_setting(name, true)` returns NULL on a connection that has never
  set the name and `''` on one that has. Every policy therefore compares
  through something that denies both: `= ANY (string_to_array('', ','))` is
  false, `'' = 'organization'` is false, and the member policy says
  `coalesce(…, '') <> ''`. A policy written `IS NOT NULL` would be open on
  every reused connection. The break that holds this: unset the principal —
  on a fresh connection *and* on one that has carried a principal — and the
  query returns zero rows, never everything.

### 5.3 The tests that keep it from being nominal

1. **`test_every_table_is_forced.py`** (db): enumerate `pg_tables` for every
   ordinary table in the schema — **fail closed**: an unknown table with no
   policy is a failure, not a skip, and `alembic_version` is the one
   exemption, named with its reason; each must have
   `relrowsecurity` and `relforcerowsecurity` true and at least one row in
   `pg_policies`. Fails naming the table. A migration that adds a table
   without a policy is red in CI; a policy that exists without FORCE is red
   in CI — the worst failure shape, correct in `psql` and bypassed by the app
   connection, cannot land.
2. **`test_tenant_isolation.py`** (db, §2.4): asserts the connection role is
   `dcp_app` and not a superuser first; then the raw unfiltered
   `select(Submission)` under supervisor A's principal sees A's team's rows
   only; under no principal, on a fresh connection and on a reused one, sees
   none; under the fixture organisation, sees nothing of the seed's.
3. **`test_one_connection_factory.py`**: the AST lint of §2.3 — no engine,
   no raw connection, no `postgresql://` outside the factory, in `app/` or
   `scripts/`.
4. **The scoped-table list in `test_schema.py`**: the tables carrying a
   `scope` policy are enumerated, and a table item 2 scopes that is missing
   from the list fails, the way `test_tenant_tables_have_no_organization_id_column`
   works.

Breaks, each to be run for real when the tests exist: drop FORCE from one
table; drop a policy from one table; add a table in a scratch migration with
no policy; connect the suite as the owner; set the principal at session
level; write a policy with `IS NOT NULL`; unset the principal and expect
zero.

## 6. The model's DDL — memberships, roles, people

Unchanged in substance from the first draft. Every new table below is
created with row-level security enabled and forced and the organisation
policy of §2.2, like every other.

```sql
-- platform_user: a person exists once and is never deleted (§3.4)
ALTER TABLE platform_user
    ADD COLUMN display_name text NOT NULL DEFAULT '',
    ADD COLUMN username     text UNIQUE,          -- the login identifier (assumption A1)
    ADD COLUMN phone        text,
    ADD COLUMN created_by   text REFERENCES platform_user (id) ON DELETE RESTRICT,
    ADD COLUMN updated_at   timestamptz NOT NULL DEFAULT now(),
    ALTER COLUMN email DROP NOT NULL;
-- Status set unchanged. `pending_approval` is a membership's, not a person's (§7).

-- platform_org_membership: §3.2 who created, §3.3 pending, §3.4 permanent/temporary
ALTER TABLE platform_org_membership
    ADD COLUMN status          text NOT NULL DEFAULT 'active',
    ADD COLUMN membership_kind text NOT NULL DEFAULT 'permanent',
    ADD COLUMN created_by      text REFERENCES platform_user (id) ON DELETE RESTRICT,
    ADD COLUMN approved_by     text REFERENCES platform_user (id) ON DELETE RESTRICT,
    ADD COLUMN approved_at     timestamptz,
    ADD COLUMN deactivated_at  timestamptz,
    ADD CONSTRAINT platform_org_membership_status_check
        CHECK (status IN ('active', 'pending_approval', 'deactivated')),
    ADD CONSTRAINT platform_org_membership_kind_check
        CHECK (membership_kind IN ('permanent', 'temporary')),
    ADD CONSTRAINT platform_org_membership_approval_check
        CHECK ((approved_by IS NULL) = (approved_at IS NULL)),
    ADD CONSTRAINT platform_org_membership_pending_unapproved_check
        CHECK (status <> 'pending_approval' OR approved_at IS NULL);
-- `org_role` stays as who may administer the organisation itself (owner/admin).

-- role, role_permission, user_role (§3.5), in the tenant schema
CREATE TABLE role (
    id              text PRIMARY KEY,
    -- An organisation's own (§3.5): tenant-scoped like everything else, with
    -- the organisation policy. No shared system-role table beside it.
    organization_id text NOT NULL REFERENCES platform_organization (id) ON DELETE RESTRICT,
    name            text NOT NULL,
    scope_kind      text NOT NULL,
    builtin         boolean NOT NULL DEFAULT false,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, name),
    CONSTRAINT role_scope_kind_check
        CHECK (scope_kind IN ('organization', 'project', 'team'))
);
CREATE TABLE role_permission (
    role_id         text NOT NULL REFERENCES role (id) ON DELETE CASCADE,
    permission      text NOT NULL,
    PRIMARY KEY (role_id, permission),
    -- The closed set, mirrored in code like SUBMISSION_STATUSES and generated
    -- into the console's contract as PERMISSIONS.
    CONSTRAINT role_permission_name_check
        CHECK (permission IN (
            'user.create', 'user.approve', 'user.deactivate', 'user.assign_role',
            'team.manage',
            'sample.upload', 'sample.assign',
            'form.edit', 'form.publish', 'form.deploy',
            'submission.view', 'submission.review',
            'export.download',
            'device.revoke'
        ))
);
CREATE TABLE user_role (
    id              text PRIMARY KEY,
    user_id         text NOT NULL REFERENCES platform_user (id) ON DELETE RESTRICT,
    role_id         text NOT NULL REFERENCES role (id) ON DELETE RESTRICT,
    scope_kind      text NOT NULL,
    project_id      text REFERENCES project (id) ON DELETE CASCADE,
    team_id         text REFERENCES team (id) ON DELETE CASCADE,
    granted_by      text REFERENCES platform_user (id) ON DELETE RESTRICT,
    granted_at      timestamptz NOT NULL DEFAULT now(),
    revoked_at      timestamptz,
    CONSTRAINT user_role_scope_kind_check
        CHECK (scope_kind IN ('organization', 'project', 'team')),
    CONSTRAINT user_role_scope_target_check
        CHECK (
            (scope_kind = 'organization' AND project_id IS NULL AND team_id IS NULL) OR
            (scope_kind = 'project'      AND project_id IS NOT NULL AND team_id IS NULL) OR
            (scope_kind = 'team'         AND team_id IS NOT NULL)
        )
);
CREATE UNIQUE INDEX user_role_live_idx
    ON user_role (user_id, role_id, scope_kind, coalesce(project_id, ''), coalesce(team_id, ''))
    WHERE revoked_at IS NULL;

-- The standard roles, seeded PER ORGANISATION at its creation — by this
-- migration for the one that exists, by provisioning for every later one.
-- Duplicating a few rows is cheaper than an exception to the isolation rule.
INSERT INTO role (id, organization_id, name, scope_kind, builtin)
SELECT o.id || '_' || r.suffix, o.id, r.name, r.scope_kind, true
FROM platform_organization o,
     (VALUES ('admin', 'Admin', 'organization'),
             ('pm', 'Programme manager', 'project'),
             ('supervisor', 'Supervisor', 'team'),
             ('enumerator', 'Enumerator', 'team')) AS r(suffix, name, scope_kind);
-- and their permissions: Admin everything; PM everything but device.revoke;
-- Supervisor user.create, sample.assign, submission.view; Enumerator none —
-- an enumerator's access is their device's session, not a permission.

-- project_member: membership separate from the role (§3.1), with a status
ALTER TABLE project_member
    ADD COLUMN status     text NOT NULL DEFAULT 'active',
    ADD COLUMN added_by   text REFERENCES platform_user (id) ON DELETE RESTRICT,
    ADD COLUMN removed_at timestamptz,
    ADD CONSTRAINT project_member_user_fk
        FOREIGN KEY (user_id) REFERENCES platform_user (id) ON DELETE RESTRICT,
    ADD CONSTRAINT project_member_status_check CHECK (status IN ('active', 'removed')),
    DROP CONSTRAINT project_member_role_check,
    DROP COLUMN project_role;                 -- assumption A3

-- Who-did-what: every person-naming column becomes a foreign key while empty
ALTER TABLE form_version    ADD FOREIGN KEY (published_by) REFERENCES platform_user (id) ON DELETE RESTRICT;
ALTER TABLE form_deployment ADD FOREIGN KEY (deployed_by)  REFERENCES platform_user (id) ON DELETE RESTRICT;
ALTER TABLE form_draft      ADD FOREIGN KEY (updated_by)   REFERENCES platform_user (id) ON DELETE RESTRICT;
ALTER TABLE assignment      ADD FOREIGN KEY (assigned_by)  REFERENCES platform_user (id) ON DELETE RESTRICT;
ALTER TABLE assignment      ADD FOREIGN KEY (user_id)      REFERENCES platform_user (id) ON DELETE RESTRICT;
ALTER TABLE audit_event     ADD FOREIGN KEY (actor_id)     REFERENCES platform_user (id) ON DELETE RESTRICT;
ALTER TABLE submission      ADD FOREIGN KEY (created_by)   REFERENCES platform_user (id) ON DELETE RESTRICT;
UPDATE submission_op SET actor_id = NULL WHERE actor_id = 'usr_local';   -- assumption A5
ALTER TABLE submission_op   ADD FOREIGN KEY (actor_id)     REFERENCES platform_user (id) ON DELETE RESTRICT;
```

`ON DELETE RESTRICT` everywhere a person is named: §3.4 says a person is never
deleted, and the constraint makes the sentence true rather than remembered.

## 7. Where this departs from §3.6, and why

- **`pending_approval` is on the membership, not the user.** A supervisor's
  new enumerator is pending *in this organisation*; a person who already
  exists is selected, not created, and needs no approval (§3.2). The CHECK
  constraints make pending-with-an-approval unrepresentable.
- **`org_role` stays; operational roles are `user_role`.** Owner/admin of the
  organisation is a platform concern; PM, supervisor, enumerator and custom
  roles are rows with permissions, held in a scope.
- **Scope is two nullable columns and a CHECK**, the shape `assignment`
  already has, not a polymorphic id with no foreign key.
- **Isolation is a policy in the database**, not a filter in a service (§5).
- **Users and roles are tenant-scoped**, carrying `organization_id` under the
  same policy as everything else; §3.6 had them platform-level.

## 8. Assumptions the DDL was written under — say if any is wrong

The five questions from the first draft that the answers did not reach, each
taken the recommended way so the DDL could be written:

| | Assumed | If wrong |
|---|---|---|
| A1 | An enumerator logs in with a **username** chosen by whoever created them; email and phone optional | `username` becomes `phone`, or email stays required |
| A2 | A handset is **one person's** at a time; `device.user_id` is the current binding and a second login rebinds | Nothing in the DDL changes; the login flow refuses instead of rebinding |
| A3 | `project_member.project_role` is **dropped** now, while empty | Keep it as a label with no CHECK |
| A5 | Existing ops' `usr_local` actor becomes **null**; a pre-login op has no person | Keep the placeholder and declare the key `NOT VALID` for the past |
| A7 | The **seed** creates the organisation's owner; every other person descends from that one through §3.2 | A first-run command instead |

## 9. What lands with it, beyond the schema

- The connection layer (§2.3) and its isolation test (§2.4) — first, before
  any route is authenticated, because every later query is written against
  it.
- `POST /auth/login` (console and app), `POST /auth/logout`, `GET /auth/me`;
  the principal dependency and `require(permission)`; the push and pull
  routes bound to the app session (§4).
- A login page in the console; users, teams, roles and the approval queue
  (§3.3) for an Admin and a PM; a login screen in the app.
- `scripts/seed_dev.py` creates an owner, a PM, a supervisor with a team and
  an enumerator, so the chain can be walked on the emulator as item 0 was —
  including a pending enumerator who is refused, approved, and then pushes.
- The console's contract gains `PERMISSIONS`; every screen checks a name from
  it and no screen checks a role.
- Known-breaks rows for the structural claims: the connection layer set to a
  constant path; the policy dropped from `submission`; a test connecting as
  the owner; a route without the principal; a screen that checks a role name;
  a pending user who can log in; a registered, unbound device that can push;
  the session token in any storage; a script with its own engine; a table
  added in a scratch migration that the coverage test does not know; a login
  route that reads `platform_user` before the organisation is resolved.
