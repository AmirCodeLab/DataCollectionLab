-- 009: one more permission, `project.manage`.
--
-- Mapping the routes to the closed set in 008 §4 found two that no permission
-- covered: a project's recovery keys (create, revoke, list) and its media
-- policy. Neither is a form, a sample or a submission; both change what a
-- project *is*. Rather than borrow `device.revoke` because it happens to be
-- admin-only, the set gains the name for the thing. The Admin and Programme
-- manager roles hold it, in every organisation that has them, and the mirror
-- in app/modules/auth/schemas.py grows by the same line.

ALTER TABLE role_permission DROP CONSTRAINT role_permission_name_check;
ALTER TABLE role_permission ADD CONSTRAINT role_permission_name_check
    CHECK (permission IN (
        'user.create', 'user.approve', 'user.deactivate', 'user.assign_role',
        'team.manage',
        'sample.upload', 'sample.assign',
        'form.edit', 'form.publish', 'form.deploy',
        'submission.view', 'submission.review',
        'export.download',
        'device.revoke',
        'project.manage'
    ));

INSERT INTO role_permission (role_id, permission)
SELECT r.id, 'project.manage'
FROM role r
WHERE r.builtin AND r.name IN ('Admin', 'Programme manager')
ON CONFLICT DO NOTHING;
