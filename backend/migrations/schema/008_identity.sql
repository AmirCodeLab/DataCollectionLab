-- 008_identity.sql — a person, not a device; and the isolation every later
-- query is written against.
--
-- NORMATIVE. migrations/versions/0008_identity.py transcribes this into
-- Alembic operations; tests/test_migrations.py asserts the two agree, and if
-- they ever disagree this file wins.
--
-- Spec: specs/erd-v0.1.md §1 (decided 7 September 2026: one shared schema,
-- isolation by row-level security set from the connection) and
-- docs/phase3-pilot-scope.md §3 (the model). The proposal this transcribes
-- is docs/phase3-item1-login-permissions.md.
--
-- ============================================================================
-- Two mechanisms are one mechanism
-- ============================================================================
--
-- Tenancy (an organisation cannot see another's rows) and scope (a supervisor
-- sees only their team) are the same thing asked twice: set a principal on
-- the connection, per transaction, and let the database enforce it. A filter
-- in a service can be forgotten by one export nobody thought of; a policy on
-- the table cannot be skipped by any query, filtered or not.
--
-- Every policy here is written by one of three helpers, never by hand per
-- table, so a table's policy is a call with a shape and not a chance to get
-- the expression wrong. Every table is ENABLED and FORCED, and
-- tests/test_every_table_is_forced.py enumerates pg_tables and fails closed:
-- an unknown table with no policy is a failure, not a skip. `alembic_version`
-- is the one named exemption — Alembic owns it, it holds no tenant data, and
-- the application never reads it.
--
-- Three facts every policy rests on, each from a probe run on 7 September
-- 2026 and recorded in the spec:
--
--   * The application never connects as the owner. The owner is a superuser,
--     and a superuser is exempt from row-level security; FORCE does not
--     change that. `dcp_app` (below) is what the application connects as.
--   * The principal is transaction-local (`set_config(name, value, true)`),
--     never session-level: a session-level setting rode a pooled connection
--     into the next request and showed it another person's row.
--   * An absent principal reads as '' as often as NULL — a setting set once in
--     a session reads back as '' for the rest of it — so every comparison
--     goes through coalesce(current_setting(name, true), '') and an absent
--     principal is NO ACCESS, never "unset, allow through".

-- ----------------------------------------------------------------------------
-- The principal, as the connection sees it (set by app/infrastructure/database.py):
--   app.org_slug           while login resolves the organisation from the request
--   app.org_id             the organisation
--   app.user_id            the person
--   app.scope_kind         'organization' | 'project' | 'team' — the widest live grant
--   app.visible_user_ids   comma-joined ids of the people whose work this
--                          principal may see
-- ----------------------------------------------------------------------------


-- ============================================================================
-- 1. The application's role
-- ============================================================================
--
-- Created NOLOGIN by the schema; the deployment grants LOGIN and a password
-- out of band (docker-compose, CI, production secrets). A password in a
-- normative file would be a published secret (conventions rule 11).

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dcp_app') THEN
        CREATE ROLE dcp_app NOLOGIN;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO dcp_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO dcp_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO dcp_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO dcp_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO dcp_app;


-- ============================================================================
-- 2. The discriminators: four tables name an organisation, nothing else does
-- ============================================================================

-- project: the root every operational table resolves through.
ALTER TABLE project ADD COLUMN organization_id text
    REFERENCES platform_organization (id) ON DELETE RESTRICT;
UPDATE project SET organization_id = (
    SELECT id FROM platform_organization ORDER BY created_at, id LIMIT 1
) WHERE organization_id IS NULL;
ALTER TABLE project ALTER COLUMN organization_id SET NOT NULL;
CREATE INDEX project_organization_idx ON project (organization_id);

-- platform_user: a person belongs to one organisation (pilot scope §3.1) and
-- is as tenant-scoped as a submission.
ALTER TABLE platform_user ADD COLUMN organization_id text
    REFERENCES platform_organization (id) ON DELETE RESTRICT;
UPDATE platform_user SET organization_id = (
    SELECT id FROM platform_organization ORDER BY created_at, id LIMIT 1
) WHERE organization_id IS NULL;
ALTER TABLE platform_user ALTER COLUMN organization_id SET NOT NULL;
-- So a membership can reference the pair and never disagree with it.
ALTER TABLE platform_user ADD CONSTRAINT platform_user_org_id_key UNIQUE (organization_id, id);

-- audit_event: an audit trail is an organisation's by nature, and it has no
-- project to resolve through — a user's approval is not a project event.
ALTER TABLE audit_event ADD COLUMN organization_id text
    REFERENCES platform_organization (id) ON DELETE RESTRICT;
UPDATE audit_event SET organization_id = (
    SELECT id FROM platform_organization ORDER BY created_at, id LIMIT 1
) WHERE organization_id IS NULL;
ALTER TABLE audit_event ALTER COLUMN organization_id SET NOT NULL;

-- outbox_event resolves through its project, like everything operational.
ALTER TABLE outbox_event ADD COLUMN project_id text
    REFERENCES project (id) ON DELETE CASCADE;
UPDATE outbox_event SET project_id = (
    SELECT id FROM project ORDER BY created_at, id LIMIT 1
) WHERE project_id IS NULL;
ALTER TABLE outbox_event ALTER COLUMN project_id SET NOT NULL;

-- (`role`, the fourth, is created in §4.)

-- schema_name meant something under schema-per-tenant. It does not now.
ALTER TABLE platform_organization DROP COLUMN schema_name;


-- ============================================================================
-- 3. People and memberships (pilot scope §3.1–§3.4)
-- ============================================================================

ALTER TABLE platform_user
    ADD COLUMN display_name text NOT NULL DEFAULT '',
    -- The login identifier (proposal §8, A1): chosen by whoever created the
    -- person; email and phone are optional and informational.
    ADD COLUMN username text,
    ADD COLUMN phone text,
    ADD COLUMN created_by text REFERENCES platform_user (id) ON DELETE RESTRICT,
    ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now(),
    ALTER COLUMN email DROP NOT NULL;
ALTER TABLE platform_user ADD CONSTRAINT platform_user_username_key UNIQUE (username);

-- The status set is unchanged: `invited` is "exists, has no credentials
-- yet"; `deactivated` is §3.4's end of a temporary membership.
-- `pending_approval` is a fact about a MEMBERSHIP, not a person (a person who
-- already exists is selected, not created, and needs no approval — §3.2), so
-- it lives on the membership, below.

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
    -- Pending never carries an approval; the two states are not both true.
    ADD CONSTRAINT platform_org_membership_pending_unapproved_check
        CHECK (status <> 'pending_approval' OR approved_at IS NULL),
    -- The membership's organisation IS the person's. Unrepresentable otherwise.
    ADD CONSTRAINT platform_org_membership_same_org_fk
        FOREIGN KEY (organization_id, user_id)
        REFERENCES platform_user (organization_id, id) ON DELETE CASCADE;

-- `org_role` stays as who may administer the organisation itself
-- (owner / admin / member); operational roles are §4.


-- ============================================================================
-- 4. Roles: a set of permissions plus a scope (pilot scope §3.5)
-- ============================================================================

-- An organisation's own. Tenant-scoped like everything else, with the same
-- policy; there is no shared system-role table beside it, because that would
-- be a second isolation model living beside the first, one of which gets
-- forgotten. The standard roles are seeded per organisation at its creation
-- (below, for the one that exists; by provisioning for every later one).
CREATE TABLE role (
    id              text PRIMARY KEY,
    organization_id text NOT NULL REFERENCES platform_organization (id) ON DELETE RESTRICT,
    name            text NOT NULL,
    -- The kind of scope a holder is given: an admin's is the organisation, a
    -- PM's a project, a supervisor's a team.
    scope_kind      text NOT NULL,
    -- The seeded roles cannot be deleted or renamed; custom roles can.
    builtin         boolean NOT NULL DEFAULT false,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT role_org_name_key UNIQUE (organization_id, name),
    CONSTRAINT role_scope_kind_check
        CHECK (scope_kind IN ('organization', 'project', 'team'))
);

CREATE TABLE role_permission (
    role_id         text NOT NULL REFERENCES role (id) ON DELETE CASCADE,
    permission      text NOT NULL,
    PRIMARY KEY (role_id, permission),
    -- The closed set. Mirrored in code the way SUBMISSION_STATUSES is, and
    -- generated into the console's contract as PERMISSIONS, so a screen
    -- checks a permission by name from this list and never a role.
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

-- This person holds this role in this scope. Exactly the column the scope
-- kind names is set; the organisation needs none — the role's is it.
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
-- One live grant of a role in a scope per person; a revoked one may recur.
CREATE UNIQUE INDEX user_role_live_idx
    ON user_role (user_id, role_id, scope_kind, coalesce(project_id, ''), coalesce(team_id, ''))
    WHERE revoked_at IS NULL;

-- The standard roles, per organisation. Duplicating a few rows is cheaper
-- than an exception to the isolation rule.
INSERT INTO role (id, organization_id, name, scope_kind, builtin)
SELECT o.id || '_' || r.suffix, o.id, r.name, r.scope_kind, true
FROM platform_organization o,
     (VALUES ('admin',      'Admin',             'organization'),
             ('pm',         'Programme manager', 'project'),
             ('supervisor', 'Supervisor',        'team'),
             ('enumerator', 'Enumerator',        'team')) AS r(suffix, name, scope_kind);

-- Admin: everything. PM: everything but device.revoke. Supervisor (§3.2):
-- creates enumerators in their own team, assigns sample, sees submissions —
-- and does NOT hold user.approve, which is how the approval flow falls out of
-- the model. Enumerator: no permission; an enumerator's access is their
-- device's session, not a grant.
INSERT INTO role_permission (role_id, permission)
SELECT r.id, p.name
FROM role r,
     (VALUES ('user.create'), ('user.approve'), ('user.deactivate'), ('user.assign_role'),
             ('team.manage'), ('sample.upload'), ('sample.assign'),
             ('form.edit'), ('form.publish'), ('form.deploy'),
             ('submission.view'), ('submission.review'),
             ('export.download'), ('device.revoke')) AS p(name)
WHERE r.builtin AND (
    (r.name = 'Admin')
    OR (r.name = 'Programme manager' AND p.name <> 'device.revoke')
    OR (r.name = 'Supervisor' AND p.name IN ('user.create', 'sample.assign', 'submission.view'))
);


-- ============================================================================
-- 5. Membership of a project is separate from the role (pilot scope §3.1)
-- ============================================================================

ALTER TABLE project_member
    ADD COLUMN status     text NOT NULL DEFAULT 'active',
    ADD COLUMN added_by   text REFERENCES platform_user (id) ON DELETE RESTRICT,
    ADD COLUMN removed_at timestamptz,
    ADD CONSTRAINT project_member_user_fk
        FOREIGN KEY (user_id) REFERENCES platform_user (id) ON DELETE RESTRICT,
    ADD CONSTRAINT project_member_status_check
        CHECK (status IN ('active', 'removed')),
    -- The role lives in user_role now; a second place a role is written down
    -- is a second place it can disagree (proposal §8, A3).
    DROP CONSTRAINT project_member_role_check,
    DROP COLUMN project_role;


-- ============================================================================
-- 6. Devices: registered is not bound (proposal §4)
-- ============================================================================
--
-- A device may register but cannot push until it is bound to an active
-- person: login binds it and creates the app session; push requires that
-- session. The same active membership that admits a person admits their
-- device — no second rule.

UPDATE device SET user_id = NULL WHERE user_id = 'usr_unassigned';
ALTER TABLE device
    ALTER COLUMN user_id DROP NOT NULL,
    ADD COLUMN bound_at timestamptz,
    ADD CONSTRAINT device_user_fk
        FOREIGN KEY (user_id) REFERENCES platform_user (id) ON DELETE RESTRICT,
    ADD CONSTRAINT device_bound_check
        CHECK ((user_id IS NULL) = (bound_at IS NULL));


-- ============================================================================
-- 7. Sessions: a cookie, a row, and nothing readable in the page
-- ============================================================================
--
-- One table for the console and the app, because revocation is one
-- operation: revoking a device revokes its sessions, deactivating a person
-- revokes theirs, "log that phone out" is a row update. The cookie carries an
-- opaque random token; only its hash is here, so a copy of this table logs
-- nobody in. HttpOnly, Secure, SameSite=Strict — no token in any storage a
-- page can read, the private-key rule applied to sessions.

CREATE TABLE platform_session (
    id                 text PRIMARY KEY,
    user_id            text NOT NULL REFERENCES platform_user (id) ON DELETE CASCADE,
    -- 'console' or 'app'. An app session names its device; a console session never does.
    kind               text NOT NULL,
    device_id          text REFERENCES device (id) ON DELETE CASCADE,
    token_hash         text NOT NULL,
    created_at         timestamptz NOT NULL DEFAULT now(),
    last_used_at       timestamptz,
    expires_at         timestamptz NOT NULL,
    revoked_at         timestamptz,
    revoked_reason     text,
    CONSTRAINT platform_session_token_hash_key UNIQUE (token_hash),
    CONSTRAINT platform_session_kind_check CHECK (kind IN ('console', 'app')),
    CONSTRAINT platform_session_device_check CHECK ((kind = 'app') = (device_id IS NOT NULL))
);
CREATE INDEX platform_session_user_idx ON platform_session (user_id);


-- ============================================================================
-- 8. Who did what: a person-naming column is a foreign key
-- ============================================================================
--
-- ON DELETE RESTRICT everywhere: §3.4 says a person is never deleted, and
-- the constraint makes the sentence true rather than remembered.
--
-- Two columns are NOT keyed here: submission.created_by and
-- submission_op.actor_id. They are the two a device writes offline, and
-- today every handset stamps them 'usr_local'. They gain their keys in the
-- step that binds a device to a person (proposal §4), when the server stamps
-- the actor from the session and stops trusting the device's word for it —
-- keying them now would refuse every push from a handset that has not yet
-- been given a way to log in. Stated here so the gap has a name.

ALTER TABLE form_version ADD CONSTRAINT form_version_published_by_fk
    FOREIGN KEY (published_by) REFERENCES platform_user (id) ON DELETE RESTRICT;
ALTER TABLE form_deployment ADD CONSTRAINT form_deployment_deployed_by_fk
    FOREIGN KEY (deployed_by) REFERENCES platform_user (id) ON DELETE RESTRICT;
ALTER TABLE form_draft ADD CONSTRAINT form_draft_updated_by_fk
    FOREIGN KEY (updated_by) REFERENCES platform_user (id) ON DELETE RESTRICT;
ALTER TABLE assignment ADD CONSTRAINT assignment_user_fk
    FOREIGN KEY (user_id) REFERENCES platform_user (id) ON DELETE RESTRICT;
ALTER TABLE assignment ADD CONSTRAINT assignment_assigned_by_fk
    FOREIGN KEY (assigned_by) REFERENCES platform_user (id) ON DELETE RESTRICT;
ALTER TABLE audit_event ADD CONSTRAINT audit_event_actor_fk
    FOREIGN KEY (actor_id) REFERENCES platform_user (id) ON DELETE RESTRICT;


-- ============================================================================
-- 9. Row-level security, on every table, from three helpers
-- ============================================================================

-- The one expression an absent principal must fail. '' and NULL alike.
CREATE FUNCTION dcp_principal(name text) RETURNS text
    LANGUAGE sql STABLE
    RETURN coalesce(current_setting(name, true), '');

-- Enable, force, and write the one policy. Every policy below goes through
-- this; nothing is hand-rolled per table.
CREATE FUNCTION dcp_policy(tbl regclass, using_expr text) RETURNS void
    LANGUAGE plpgsql AS $$
BEGIN
    EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY', tbl);
    EXECUTE format('ALTER TABLE %s FORCE ROW LEVEL SECURITY', tbl);
    EXECUTE format('DROP POLICY IF EXISTS isolation ON %s', tbl);
    EXECUTE format('CREATE POLICY isolation ON %s USING (%s) WITH CHECK (%s)',
                   tbl, using_expr, using_expr);
END
$$;

-- Shape (a): a root — the row's organisation is the principal's.
CREATE FUNCTION dcp_policy_root(tbl regclass) RETURNS void
    LANGUAGE sql
    RETURN dcp_policy(tbl, 'organization_id = dcp_principal(''app.org_id'')');

-- Shape (b): a child — the row's parent is visible, so the row is. The
-- subselect is itself under the parent's policy, which is how the chain
-- reaches project and then the organisation.
CREATE FUNCTION dcp_policy_chain(tbl regclass, fk_column text, parent regclass) RETURNS void
    LANGUAGE sql
    RETURN dcp_policy(tbl, format('%I IN (SELECT id FROM %s)', fk_column, parent));

-- The roots.
SELECT dcp_policy_root('project');
SELECT dcp_policy_root('platform_user');
SELECT dcp_policy_root('role');
SELECT dcp_policy_root('audit_event');
SELECT dcp_policy_root('platform_org_membership');
-- platform_organization: visible by id once the principal is set, or by slug
-- while the login route is resolving it from the request — the one row
-- either way, and never a user before an organisation (ERD §1).
SELECT dcp_policy('platform_organization',
    'id = dcp_principal(''app.org_id'') OR slug = dcp_principal(''app.org_slug'')');

-- platform_session is where pending_approval is STRUCTURAL rather than a
-- login check: a session exists only for a person whose membership in the
-- principal's organisation is active. WITH CHECK refuses inserting one for a
-- pending or deactivated person; USING makes a deactivated person's existing
-- sessions vanish — logged out by the policy, with no revoke job to forget.
SELECT dcp_policy('platform_session',
    'EXISTS (SELECT 1 FROM platform_org_membership m '
    ' WHERE m.user_id = platform_session.user_id AND m.status = ''active'')');

-- Under project, one step.
SELECT dcp_policy_chain('environment',         'project_id', 'project');
SELECT dcp_policy_chain('team',                'project_id', 'project');
SELECT dcp_policy_chain('project_member',      'project_id', 'project');
SELECT dcp_policy_chain('device',              'project_id', 'project');
SELECT dcp_policy_chain('project_key',         'project_id', 'project');
SELECT dcp_policy_chain('form',                'project_id', 'project');
SELECT dcp_policy_chain('entity_type',         'project_id', 'project');
SELECT dcp_policy_chain('dataset',             'project_id', 'project');
SELECT dcp_policy_chain('case_record',         'project_id', 'project');
SELECT dcp_policy_chain('tombstone',           'project_id', 'project');
SELECT dcp_policy_chain('quality_rule',        'project_id', 'project');
SELECT dcp_policy_chain('workflow_definition', 'project_id', 'project');
SELECT dcp_policy_chain('outbox_event',        'project_id', 'project');
SELECT dcp_policy_chain('user_role',           'role_id',    'role');
SELECT dcp_policy_chain('role_permission',     'role_id',    'role');

-- Two steps and further.
SELECT dcp_policy_chain('form_version',           'form_id',            'form');
SELECT dcp_policy_chain('form_draft',             'form_id',            'form');
SELECT dcp_policy_chain('form_deployment',        'form_version_id',    'form_version');
SELECT dcp_policy_chain('entity',                 'entity_type_id',     'entity_type');
SELECT dcp_policy_chain('entity_relationship',    'from_entity_id',     'entity');
SELECT dcp_policy_chain('dataset_version',        'dataset_id',         'dataset');
SELECT dcp_policy_chain('dataset_record',         'dataset_version_id', 'dataset_version');
SELECT dcp_policy_chain('form_version_dataset',   'form_version_id',    'form_version');
SELECT dcp_policy_chain('assignment',             'case_id',            'case_record');
SELECT dcp_policy_chain('visit',                  'case_id',            'case_record');
SELECT dcp_policy_chain('sync_cursor',            'device_id',          'device');
SELECT dcp_policy_chain('workflow_instance',      'definition_id',      'workflow_definition');
SELECT dcp_policy_chain('workflow_transition',    'instance_id',        'workflow_instance');

-- submission carries the SCOPED policy (the proof of the mechanism, and the
-- table every later item reads): its project is visible, AND its author is
-- among the people this principal may see, unless the principal's scope is
-- the whole organisation. Items 2, 5 and 6 put the same shape on
-- case_record, assignment, device and submission_op.
SELECT dcp_policy('submission',
    'project_id IN (SELECT id FROM project) AND ('
    '  created_by = ANY (string_to_array(dcp_principal(''app.visible_user_ids''), '','')) '
    '  OR dcp_principal(''app.scope_kind'') = ''organization'')');

-- Everything under a submission inherits its scope.
SELECT dcp_policy_chain('submission_content_key', 'submission_id',  'submission');
SELECT dcp_policy_chain('submission_wrapped_key', 'submission_id',  'submission');
SELECT dcp_policy_chain('submission_op',          'submission_id',  'submission');
SELECT dcp_policy_chain('submission_state',       'submission_id',  'submission');
SELECT dcp_policy_chain('submission_snapshot',    'submission_id',  'submission');
SELECT dcp_policy_chain('media',                  'submission_id',  'submission');
SELECT dcp_policy_chain('media_upload_session',   'media_id',       'media');
SELECT dcp_policy_chain('media_wrapped_key',      'media_id',       'media');
SELECT dcp_policy_chain('media_chunk',            'media_id',       'media');
SELECT dcp_policy_chain('quality_flag',           'submission_id',  'submission');
SELECT dcp_policy_chain('review',                 'submission_id',  'submission');

-- spatial_ref_sys is PostGIS's, not ours, and the extension owns it; the
-- coverage test names it beside alembic_version as the two exemptions.
