-- The four builtin roles and what each may do. ONE definition (gate 1, A7).
--
-- Executed for one organisation, by whoever is standing it up:
--   * scripts/provision.py, for a real deployment;
--   * scripts/seed_dev.py, for the development database.
-- Both go through `app.modules.auth.builtin_roles.install`, and
-- `backend/tests/test_builtin_roles_have_one_definition.py` fails if a third
-- writer of `role` or `role_permission` appears anywhere outside this file.
--
-- ---------------------------------------------------------------------------
-- Why this file exists, and why the migrations are not rewritten
-- ---------------------------------------------------------------------------
--
-- These grants were written in four places: 008_identity.sql creates the roles
-- and their permissions, 010_people.sql adds `user.assign_role` to Supervisor,
-- 016_review.sql adds `submission.review` to Supervisor, and the dev seed
-- carried its own copy of the whole set. Kept in step by hand, four times.
--
-- Measured on 11 September before this file existed, the four copies **agreed
-- exactly** — so nothing here is a reconciliation, and no list was wrong. What
-- they had was no mechanism, and a permission set that four people maintain by
-- remembering is one where the fifth copy is silent: every screen works and a
-- supervisor simply cannot review.
--
-- The migrations stay exactly as they are. They are an append-only record of
-- what happened to databases that already exist, and rewriting history to
-- point at a file that did not exist then would be a lie about what ran. This
-- is what anything standing up an organisation **now** executes. A future
-- migration that changes a builtin permission edits this file and re-runs it
-- for the organisations that exist.
--
-- `:org` is the organisation id, bound by the caller. Idempotent: running it
-- twice changes nothing, so it is safe to re-run after adding a permission.

INSERT INTO role (id, organization_id, name, scope_kind, builtin)
SELECT :org || '_' || r.suffix, :org, r.name, r.scope_kind, true
FROM (VALUES ('admin',      'Admin',             'organization'),
             ('pm',         'Programme manager', 'project'),
             ('supervisor', 'Supervisor',        'team'),
             ('enumerator', 'Enumerator',        'team'))
     AS r(suffix, name, scope_kind)
ON CONFLICT (id) DO NOTHING;

-- Admin: everything. Programme manager: everything but device.revoke — a
-- revoked device is an operational act with a support call behind it.
-- Supervisor (§3.2, 010 §3, 016 §1): creates enumerators in their own team,
-- assigns sample, sees submissions, and REVIEWS them, because in RCons the
-- supervisor is the reviewer. A supervisor does NOT hold user.approve, which
-- is how the approval flow falls out of the model rather than being enforced.
-- Enumerator: nothing at all — an enumerator's access is their device's
-- session, not a grant.
INSERT INTO role_permission (role_id, permission)
SELECT r.id, p.name
FROM role r,
     (VALUES ('user.create'), ('user.approve'), ('user.deactivate'),
             ('user.assign_role'), ('team.manage'), ('sample.upload'),
             ('sample.assign'), ('form.edit'), ('form.publish'),
             ('form.deploy'), ('submission.view'), ('submission.review'),
             ('export.download'), ('device.revoke'), ('project.manage'))
     AS p(name)
WHERE r.organization_id = :org AND r.builtin AND (
    r.name = 'Admin'
    OR (r.name = 'Programme manager' AND p.name <> 'device.revoke')
    OR (r.name = 'Supervisor' AND p.name IN
        ('user.create', 'user.assign_role', 'sample.assign',
         'submission.view', 'submission.review'))
)
ON CONFLICT DO NOTHING;
