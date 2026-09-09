-- 010: people — the principal carries the person's authority, and the
-- database reads it.
--
-- The question asked before the people screens were written: what would pass
-- every test? A role or permission editable in the UI that the policy does
-- not read — a screen that says a supervisor may do something the database
-- will refuse, or worse, permit. So the authority a screen shows is the
-- authority the database enforces, from the same principal:
--
--   app.permissions   comma-joined: what this person may do
--   app.project_ids   the projects a project-scope grant names
--   app.team_ids      the teams a team-scope grant names, and their sub-teams
--
-- computed here, by `dcp_principal_for`, and declared on every transaction by
-- the connection layer. With those on the connection:
--
--   * a membership is created `active` only by someone holding user.approve —
--     the column DEFAULT decides, so the service never says which (§3.2, §3.3);
--     approval is an UPDATE only user.approve may make; deactivation only
--     user.deactivate;
--   * a role grant sits inside the grantor's own authority: every permission
--     the role carries is one they hold, and the scope target is within their
--     scope (§3.2: nobody creates a role above their own, or outside it);
--   * a role carries only permissions its editor holds, and the standard roles
--     cannot be edited or have permissions removed;
--   * a person sees the people in their scope, the people they created, and
--     themself (§4.2: supervisor A does not see B's enumerators) — which is a
--     policy on platform_user, and a policy on platform_user is why the auth
--     path becomes four SECURITY DEFINER functions: a login has to find a
--     person before there is a person on the connection. Those five are the
--     only reads of a person without a principal, and they are named here.
--
-- Downgrade restores 008/009's policies exactly.

-- ============================================================================
-- 1. The principal's authority, readable in a policy
-- ============================================================================

CREATE FUNCTION dcp_has(perm text) RETURNS boolean
    LANGUAGE sql STABLE
    RETURN perm = ANY (string_to_array(dcp_principal('app.permissions'), ','));

CREATE FUNCTION dcp_in_list(name text, value text) RETURNS boolean
    LANGUAGE sql STABLE
    RETURN value IS NOT NULL AND value = ANY (string_to_array(dcp_principal(name), ','));

CREATE FUNCTION dcp_org_wide() RETURNS boolean
    LANGUAGE sql STABLE
    RETURN dcp_principal('app.scope_kind') = 'organization';

-- The helper learns a separate WITH CHECK, and a restrictive form for the
-- one thing a permissive policy cannot say: "and never this".
CREATE FUNCTION dcp_policy(tbl regclass, using_expr text, check_expr text) RETURNS void
    LANGUAGE plpgsql AS $$
BEGIN
    EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY', tbl);
    EXECUTE format('ALTER TABLE %s FORCE ROW LEVEL SECURITY', tbl);
    EXECUTE format('DROP POLICY IF EXISTS isolation ON %s', tbl);
    EXECUTE format('CREATE POLICY isolation ON %s USING (%s) WITH CHECK (%s)',
                   tbl, using_expr, check_expr);
END
$$;

CREATE FUNCTION dcp_restrict(tbl regclass, name text, command text, expr text) RETURNS void
    LANGUAGE plpgsql AS $$
BEGIN
    EXECUTE format('DROP POLICY IF EXISTS %I ON %s', name, tbl);
    EXECUTE format('CREATE POLICY %I ON %s AS RESTRICTIVE FOR %s USING (%s)',
                   name, tbl, command, expr);
END
$$;

-- ============================================================================
-- 2. The auth path: the only reads of a person with no person on the connection
-- ============================================================================
--
-- SECURITY DEFINER: these run as the owner and see through the policies.
-- Each is scoped to app.org_id — the organisation is always resolved first
-- (ERD §1) — and each reads exactly what the login or the session needs.

-- One rule for "may hold a session", used by the session policy and by the
-- session lookup alike.
CREATE FUNCTION dcp_membership_active(person text) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public
    RETURN EXISTS (
        SELECT 1 FROM platform_org_membership m
        WHERE m.user_id = person AND m.status = 'active'
          AND m.organization_id = dcp_principal('app.org_id'));

CREATE FUNCTION dcp_login_lookup(login text)
    RETURNS TABLE (id text, organization_id text, password_hash text, username text,
                   display_name text, status text)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public
    AS $$
        SELECT u.id, u.organization_id, u.password_hash, u.username, u.display_name, u.status
        FROM platform_user u
        WHERE u.username = login AND u.organization_id = dcp_principal('app.org_id')
    $$;

CREATE FUNCTION dcp_session_lookup(hash text)
    RETURNS TABLE (session_id text, user_id text, kind text, device_id text,
                   expires_at timestamptz, last_used_at timestamptz,
                   username text, display_name text, organization_id text)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public
    AS $$
        SELECT s.id, s.user_id, s.kind, s.device_id, s.expires_at, s.last_used_at,
               u.username, u.display_name, u.organization_id
        FROM platform_session s
        JOIN platform_user u ON u.id = s.user_id
        WHERE s.token_hash = hash AND s.revoked_at IS NULL AND s.expires_at > now()
          AND u.organization_id = dcp_principal('app.org_id')
          AND dcp_membership_active(s.user_id)
    $$;

-- The principal a person's live grants amount to. The widest grant decides
-- the scope kind; the people in every granted project and team (and its
-- sub-teams), plus the person, are who they may see.
CREATE FUNCTION dcp_principal_for(person text)
    RETURNS TABLE (scope_kind text, visible_user_ids text[], project_ids text[],
                   team_ids text[], permissions text[])
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public
    AS $$
        WITH RECURSIVE grants AS (
            SELECT ur.scope_kind, ur.project_id, ur.team_id, ur.role_id
            FROM user_role ur
            WHERE ur.user_id = person AND ur.revoked_at IS NULL
        ),
        teams AS (
            SELECT g.team_id AS id FROM grants g WHERE g.team_id IS NOT NULL
            UNION
            SELECT t.id FROM team t JOIN teams ON t.parent_team_id = teams.id
        )
        SELECT
            coalesce((SELECT CASE
                        WHEN bool_or(g.scope_kind = 'organization') THEN 'organization'
                        WHEN bool_or(g.scope_kind = 'project') THEN 'project'
                        WHEN bool_or(g.scope_kind = 'team') THEN 'team'
                      END FROM grants g), ''),
            (SELECT array_agg(DISTINCT v.id ORDER BY v.id) FROM (
                SELECT person AS id
                UNION
                SELECT pm.user_id FROM project_member pm
                WHERE pm.status = 'active'
                  AND (pm.project_id IN (SELECT g.project_id FROM grants g WHERE g.scope_kind = 'project')
                       OR pm.team_id IN (SELECT id FROM teams))) v),
            (SELECT coalesce(array_agg(DISTINCT g.project_id ORDER BY g.project_id), '{}')
               FROM grants g WHERE g.scope_kind = 'project'),
            (SELECT coalesce(array_agg(DISTINCT id ORDER BY id), '{}') FROM teams),
            (SELECT coalesce(array_agg(DISTINCT rp.permission ORDER BY rp.permission), '{}')
               FROM grants g JOIN role_permission rp ON rp.role_id = g.role_id)
    $$;

-- Why a session was refused, for the login to name: the membership's status,
-- which the login cannot see either. Read only after the policy said no.
CREATE FUNCTION dcp_membership_status(person text) RETURNS text
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public
    RETURN (SELECT m.status FROM platform_org_membership m
            WHERE m.user_id = person AND m.organization_id = dcp_principal('app.org_id'));

-- A login is noted on the person, whom the login cannot yet see.
CREATE FUNCTION dcp_note_login(person text) RETURNS void
    LANGUAGE sql SECURITY DEFINER SET search_path = public
    AS $$
        UPDATE platform_user SET last_login_at = now()
        WHERE id = person AND organization_id = dcp_principal('app.org_id')
    $$;

REVOKE ALL ON FUNCTION dcp_membership_active(text), dcp_login_lookup(text),
    dcp_session_lookup(text), dcp_principal_for(text), dcp_membership_status(text),
    dcp_note_login(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION dcp_membership_active(text), dcp_login_lookup(text),
    dcp_session_lookup(text), dcp_principal_for(text), dcp_membership_status(text),
    dcp_note_login(text) TO dcp_app;

-- ============================================================================
-- 3. Who may hold a membership in which state is the database's decision
-- ============================================================================

-- A new membership: active if its creator may approve, waiting otherwise.
-- The DEFAULT is the one place that rule is written; the service inserts no
-- status, and WITH CHECK below refuses one it would not have chosen.
CREATE FUNCTION dcp_default_membership_status() RETURNS text
    LANGUAGE sql STABLE
    RETURN CASE WHEN dcp_has('user.approve') THEN 'active' ELSE 'pending_approval' END;
ALTER TABLE platform_org_membership
    ALTER COLUMN status SET DEFAULT dcp_default_membership_status();

-- A supervisor creates enumerators (§3.2), which is granting the Enumerator
-- role in their own team — bounded below to roles inside their own authority
-- and teams inside their own scope, which is what makes it safe to hold.
INSERT INTO role_permission (role_id, permission)
SELECT r.id, 'user.assign_role' FROM role r WHERE r.builtin AND r.name = 'Supervisor'
ON CONFLICT DO NOTHING;

-- ============================================================================
-- 4. The policies
-- ============================================================================

-- People: in scope, created by me, or me. Creating one needs user.create and
-- names the creator, so that the person is visible to whoever made them
-- before any team membership does.
SELECT dcp_policy('platform_user',
    'organization_id = dcp_principal(''app.org_id'') AND ('
    '  dcp_org_wide() OR dcp_in_list(''app.visible_user_ids'', id)'
    '  OR created_by = dcp_principal(''app.user_id'') OR id = dcp_principal(''app.user_id''))',
    'organization_id = dcp_principal(''app.org_id'') AND ('
    '  dcp_org_wide() OR dcp_in_list(''app.visible_user_ids'', id)'
    '  OR id = dcp_principal(''app.user_id'')'
    '  OR (created_by = dcp_principal(''app.user_id'') AND dcp_has(''user.create'')))');

-- Memberships: seen with the person; each state is a permission's to set.
SELECT dcp_policy('platform_org_membership',
    'organization_id = dcp_principal(''app.org_id'') AND user_id IN (SELECT id FROM platform_user)',
    'organization_id = dcp_principal(''app.org_id'') AND user_id IN (SELECT id FROM platform_user)'
    ' AND ((status = ''pending_approval'' AND dcp_has(''user.create''))'
    '   OR (status = ''active'' AND dcp_has(''user.approve''))'
    '   OR (status = ''deactivated'' AND dcp_has(''user.deactivate'')))');

-- Sessions: the one rule, through the one function.
SELECT dcp_policy('platform_session', 'dcp_membership_active(user_id)', 'dcp_membership_active(user_id)');

-- Grants: inside the grantor's own authority and scope.
SELECT dcp_policy('user_role',
    'role_id IN (SELECT id FROM role) AND user_id IN (SELECT id FROM platform_user)',
    'role_id IN (SELECT id FROM role) AND user_id IN (SELECT id FROM platform_user)'
    ' AND dcp_has(''user.assign_role'')'
    ' AND NOT EXISTS (SELECT 1 FROM role_permission rp'
    '                  WHERE rp.role_id = user_role.role_id AND NOT dcp_has(rp.permission))'
    ' AND ((scope_kind = ''organization'' AND dcp_org_wide())'
    '   OR (scope_kind = ''project'' AND (dcp_org_wide() OR dcp_in_list(''app.project_ids'', project_id)))'
    '   OR (scope_kind = ''team'' AND (dcp_org_wide() OR dcp_in_list(''app.team_ids'', team_id)'
    '        OR team_id IN (SELECT t.id FROM team t WHERE dcp_in_list(''app.project_ids'', t.project_id)))))');

-- Project membership: within the adder's scope. A pending person may be
-- added to a team (§3.3): nothing here reads the membership's status.
SELECT dcp_policy('project_member',
    'project_id IN (SELECT id FROM project) AND user_id IN (SELECT id FROM platform_user)',
    'project_id IN (SELECT id FROM project) AND user_id IN (SELECT id FROM platform_user)'
    ' AND (dcp_org_wide() OR dcp_in_list(''app.project_ids'', project_id)'
    '      OR dcp_in_list(''app.team_ids'', team_id))');

-- Teams: seen through the project; made with team.manage, within scope.
SELECT dcp_policy('team',
    'project_id IN (SELECT id FROM project)',
    'project_id IN (SELECT id FROM project) AND dcp_has(''team.manage'')'
    ' AND (dcp_org_wide() OR dcp_in_list(''app.project_ids'', project_id)'
    '      OR dcp_in_list(''app.team_ids'', parent_team_id))');

-- Roles: an organisation's own. A custom role is made and edited by
-- user.assign_role; the standard roles are provisioning's and stay as made.
SELECT dcp_policy('role',
    'organization_id = dcp_principal(''app.org_id'')',
    'organization_id = dcp_principal(''app.org_id'') AND dcp_has(''user.assign_role'') AND NOT builtin');
SELECT dcp_restrict('role', 'builtin_kept', 'DELETE', 'NOT builtin');

-- A role carries only permissions its editor holds — in, and out.
SELECT dcp_policy('role_permission',
    'role_id IN (SELECT id FROM role)',
    'role_id IN (SELECT id FROM role) AND dcp_has(''user.assign_role'') AND dcp_has(permission)'
    ' AND NOT (SELECT r.builtin FROM role r WHERE r.id = role_permission.role_id)');
SELECT dcp_restrict('role_permission', 'builtin_kept', 'DELETE',
    'NOT (SELECT r.builtin FROM role r WHERE r.id = role_permission.role_id)');
SELECT dcp_restrict('role_permission', 'own_authority', 'DELETE',
    'dcp_has(''user.assign_role'') AND dcp_has(permission)');
