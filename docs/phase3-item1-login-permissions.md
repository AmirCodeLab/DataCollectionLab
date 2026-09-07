# Item 1 — login and permissions: the schema, before the code

**Status:** proposal, 7 September 2026. Nothing here is implemented. The
decisions it rests on are the ones in `docs/phase3-pilot-scope.md` §3 from the
design session; what this document adds is the DDL those decisions become,
what in the current schema and code has to move for them, and the questions
the DDL cannot be written without answering. Read §3 first; this does not
restate it.

The shape is the one §11.3 of the Form IR took: decide the model in a
document, then write the migration as its transcription
(`migrations/schema/008_identity.sql`, NORMATIVE, with the Alembic file
transcribing it and `test_migrations.py` holding the two together).

---

## 1. What exists today, plainly

The platform identifies a device, not a person, and it does so loosely.

| | Today |
|---|---|
| Authentication | **None, on any route.** Every handler takes a database session and nothing else (`app/api/v1/*`, `app/api/deps.py`). Anyone who reaches the API is everyone |
| The console | No login page, no session, no principal. `/forms/{id}` edits, publishes and deploys for whoever opens it |
| The handset | Registers a device (`POST /devices`, sync §4) and is attached to the deployment's single project. Its ops carry `actorId = "usr_local"` (`CoreFactory.kt`); the server files the device under `user_id = "usr_unassigned"` (`projects/service.py`) |
| `platform_user` | Exists (`001_initial.sql`), with `email NOT NULL UNIQUE`, `password_hash`, `mfa_secret`, a status set of active / invited / suspended / deactivated. **No row is ever written**: `scripts/seed_dev.py` seeds an organisation, a project and environments, and no user |
| `platform_org_membership` | Exists, `org_role` in owner / admin / member. Never written |
| `project_member` | Exists. `user_id` is text with no foreign key; `project_role` is a CHECK of five names; `team_id` is nullable. Never written |
| `team` | Exists, project-scoped, with `parent_team_id`. Never written |
| Who-did-what columns | `submission.created_by`, `submission_op.actor_id`, `form_version.published_by`, `form_deployment.deployed_by`, `form_draft.updated_by`, `assignment.assigned_by`, `audit_event.actor_id`, `device.user_id` — all `text`, none a foreign key, all null or a placeholder |
| Tenancy | Schema-per-tenant is the ERD's rule (`specs/erd-v0.1.md` §1) and `test_tenant_tables_have_no_organization_id_column` enforces the column half. **The app sets no `search_path`**: there is one schema, and `platform_*` and tenant tables sit in it together. The rule is real in the DDL and not yet in the runtime |

Two things follow for the schema. The role tables are tenant tables — an
organisation's roles are operational data and carry no `organization_id`,
which the test would refuse anyway. And every text column that names a person
gains a foreign key now, while every one of them is empty; the moment one of
them holds a real id is the moment adding the key becomes a data migration.

## 2. The model, in tables

§3.1's diagram, with the tables named:

```
platform_user               who: credentials, created once, never deleted
    │
platform_org_membership     member of this organisation — status, kind, who created,
    │                       who approved (§3.3, §3.4)
    │
role                        a named set of permissions for a scope kind (§3.5)
role_permission             the set
user_role                   this user holds this role in this scope:
    │                       the organisation, one project, or one team
    │
project_member              is in this project, in this team (§3.1 "comes and goes")
team                        the supervisor's team; scope resolves through it
    │
device                      bound to a person once they log in on it
platform_session            a login: refresh token, device, revocation (arch §14)
```

**Permissions, not roles** (§3.5): the server checks `user.approve`, never
"is a PM". A role is a row, and the three roles §3.2 names are seeded rows,
not code. "A supervisor sees only their own team" is `user_role.scope_kind =
'team'`, and the query layer resolves it — §4.2 of the pilot scope says why it
is a scope and not a filter.

## 3. The DDL

Proposed `migrations/schema/008_identity.sql`. Everything below is against
`001_initial.sql` as it stands; nothing else has touched these tables.

```sql
-- 008_identity.sql — a person, not a device.
--
-- NORMATIVE. migrations/versions/0008_identity.py transcribes this into
-- Alembic operations; tests/test_migrations.py asserts the two agree.

-- ---------------------------------------------------------------------------
-- platform_user: a person exists once, and is never deleted (pilot scope §3.4)
-- ---------------------------------------------------------------------------

ALTER TABLE platform_user
    ADD COLUMN display_name text NOT NULL DEFAULT '',
    ADD COLUMN username     text UNIQUE,          -- see question 1
    ADD COLUMN phone        text,                 -- see question 1
    ADD COLUMN created_by   text REFERENCES platform_user (id) ON DELETE RESTRICT,
    ADD COLUMN updated_at   timestamptz NOT NULL DEFAULT now(),
    ALTER COLUMN email DROP NOT NULL;             -- see question 1

-- The status set is unchanged: `invited` is "exists, has no credentials yet",
-- `deactivated` is §3.4's end of a temporary membership. `pending_approval`
-- is NOT added here — it is a fact about a membership, not a person (§4 below).

-- ---------------------------------------------------------------------------
-- platform_org_membership: §3.2 who created, §3.3 pending, §3.4 permanent/temporary
-- ---------------------------------------------------------------------------

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
    -- An approval is a fact with a witness: both or neither.
    ADD CONSTRAINT platform_org_membership_approval_check
        CHECK ((approved_by IS NULL) = (approved_at IS NULL)),
    -- Active means somebody approved it, or nobody had to (created by a PM
    -- or an Admin, §3.2). Pending never carries an approval.
    ADD CONSTRAINT platform_org_membership_pending_unapproved_check
        CHECK (status <> 'pending_approval' OR approved_at IS NULL);

-- `org_role` stays as the platform-level owner/admin/member — who may
-- administer the organisation itself. Operational roles move to `user_role`.

-- ---------------------------------------------------------------------------
-- role, role_permission, user_role: §3.5, permissions plus a scope
-- ---------------------------------------------------------------------------

CREATE TABLE role (
    id              text PRIMARY KEY,
    name            text NOT NULL UNIQUE,
    -- The kind of scope a holder of this role is given: an admin's is the
    -- organisation, a PM's a project, a supervisor's a team.
    scope_kind      text NOT NULL,
    -- The three roles §3.2 names are seeded and cannot be deleted; custom
    -- roles (architecture S1) are the rest.
    builtin         boolean NOT NULL DEFAULT false,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT role_scope_kind_check
        CHECK (scope_kind IN ('organization', 'project', 'team'))
);

CREATE TABLE role_permission (
    role_id         text NOT NULL REFERENCES role (id) ON DELETE CASCADE,
    permission      text NOT NULL,
    PRIMARY KEY (role_id, permission),
    -- The closed set. Mirrored in code the way SUBMISSION_STATUSES is, and
    -- generated into the console's contract so a screen checks a name from
    -- the same list (§3.5, "every console screen checks a permission").
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
    -- Exactly the column the scope kind names is set. The organisation needs
    -- no column: the tenant schema IS the organisation.
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
-- One live grant of a role in a scope per user; a revoked one may be repeated.
CREATE UNIQUE INDEX user_role_live_idx
    ON user_role (user_id, role_id, scope_kind, coalesce(project_id, ''), coalesce(team_id, ''))
    WHERE revoked_at IS NULL;

-- ---------------------------------------------------------------------------
-- project_member: membership is separate from the role (§3.1) and has a status
-- ---------------------------------------------------------------------------

ALTER TABLE project_member
    ADD COLUMN status     text NOT NULL DEFAULT 'active',
    ADD COLUMN added_by   text REFERENCES platform_user (id) ON DELETE RESTRICT,
    ADD COLUMN removed_at timestamptz,
    ADD CONSTRAINT project_member_user_fk
        FOREIGN KEY (user_id) REFERENCES platform_user (id) ON DELETE RESTRICT,
    ADD CONSTRAINT project_member_status_check
        CHECK (status IN ('active', 'removed'));
-- `project_role` stays for now and is no longer what the server checks —
-- see question 3 for whether it goes.

-- ---------------------------------------------------------------------------
-- device: bound to a person by login, not by registration
-- ---------------------------------------------------------------------------

ALTER TABLE device
    ALTER COLUMN user_id DROP NOT NULL,
    ADD COLUMN bound_at timestamptz,
    ADD CONSTRAINT device_user_fk
        FOREIGN KEY (user_id) REFERENCES platform_user (id) ON DELETE RESTRICT;
-- Existing rows hold 'usr_unassigned'; the migration sets them to NULL first.

-- ---------------------------------------------------------------------------
-- platform_session: a login (architecture §14: short-lived access token,
-- rotating refresh token, device and session revocation)
-- ---------------------------------------------------------------------------

CREATE TABLE platform_session (
    id                text PRIMARY KEY,
    user_id           text NOT NULL REFERENCES platform_user (id) ON DELETE CASCADE,
    -- Null for a console session; the handset's session names its device.
    device_id         text REFERENCES device (id) ON DELETE CASCADE,
    refresh_token_hash text NOT NULL UNIQUE,
    created_at        timestamptz NOT NULL DEFAULT now(),
    last_used_at      timestamptz,
    expires_at        timestamptz NOT NULL,
    revoked_at        timestamptz,
    revoked_reason    text
);

-- ---------------------------------------------------------------------------
-- Who-did-what: every person-naming column becomes a foreign key while empty
-- ---------------------------------------------------------------------------

ALTER TABLE form_version    ADD CONSTRAINT form_version_published_by_fk
    FOREIGN KEY (published_by) REFERENCES platform_user (id) ON DELETE RESTRICT;
ALTER TABLE form_deployment ADD CONSTRAINT form_deployment_deployed_by_fk
    FOREIGN KEY (deployed_by) REFERENCES platform_user (id) ON DELETE RESTRICT;
ALTER TABLE form_draft      ADD CONSTRAINT form_draft_updated_by_fk
    FOREIGN KEY (updated_by) REFERENCES platform_user (id) ON DELETE RESTRICT;
ALTER TABLE assignment      ADD CONSTRAINT assignment_assigned_by_fk
    FOREIGN KEY (assigned_by) REFERENCES platform_user (id) ON DELETE RESTRICT;
ALTER TABLE assignment      ADD CONSTRAINT assignment_user_fk
    FOREIGN KEY (user_id) REFERENCES platform_user (id) ON DELETE RESTRICT;
ALTER TABLE audit_event     ADD CONSTRAINT audit_event_actor_fk
    FOREIGN KEY (actor_id) REFERENCES platform_user (id) ON DELETE RESTRICT;
ALTER TABLE submission      ADD CONSTRAINT submission_created_by_fk
    FOREIGN KEY (created_by) REFERENCES platform_user (id) ON DELETE RESTRICT;
-- submission_op.actor_id: see question 5. It is the one column that is not
-- empty, and the one a device writes offline.
```

`ON DELETE RESTRICT` everywhere a person is named, because §3.4 says a person
is never deleted; the constraint makes the sentence true rather than
remembered.

## 4. Where the DDL departs from §3.6, and why

§3.6's table was written against `001_initial.sql` in one sitting; three rows
of it came out differently once the constraints were written.

- **`pending_approval` is on the membership, not the user.** §3.6 adds it to
  `platform_user.status`. A supervisor's new enumerator is pending *in this
  organisation*; the same person, if they already exist, is selected rather
  than created and needs no approval (§3.2). A status on the person would have
  to be cleared by the first approval and would say nothing about a second
  organisation. `platform_user.status` keeps `invited` for "exists, cannot log
  in yet", and the CHECK constraints above make pending-with-an-approval
  unrepresentable.
- **`org_role` stays; operational roles are `user_role`.** §3.6 offers
  "widens, or moves to a role table". Both: `org_role` keeps meaning who may
  administer the organisation (owner/admin), which is a platform concern;
  everything §3.2's table is about — PM, supervisor, enumerator, and custom
  roles after them — is a `role` row with permissions, held in a scope.
- **Scope has two nullable columns and a CHECK, not a polymorphic id.**
  `assignment` already does this (`assignment_target_check`); a `scope_id`
  text column with no foreign key is what `project_member.user_id` was.

## 5. What the DDL does not decide, and the code must

Listed so the implementation step does not decide them sideways.

- **The principal.** One FastAPI dependency that turns a bearer token into
  `(user, memberships, live user_roles)` and one `require("form.publish")`
  dependency that refuses without it. Every route gains it; the sync routes
  gain the device-bound session.
- **Scope resolution is structural** (§4.2 of the pilot scope: a filter can be
  forgotten, a scope cannot). Every list query in the modules items 2, 5 and 6
  build goes through one `scoped(query, principal)` helper, and a test in the
  shape of `test_form_version_has_one_writer.py` fails on a `select(...)` over a
  scoped table that does not. That test is item 2's first deliverable, not a
  nice-to-have.
- **Login on the handset binds the device.** Registration stays as it is
  (sync §4); the first successful login on a device sets `device.user_id` and
  `bound_at`, and the op's `actorId` becomes that user's id rather than
  `usr_local`. A pending or deactivated membership is refused at login with
  the reason, and the enumerator's prepared work (§3.3) is waiting when it lands.
- **The permission list is code-defined and generated outward.** The CHECK
  above, a Python literal beside it (mirrored by `test_wire_enum_mirrors.py`),
  and `PERMISSIONS` in the console's generated contract. The console checks a
  permission by name from that array and never a role — the first custom role
  is the test.

## 6. Questions the DDL cannot be written without

1. **What does an enumerator log in with?** `email` is `NOT NULL UNIQUE` today.
   RCons's 40–50 enumerators may not have email; a supervisor creating one in
   the field will not type one. The DDL above adds `username` and `phone`,
   makes `email` nullable, and needs one of them to be the identifier. My
   recommendation: `username`, unique, chosen by the creator; phone and email
   optional. Say which.
2. **Is a handset one person's?** `device.user_id` above is one user. If two
   enumerators share a phone across shifts, binding is per session and the
   device column is "last bound". RCons's practice decides; the DDL is the
   same either way, the login flow is not.
3. **`project_member.project_role`.** With roles in `user_role`, the five-name
   CHECK on `project_member` is a second place a role is written down. Keep it
   as a denormalised label, or drop it in this migration while it is empty? My
   recommendation: drop it now; a reversible migration can put an empty column
   back.
4. **Roles per organisation or per installation?** `role` above is a tenant
   table (one organisation per schema, by the ERD). Since the runtime has one
   schema today, the three built-in roles are seeded once and a second
   organisation would share them. That is correct under the ERD and wrong
   under the current runtime; it is the first place the missing `search_path`
   costs something. Either the tenancy runtime lands with item 1, or the
   proposal accepts one organisation for the pilot and says so.
5. **`submission_op.actor_id`.** The only person-column with data: every op so
   far carries `usr_local`. A foreign key needs those rows rewritten or the
   constraint declared `NOT VALID` for the past. Recommendation: the migration
   nulls the placeholder and adds the key; a null actor on a pre-login op is
   the truth.
6. **Sessions.** Short-lived access JWT plus the refresh row above, as the
   architecture doc says; lifetimes to confirm (proposal: 15 minutes / 30 days,
   the handset refreshing on sync). MFA (S7) and SSO (S8) are not in this
   item; `mfa_secret` stays unused.
7. **Who is the first user?** Nothing can create a user without a user. The
   seed script (or a one-off command) creates the organisation's owner; every
   other person descends from that one through §3.2. Confirm the seed is the
   right place for the pilot.

## 7. What lands with it, beyond the schema

- A login page in the console and a login screen in the app; a "who am I"
  route; users, teams and roles screens for an Admin and a PM; the approval
  queue for §3.3.
- `scripts/seed_dev.py` creates an owner, one PM, one supervisor with a team,
  and one enumerator, so the chain can be walked end to end on the emulator
  as item 0 was.
- Known-breaks rows for the structural claims: a route that skips the
  principal, a scoped query that skips `scoped()`, a console screen that
  checks a role name, a pending user who can log in.
