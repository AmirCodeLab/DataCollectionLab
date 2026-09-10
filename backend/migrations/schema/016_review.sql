-- 016: the review loop gets its policies, its provenance and its reviewer
-- (item 6). Nothing here is a new table.
--
-- `quality_rule`, `quality_flag` and `review` have existed since 001 with ORM
-- models and no writer. Item 6 gives them one, and three things have to be
-- true before that is safe: they have to be scoped like everything else, a
-- flag has to say which rule raised it *as that rule was at the time*, and a
-- rule that could not be evaluated has to be a recorded fact rather than an
-- absence.

-- ===========================================================================
-- 1. The pilot's reviewers are supervisors
-- ===========================================================================
--
-- 008 gave `submission.review` to Admin and Programme manager and stopped
-- there, on the reading that review is a back-office activity. It is not the
-- one RCons run: the supervisor gets the list and reviews as they go, in the
-- field, which is the same place they already live during fieldwork — so it
-- is also the person item 5's dashboard was built for. Admin and Programme
-- manager keep it; this widens, it does not move.
--
-- Same shape as 010's `user.assign_role` grant: an INSERT against the builtin
-- roles of every organisation, idempotent.

INSERT INTO role_permission (role_id, permission)
SELECT r.id, 'submission.review' FROM role r WHERE r.builtin AND r.name = 'Supervisor'
ON CONFLICT DO NOTHING;

-- ===========================================================================
-- 2. A flag says what was checked, by which rule, as it then was
-- ===========================================================================
--
-- `quality_flag.rule_id` is `ON DELETE SET NULL`, which loses the answer at
-- exactly the moment it matters. A rule edited or disabled after a review
-- would otherwise rewrite the history of the review that was made under it:
-- either the old flags stay and cannot say what raised them, or they are
-- recomputed and a submission somebody approved yesterday is flagged today
-- with no record of the change. So the flag carries the rule's name and its
-- definition **as evaluated**, and neither is a foreign key.
--
-- `outcome` is the second half and the more important one. A flag row today
-- means "this rule was violated". The server cannot read a `field_level` or
-- `project_e2e` submission — the console decrypts in the browser with a key
-- the server has never held — so for those projects a rule referencing an
-- encrypted path cannot be evaluated at all. Reporting that as a pass is the
-- same lie as item 5's "0 flags outstanding" card with nothing behind it,
-- except that a human has now approved on the strength of it.
--
-- So "I could not say" is one of the things a rule can say, and it is a row
-- rather than a column somewhere else. That keeps one path: the count of
-- unevaluated rules and the list of them are the same query, which is item
-- 5's D1 applied to this table.

ALTER TABLE quality_flag
    ADD COLUMN outcome text NOT NULL DEFAULT 'violation',
    ADD COLUMN rule_name text,
    ADD COLUMN rule_definition jsonb;

ALTER TABLE quality_flag
    ADD CONSTRAINT quality_flag_outcome_check
        CHECK (outcome IN ('violation', 'not_evaluated'));

-- The open-flags index is what item 5's count reads. A row that could not be
-- evaluated is not an outstanding violation and must not be counted as one,
-- so the partial index narrows with the column rather than beside it.
DROP INDEX IF EXISTS quality_flag_open_idx;
CREATE INDEX quality_flag_open_idx
    ON quality_flag (submission_id)
    WHERE resolved_at IS NULL AND outcome = 'violation';

CREATE INDEX quality_flag_unevaluated_idx
    ON quality_flag (submission_id)
    WHERE resolved_at IS NULL AND outcome = 'not_evaluated';

-- ===========================================================================
-- 3. Which submissions a reviewer is asked to look at
-- ===========================================================================
--
-- Reviewing everything is what makes SurveyCTO slow and is the thing RCons is
-- buying their way out of; reviewing only what is flagged is the
-- differentiator. It is still a setting rather than a constant, because a
-- pilot will want to watch the rules for a week before trusting them.
--
-- One column on `project`, not a settings table. It changes the queue's
-- filter, never its shape.

ALTER TABLE project
    ADD COLUMN review_policy text NOT NULL DEFAULT 'flagged';

ALTER TABLE project
    ADD CONSTRAINT project_review_policy_check
        CHECK (review_policy IN ('flagged', 'all'));

-- ===========================================================================
-- 4. The policies
-- ===========================================================================
--
-- All three tables are unpoliced today, which was harmless only while nothing
-- wrote them. Each chains to the row it is about, so each inherits a scope
-- that is already decided and already tested: a flag and a review inherit
-- item 2's submission scope — a supervisor sees their team's work and an
-- enumerator sees their own — and a rule inherits its project.
--
-- Reading and writing are separated for two of them, because "may see this
-- submission" and "may pass judgement on it" are different facts and item 1
-- put that distinction on the principal. The refusal is the database's.

-- A rule is visible to anyone who can see the project, and written only by
-- somebody who manages it.
SELECT dcp_policy('quality_rule',
    'project_id IN (SELECT id FROM project)',
    'project_id IN (SELECT id FROM project) AND dcp_has(''project.manage'')');

-- A flag is visible with its submission, and written only along with one.
-- Deliberately NOT gated on submission.review: flags are raised by the push
-- that carries the work, under the enumerator's own principal, and an
-- enumerator holds no permission at all. The submission is theirs, which is
-- the whole of the authority needed to record what the rules said about it.
SELECT dcp_policy_chain('quality_flag', 'submission_id', 'submission');

-- A review decision is visible with its submission and written only by
-- somebody holding submission.review. This is the one that matters: it is
-- the permission the console screen will check, and a check in a screen is
-- not a guarantee (defect 26, one surface up).
SELECT dcp_policy('review',
    'submission_id IN (SELECT id FROM submission)',
    'submission_id IN (SELECT id FROM submission) AND dcp_has(''submission.review'')');

-- ===========================================================================
-- 5. A reviewer may change a submission's status, and nothing else about it
-- ===========================================================================
--
-- 012 wrote `submission`'s WITH CHECK for the only writer there was: a device
-- pushing its own work. `created_by = me AND the case is mine` is exactly
-- right for that and admits nobody else — so a supervisor who may *see* a
-- submission cannot write to it, and the review decision fails on the status
-- UPDATE with "new row violates row-level security policy".
--
-- Found by the loop test, not by reading. The decision, the `review` row and
-- the status move in one transaction, and the first two succeeded.
--
-- So the write side gains the reviewer, bounded the same way the read side
-- is: somebody holding `submission.review` may write a submission they can
-- already see. It is not a widening of what anybody can read. The USING
-- clause is unchanged and is repeated here verbatim, because `dcp_policy`
-- replaces the whole policy and a WITH CHECK written alone would silently
-- drop the read side.
--
-- What stops a reviewer rewriting the answers is that they never touch them:
-- answers live in `submission_op`, which is append-only and whose policy this
-- does not go near. A status is the only column a decision writes.

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
    '     AND (case_id IS NULL OR dcp_case_assigned_to_me(case_id)))'
    ' OR (dcp_has(''submission.review'') AND ('
    '        (case_id IS NOT NULL AND dcp_case_in_scope(case_id))'
    '     OR (case_id IS NULL'
    '         AND dcp_in_list(''app.visible_user_ids'', created_by)))))');

-- Append-only, the same way `submission_op` is. A review trail that can be
-- edited is not a trail, and "who decided what, when" is the only reason
-- these rows exist.
SELECT dcp_restrict('review', 'review_is_append_only', 'UPDATE', 'false');
SELECT dcp_restrict('review', 'review_is_never_deleted', 'DELETE', 'false');
