-- 012: cases — a sample row, held at two levels, and everything under it in
-- scope exactly when it is.
--
-- The analysis is docs/phase3-item2-sample-assignment.md; this file is its
-- §5 written down. The question it answers first: what would pass every
-- test? The assignment boundary and the data boundary drifting apart — a case
-- policy on assignment beside a submission policy on created_by, so that a
-- case moved from team A to team B leaves its submissions with A, or takes
-- them away from the enumerator who is still collecting them. Every screen
-- test passes either way, because a screen shows a case or a submission and
-- never the relation. So there is one rule, `dcp_case_in_scope`, and every
-- table under a case reads it; a submission's visibility is its case's, and
-- `created_by` matters only for uncased work and for the person who made it.
--
-- Nothing moves on reassignment. Rows under a case never carry a scope; the
-- assignment is the only row that names a holder; reassigning releases one
-- assignment and writes another, in one function, and the view moves because
-- the row it was derived from moved. History follows the case (A1). A person
-- always sees what they created, so ops in flight after a move are accepted;
-- the one scope refusal is opening NEW work on a case not assigned to me.
--
-- Two things the database holds rather than a service enforces (A3): at most
-- one live team assignment and at most one live person assignment per case
-- (two partial unique indexes), and a person assignment only under a live
-- team assignment to a team the person is in (a policy). Deleting a case is
-- refused outright: a withdrawn sample row closes its case and leaves a
-- tombstone, so the work collected against it stays explicable.
--
-- Devices are not scoped here. A device row carries no answers, registration
-- is anonymous by design (proposal §4), and item 5's monitoring is where "a
-- supervisor sees their team's devices" is a requirement; it gets its policy
-- there, with the registration path in view.

-- ============================================================================
-- 1. The case: which sample it came from, and a closed set of states
-- ============================================================================

ALTER TABLE case_record
    ADD COLUMN dataset_key text,
    ADD CONSTRAINT case_record_status_check
        CHECK (status IN ('open', 'closed', 'withdrawn')),
    -- A case made from a sample row names its sample; one without a sample
    -- has no key either. A sample row's case is unique per project by the
    -- (project_id, case_key) constraint 001 already carries.
    ADD CONSTRAINT case_record_sample_check
        CHECK ((dataset_key IS NULL) = (case_key IS NULL));

-- ============================================================================
-- 2. Assignment: two levels, one table, one live holder per level
-- ============================================================================

-- Exactly one of the two: a row is a team assignment or a person assignment,
-- never both and never neither. 001 allowed both.
ALTER TABLE assignment DROP CONSTRAINT assignment_target_check;
ALTER TABLE assignment ADD CONSTRAINT assignment_target_check
    CHECK ((user_id IS NULL) <> (team_id IS NULL));

-- A3, held by the database: at most one live holder per level per case.
CREATE UNIQUE INDEX assignment_live_team_idx
    ON assignment (case_id) WHERE released_at IS NULL AND team_id IS NOT NULL;
CREATE UNIQUE INDEX assignment_live_person_idx
    ON assignment (case_id) WHERE released_at IS NULL AND user_id IS NOT NULL;

-- ============================================================================
-- 3. The rule, and the two smaller ones beside it
-- ============================================================================
--
-- SECURITY DEFINER for the reason 010's auth-path functions are: a case's
-- policy reading assignment, whose policy reads the case, is a recursion
-- PostgreSQL refuses. Each reads the assignment rows of one case directly,
-- scoped by the principal's own settings, and is the one place the rule is.

-- Whether the asker may see this case and everything under it. The second
-- axis (analysis §3.2): held by me — the enumerator's boundary, assigned to
-- me and nothing else — or held by a team I assign within, which is what
-- sample.assign means; a programme manager sees the project's cases, split
-- or not; an administrator everything.
CREATE FUNCTION dcp_case_in_scope(the_case text) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public
    RETURN dcp_org_wide()
        OR EXISTS (SELECT 1 FROM case_record c
                   WHERE c.id = the_case AND dcp_in_list('app.project_ids', c.project_id))
        OR EXISTS (SELECT 1 FROM assignment a
                   WHERE a.case_id = the_case AND a.released_at IS NULL
                     AND (a.user_id = dcp_principal('app.user_id')
                          OR (dcp_has('sample.assign')
                              AND (dcp_in_list('app.team_ids', a.team_id)
                                   OR dcp_in_list('app.visible_user_ids', a.user_id)))));

-- Whether this case is assigned to the asker personally: what opening new
-- work against it needs.
CREATE FUNCTION dcp_case_assigned_to_me(the_case text) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public
    RETURN EXISTS (SELECT 1 FROM assignment a
                   WHERE a.case_id = the_case AND a.released_at IS NULL
                     AND a.user_id = dcp_principal('app.user_id'));

-- Whether a person may hold this case: there is a live team assignment on it
-- to a team the person is an active member of.
CREATE FUNCTION dcp_person_under_live_team(the_case text, person text) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public
    RETURN EXISTS (SELECT 1 FROM assignment a
                   JOIN project_member pm ON pm.team_id = a.team_id AND pm.user_id = person
                   WHERE a.case_id = the_case AND a.released_at IS NULL
                     AND a.team_id IS NOT NULL AND pm.status = 'active');

REVOKE ALL ON FUNCTION dcp_case_in_scope(text), dcp_case_assigned_to_me(text),
    dcp_person_under_live_team(text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION dcp_case_in_scope(text), dcp_case_assigned_to_me(text),
    dcp_person_under_live_team(text, text) TO dcp_app;

-- ============================================================================
-- 4. The two writers: invoker rights, so the policies below apply inside
-- ============================================================================

-- Reassignment is release-and-write in one statement, at one level. A team
-- assignment releases the live person assignment too: the person was in the
-- old team, and a person assignment is valid only under a live team
-- assignment to a team they are in — the policy would refuse it, this keeps
-- the row honest. Returns the new assignment's id. Every statement runs under
-- the caller's principal and the assignment policy, so a supervisor cannot
-- release what they do not hold or write what is outside their scope.
CREATE FUNCTION dcp_assign_case(the_case text, to_team text, to_person text, new_id text)
    RETURNS text
    LANGUAGE plpgsql AS $$
BEGIN
    IF (to_team IS NULL) = (to_person IS NULL) THEN
        RAISE EXCEPTION 'dcp_assign_case: exactly one of to_team, to_person';
    END IF;
    IF to_team IS NOT NULL THEN
        UPDATE assignment SET released_at = now()
         WHERE case_id = the_case AND released_at IS NULL AND user_id IS NOT NULL;
        UPDATE assignment SET released_at = now()
         WHERE case_id = the_case AND released_at IS NULL AND team_id IS NOT NULL;
        INSERT INTO assignment (id, case_id, team_id, assigned_by)
        VALUES (new_id, the_case, to_team, nullif(dcp_principal('app.user_id'), ''));
    ELSE
        UPDATE assignment SET released_at = now()
         WHERE case_id = the_case AND released_at IS NULL AND user_id IS NOT NULL;
        INSERT INTO assignment (id, case_id, user_id, assigned_by)
        VALUES (new_id, the_case, to_person, nullif(dcp_principal('app.user_id'), ''));
    END IF;
    RETURN new_id;
END
$$;

-- The sample's rows become cases, once, and stay across re-uploads: a key
-- the project already has keeps its case (and its assignments and its
-- submissions); a new key makes a case; a key no longer in the sample
-- withdraws its case and leaves a tombstone. `withdrawn` is a state, never a
-- delete. Ids for new cases are supplied by the caller (client-generated
-- ULIDs, ERD §2), one per key, in the key's order.
CREATE FUNCTION dcp_upsert_cases(the_project text, the_dataset text, keys text[], ids text[])
    RETURNS TABLE (created integer, reopened integer, withdrawn integer)
    LANGUAGE plpgsql AS $$
DECLARE
    n_created integer;
    n_reopened integer;
    n_withdrawn integer;
BEGIN
    IF array_length(keys, 1) IS DISTINCT FROM array_length(ids, 1) THEN
        RAISE EXCEPTION 'dcp_upsert_cases: one id per key';
    END IF;
    WITH incoming AS (SELECT unnest(keys) AS k, unnest(ids) AS i),
    inserted AS (
        INSERT INTO case_record (id, project_id, dataset_key, case_key)
        SELECT i, the_project, the_dataset, k FROM incoming
        WHERE NOT EXISTS (SELECT 1 FROM case_record c
                          WHERE c.project_id = the_project AND c.case_key = incoming.k)
        RETURNING 1
    )
    SELECT count(*) INTO n_created FROM inserted;
    WITH reopened_rows AS (
        UPDATE case_record c SET status = 'open', closed_at = NULL
        WHERE c.project_id = the_project AND c.dataset_key = the_dataset
          AND c.status = 'withdrawn' AND c.case_key = ANY (keys)
        RETURNING 1
    )
    SELECT count(*) INTO n_reopened FROM reopened_rows;
    WITH gone AS (
        UPDATE case_record c SET status = 'withdrawn', closed_at = now()
        WHERE c.project_id = the_project AND c.dataset_key = the_dataset
          AND c.status <> 'withdrawn' AND NOT (c.case_key = ANY (keys))
        RETURNING c.id
    ),
    stones AS (
        INSERT INTO tombstone (id, project_id, subject_type, subject_id)
        SELECT 'TS' || substr(md5(random()::text || id), 1, 24), the_project, 'case', id
        FROM gone
        RETURNING 1
    )
    SELECT count(*) INTO n_withdrawn FROM stones;
    RETURN QUERY SELECT n_created, n_reopened, n_withdrawn;
END
$$;

-- ============================================================================
-- 5. The policies
-- ============================================================================

-- Cases: seen in scope; made by the sample upload, in the project; closed or
-- withdrawn, never deleted.
SELECT dcp_policy('case_record',
    'dcp_case_in_scope(id)',
    'dcp_has(''sample.upload'') AND (dcp_org_wide() OR dcp_in_list(''app.project_ids'', project_id))');
SELECT dcp_restrict('case_record', 'never_deleted', 'DELETE', 'false');

-- Assignments: seen with the case; written within the assigner's scope, at
-- the level their scope allows — a team, in my project; a person I may see,
-- under a live team assignment to a team they are in. A release is an
-- update, and the released row is held to the same check.
SELECT dcp_policy('assignment',
    'dcp_case_in_scope(case_id)',
    'dcp_has(''sample.assign'') AND dcp_case_in_scope(case_id) AND ('
    '   (team_id IS NOT NULL'
    '      AND (dcp_org_wide()'
    '           OR team_id IN (SELECT t.id FROM team t WHERE dcp_in_list(''app.project_ids'', t.project_id))))'
    ' OR (user_id IS NOT NULL'
    '      AND (dcp_org_wide() OR dcp_in_list(''app.visible_user_ids'', user_id))'
    '      AND dcp_person_under_live_team(case_id, user_id)))');

-- Visits: with the case.
SELECT dcp_policy('visit', 'dcp_case_in_scope(case_id)', 'dcp_case_in_scope(case_id)');

-- Submissions: the case's scope when there is a case; the creator's own,
-- always; the team's uncased work for someone who may view submissions.
-- Opening one against a case needs that case assigned to me. Everything
-- under a submission — ops, state, keys, media, flags, reviews — chains
-- through it unchanged, which is how the pull, the export and the review
-- queue all answer from this one rule.
SELECT dcp_policy('submission',
    'project_id IN (SELECT id FROM project) AND ('
    '   dcp_org_wide()'
    ' OR created_by = dcp_principal(''app.user_id'')'
    ' OR (case_id IS NOT NULL AND dcp_case_in_scope(case_id))'
    ' OR (case_id IS NULL AND dcp_has(''submission.view'')'
    '     AND dcp_in_list(''app.visible_user_ids'', created_by)))',
    'project_id IN (SELECT id FROM project) AND ('
    '   dcp_org_wide()'
    ' OR (created_by = dcp_principal(''app.user_id'')'
    '     AND (case_id IS NULL OR dcp_case_assigned_to_me(case_id))))');
