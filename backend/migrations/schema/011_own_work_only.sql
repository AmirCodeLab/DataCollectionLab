-- 011: seeing other people's work is a permission.
--
-- Found on merged main, 9 September 2026, while writing item 2's analysis and
-- confirmed with a probe: an enumerator's pull carried a teammate's ops, with
-- their plaintext answers. `dcp_principal_for` (010 §2) put the people of
-- every granted team into `app.visible_user_ids` whether or not the person
-- held `submission.view`, and `submission`'s policy admits work by anyone in
-- that list. The Enumerator role is team-scoped, so an enumerator's
-- principal named their whole team. The console refused them at the route;
-- the handset's sync has no route to refuse them at, and stored the ops.
--
-- The rule, which item 1 already stated for screens (pilot scope §3.5) and
-- item 2's analysis states for the pull: visibility of other people's work
-- is a permission. A person with `submission.view` sees the people in their
-- granted projects and teams; a person without it sees themself. Nothing
-- else on the principal changes.

CREATE OR REPLACE FUNCTION dcp_principal_for(person text)
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
        ),
        held AS (
            SELECT DISTINCT rp.permission
            FROM grants g JOIN role_permission rp ON rp.role_id = g.role_id
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
                -- Other people's work is a permission: the people in scope
                -- are visible to someone who may view submissions, and to
                -- nobody else.
                SELECT pm.user_id FROM project_member pm
                WHERE EXISTS (SELECT 1 FROM held WHERE held.permission = 'submission.view')
                  AND pm.status = 'active'
                  AND (pm.project_id IN (SELECT g.project_id FROM grants g WHERE g.scope_kind = 'project')
                       OR pm.team_id IN (SELECT id FROM teams))) v),
            (SELECT coalesce(array_agg(DISTINCT g.project_id ORDER BY g.project_id), '{}')
               FROM grants g WHERE g.scope_kind = 'project'),
            (SELECT coalesce(array_agg(DISTINCT id ORDER BY id), '{}') FROM teams),
            (SELECT coalesce(array_agg(permission ORDER BY permission), '{}') FROM held)
    $$;
