-- 014: a case is held only by someone who can work it.
--
-- Found in item 2's browser run, not by a test: a supervisor assigned a case
-- to a person whose organisation membership was pending approval, and the
-- database accepted it. `dcp_person_under_live_team` (012) checked the
-- person's PROJECT membership was active and said nothing about their
-- ORGANISATION membership — the one the session policy reads, the one that
-- decides whether they can sign in at all. Someone who cannot sign in cannot
-- collect, so a case held by them is a case nobody is working, and the
-- supervisor's list shows it as covered.
--
-- One rule, one place: the same `dcp_membership_active` the session policy
-- uses (010), added to the function every person assignment already passes
-- through. Approval and deactivation therefore govern assignment with no
-- second copy of the state. A deactivated person's LIVE assignments are not
-- released here — that is the audit question A2 left with the previous
-- holder, and it is for the supervisor to reassign, visibly.

CREATE OR REPLACE FUNCTION dcp_person_under_live_team(the_case text, person text) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public
    RETURN dcp_membership_active(person)
       AND EXISTS (SELECT 1 FROM assignment a
                   JOIN project_member pm ON pm.team_id = a.team_id AND pm.user_id = person
                   WHERE a.case_id = the_case AND a.released_at IS NULL
                     AND a.team_id IS NOT NULL AND pm.status = 'active');
