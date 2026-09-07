# Item 1 — login and permissions: the schema, before the code

**Status:** proposal, revised 7 September 2026 after three answers. Nothing here
is implemented. The decisions it rests on are the ones in
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
| **Tenancy first — the mechanism, not the provisioning.** Per-request `search_path` from the authenticated session's organisation; a test proving a query cannot reach another schema; one organisation, no onboarding, no second tenant | §2: the tenant tables leave `public`, the connection layer sets the path, migrations learn the schema. The isolation test needs a second *schema* in the test database and that is not a second *tenant* — §2.4 says how |
| **HttpOnly, SameSite=Strict cookies, console and app alike.** A token in browser storage is the shape the private-key test exists to refuse | §3: `platform_session` holds a hash of an opaque token; the token lives in the cookie and nowhere the page can read. The KMP client can carry cookies — §3.3 says what is ours to write |
| **Device registration goes through the same approval gate.** A device may register but cannot push until bound to an active user | §4: `device.user_id` becomes nullable and a foreign key, binding happens at login, and push requires the session that binding created. The `dev_` hole closes because an unbound device has nothing to present |

And one question the answers put in front of the schema — *what would pass
every test?* — has its own section, §5, because the honest answer is a
permission check in the API layer, which passes every screen test and fails
the first export.

## 1. What exists today, plainly

| | Today |
|---|---|
| Authentication | **None, on any route.** Every handler takes a database session and nothing else (`app/api/v1/*`, `app/api/deps.py`) |
| The console | No login page, no session, no principal. `/forms/{id}` edits, publishes and deploys for whoever opens it |
| The handset | Registers a device (`POST /devices`, sync §4) and is attached to the deployment's single project. Its ops carry `actorId = "usr_local"` (`CoreFactory.kt`); the server files the device under `user_id = "usr_unassigned"` (`projects/service.py`). **Anything that knows a device id can push as it** |
| `platform_user` | Exists, `email NOT NULL UNIQUE`, `password_hash`, `mfa_secret`, status active / invited / suspended / deactivated. **No row has ever been written** |
| `platform_org_membership`, `project_member`, `team` | Exist, never written. `project_member.user_id` is text with no foreign key |
| Who-did-what columns | `submission.created_by`, `submission_op.actor_id`, `form_version.published_by`, `form_deployment.deployed_by`, `form_draft.updated_by`, `assignment.assigned_by`, `audit_event.actor_id`, `device.user_id` — all `text`, none a foreign key, all null or a placeholder |
| Tenancy | The ERD (`specs/erd-v0.1.md` §1) says schema-per-tenant and `test_tenant_tables_have_no_organization_id_column` enforces the column half. **At runtime there is one schema.** The seed writes `schema_name = "public"` on the one organisation, the engine sets no `search_path`, and `migrations/env.py` knows no schema. Platform tables and tenant tables sit side by side in `public` |
| The database role | `dcp`, from `docker-compose.yml`, is the database's owner and a superuser. That matters in §5: a superuser is exempt from row-level security, so a test suite that connects as one cannot see whether isolation works |

## 2. Tenancy: the mechanism

### 2.1 What "the path exists before the first query" has to mean

The ERD's promise is that *a query that omits a filter cannot reach another
tenant's rows*, because the connection's `search_path` decides which
`submission` the word `submission` names. That promise holds only if the
other tenant's `submission` is not also on the path. With every tenant table
in `public`, a per-request `search_path = tenant_x, public` would fall through
to `public.submission` for any table the tenant schema lacked — the mechanism
would exist and prove nothing.

So `public` must hold only the `platform_*` tables, and the one organisation's
tables must live in a schema of their own. That is a table move, not
provisioning: nothing creates a schema for a new organisation, nothing
onboards one.

### 2.2 The DDL

```sql
-- One tenant schema for the one organisation. Named, not `public`, so that
-- `public` can hold platform tables only and a fallthrough cannot reach a
-- tenant row.
CREATE SCHEMA tenant_dev;

-- Every non-platform table moves. The list is every CREATE TABLE in
-- 001–007 whose name does not start with platform_; the migration derives
-- it from the catalogue rather than repeating it here, and
-- tests/test_schema.py::test_public_holds_only_platform_tables holds the
-- result.
ALTER TABLE project SET SCHEMA tenant_dev;
-- … (project, environment, team, project_member, device, project_key, form,
--     form_version, form_deployment, form_draft, entity_type, entity,
--     entity_relationship, dataset, dataset_version, dataset_record,
--     form_version_dataset, case_record, assignment, visit, submission,
--     submission_content_key, submission_wrapped_key, submission_op,
--     submission_state, submission_snapshot, tombstone, media,
--     media_upload_session, media_wrapped_key, media_chunk, quality_rule,
--     quality_flag, review, workflow_definition, workflow_instance,
--     workflow_transition, audit_event, outbox_event, sync_cursor)
ALTER SEQUENCE sync_stream_seq SET SCHEMA tenant_dev;

UPDATE platform_organization SET schema_name = 'tenant_dev' WHERE schema_name = 'public';

-- The application's role. Not the owner, not a superuser: the owner runs
-- migrations; the application reads and writes, and is subject to every
-- policy §5 adds.
CREATE ROLE dcp_app LOGIN PASSWORD :'app_password';
GRANT USAGE ON SCHEMA public, tenant_dev TO dcp_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public, tenant_dev TO dcp_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA tenant_dev TO dcp_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA tenant_dev GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO dcp_app;
```

`role` and `user_role` (§6) are tenant tables and are created in `tenant_dev`
by the same migration.

### 2.3 The connection layer

One place, `app/infrastructure/database.py`, and it is the *only* place a
session is handed out (the conventions already say so):

```
request ──► session cookie ──► platform_session ──► user ──► org membership
                                                            │
                                     SET LOCAL search_path = <org.schema_name>, public
                                     SET LOCAL app.user_id = …   (§5)
                                     SET LOCAL app.visible_user_ids = …
```

`SET LOCAL` inside the request's transaction, so a pooled connection carries
nothing to the next request. The organisation is read from the session, never
from a constant; the constant `"public"` in the seed goes with this. A request
with no session gets a connection with `search_path = public` and can reach
platform tables only — which is what a login route needs and all it needs.

Migrations: `migrations/env.py` gains `search_path = tenant_dev, public` and
keeps one version table, in `public`. Running the tenant stream once per
schema is the ERD's stated cost and is provisioning's problem; with one
organisation there is one stream.

### 2.4 The test, and the second schema it needs

`tests/test_tenant_isolation.py`, marked `db`:

1. The migrated database has `tenant_dev`; the test creates `tenant_scratch`
   by replaying the tenant DDL into it. **That is a schema, not a tenant** —
   no `platform_organization` row names it, nothing can log into it, and the
   test drops it. It exists so the test has something to fail to reach.
2. A row is inserted in `tenant_scratch.submission` and a different one in
   `tenant_dev.submission`, as the owner.
3. A session resolved to the dev organisation runs `select(Submission)` with
   **no filter**, as `dcp_app`. It sees the dev row and not the scratch row.
   The same resolved to scratch — by setting the path directly, since no
   session can — sees the reverse.
4. The connection's role is asserted to be `dcp_app` and `NOT rolsuper`
   *before* step 3, so the test cannot pass by running as the owner.

The break: point the connection layer at a constant path. Step 3 fails.

## 3. Sessions: a cookie, a row, and nothing in the page

### 3.1 The DDL

```sql
CREATE TABLE platform_session (
    id                 text PRIMARY KEY,
    user_id            text NOT NULL REFERENCES platform_user (id) ON DELETE CASCADE,
    -- 'console' or 'app'. An app session names its device (§4) and a console
    -- session never does.
    kind               text NOT NULL,
    device_id          text,          -- FK added in §4, the device table moves schema first
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
        FOREIGN KEY (device_id) REFERENCES tenant_dev.device (id) ON DELETE CASCADE;
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

`platform_session.device_id` references a tenant table from a platform table.
That is the one cross-schema key in the model, and it is the right direction:
a session belongs to the platform, a device to the organisation, and a
session for a device the organisation no longer has should go with it.

## 5. What would pass every test

The question asked, answered before the DDL rather than after the first
export.

A permission check in the API layer — `require("submission.view")`, and a
`WHERE` in each service that lists — passes every screen test, because every
screen calls a service that filters. It fails the first report or export that
queries the table directly, and nobody notices, because the screens are all
correct. That is the pilot scope §4.2's sentence with a mechanism missing:
"a filter can be forgotten in one query; a scope cannot" is true only if the
scope is somewhere a query cannot skip.

The place a query cannot skip is the database. **Row-level security**, set
from the same connection layer that sets `search_path`:

```sql
-- §5: the principal, as the connection sees it. Set with SET LOCAL by the
-- connection layer from the session; empty when there is no session.
--   app.user_id           the person
--   app.scope_kind        'organization' | 'project' | 'team' — the widest live grant
--   app.visible_user_ids  text[]: the people whose work this principal may see.
--                         For team scope, the team's members; for project
--                         scope, the project's; for organization, every member.

ALTER TABLE tenant_dev.submission ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_dev.submission FORCE ROW LEVEL SECURITY;
CREATE POLICY submission_scope ON tenant_dev.submission
    USING (created_by = ANY (string_to_array(current_setting('app.visible_user_ids', true), ','))
           OR current_setting('app.scope_kind', true) = 'organization');
```

`submission` in item 1, as the mechanism's proof and because it is the table
every later item reads. Item 2 adds the same policy to `case_record`,
`assignment`, `device` and `submission_op`; item 5's monitoring and item 6's
review inherit it without a line of their own.

Three things make this true rather than nominal, and each is a test:

- **The application is not the owner.** `FORCE ROW LEVEL SECURITY` subjects
  the owner to policies; a superuser is exempt from everything. The app
  connects as `dcp_app` (§2.2); `test_tenant_isolation.py` asserts the role
  before it asserts anything else. **A test suite that connects as `dcp`
  passes every isolation test whether or not isolation works** — that is the
  most exact instance of "what would pass every test" in this document.
- **The raw query is the test.** Supervisor A's principal runs
  `select(Submission)` — no service, no filter — and sees A's team's rows. Not
  the API: the model.
- **Every scoped table is listed.** `test_schema.py` gains a list of the
  tables that carry a scope policy and fails when a table item 2 scopes is
  missing from it, the way `test_tenant_tables_have_no_organization_id_column`
  works. The break: drop the policy on `submission`; the raw-query test fails.

The API-layer check still exists — `require(permission)` is how a screen is
refused before it renders — but it is the courtesy, not the guarantee.

## 6. The model's DDL — memberships, roles, people

Unchanged in substance from the first draft, restated with the tenancy
placement. All tenant tables are created in `tenant_dev`.

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
CREATE TABLE tenant_dev.role (
    id              text PRIMARY KEY,
    name            text NOT NULL UNIQUE,
    scope_kind      text NOT NULL,
    builtin         boolean NOT NULL DEFAULT false,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT role_scope_kind_check
        CHECK (scope_kind IN ('organization', 'project', 'team'))
);
CREATE TABLE tenant_dev.role_permission (
    role_id         text NOT NULL REFERENCES tenant_dev.role (id) ON DELETE CASCADE,
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
CREATE TABLE tenant_dev.user_role (
    id              text PRIMARY KEY,
    user_id         text NOT NULL REFERENCES platform_user (id) ON DELETE RESTRICT,
    role_id         text NOT NULL REFERENCES tenant_dev.role (id) ON DELETE RESTRICT,
    scope_kind      text NOT NULL,
    project_id      text REFERENCES tenant_dev.project (id) ON DELETE CASCADE,
    team_id         text REFERENCES tenant_dev.team (id) ON DELETE CASCADE,
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
    ON tenant_dev.user_role (user_id, role_id, scope_kind, coalesce(project_id, ''), coalesce(team_id, ''))
    WHERE revoked_at IS NULL;

-- The three roles §3.2 names, seeded by the migration, not by code.
INSERT INTO tenant_dev.role (id, name, scope_kind, builtin) VALUES
    ('role_admin',      'Admin',             'organization', true),
    ('role_pm',         'Programme manager', 'project',      true),
    ('role_supervisor', 'Supervisor',        'team',         true),
    ('role_enumerator', 'Enumerator',        'team',         true);
-- and their permissions: Admin everything; PM everything but device.revoke;
-- Supervisor user.create, sample.assign, submission.view; Enumerator none —
-- an enumerator's access is their device's session, not a permission.

-- project_member: membership separate from the role (§3.1), with a status
ALTER TABLE tenant_dev.project_member
    ADD COLUMN status     text NOT NULL DEFAULT 'active',
    ADD COLUMN added_by   text REFERENCES platform_user (id) ON DELETE RESTRICT,
    ADD COLUMN removed_at timestamptz,
    ADD CONSTRAINT project_member_user_fk
        FOREIGN KEY (user_id) REFERENCES platform_user (id) ON DELETE RESTRICT,
    ADD CONSTRAINT project_member_status_check CHECK (status IN ('active', 'removed')),
    DROP CONSTRAINT project_member_role_check,
    DROP COLUMN project_role;                 -- assumption A3

-- Who-did-what: every person-naming column becomes a foreign key while empty
ALTER TABLE tenant_dev.form_version    ADD FOREIGN KEY (published_by) REFERENCES platform_user (id) ON DELETE RESTRICT;
ALTER TABLE tenant_dev.form_deployment ADD FOREIGN KEY (deployed_by)  REFERENCES platform_user (id) ON DELETE RESTRICT;
ALTER TABLE tenant_dev.form_draft      ADD FOREIGN KEY (updated_by)   REFERENCES platform_user (id) ON DELETE RESTRICT;
ALTER TABLE tenant_dev.assignment      ADD FOREIGN KEY (assigned_by)  REFERENCES platform_user (id) ON DELETE RESTRICT;
ALTER TABLE tenant_dev.assignment      ADD FOREIGN KEY (user_id)      REFERENCES platform_user (id) ON DELETE RESTRICT;
ALTER TABLE tenant_dev.audit_event     ADD FOREIGN KEY (actor_id)     REFERENCES platform_user (id) ON DELETE RESTRICT;
ALTER TABLE tenant_dev.submission      ADD FOREIGN KEY (created_by)   REFERENCES platform_user (id) ON DELETE RESTRICT;
UPDATE tenant_dev.submission_op SET actor_id = NULL WHERE actor_id = 'usr_local';   -- assumption A5
ALTER TABLE tenant_dev.submission_op   ADD FOREIGN KEY (actor_id)     REFERENCES platform_user (id) ON DELETE RESTRICT;
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
  the session token in any storage.
