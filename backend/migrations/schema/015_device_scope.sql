-- 015: a device belongs to the person who signed in on it, and the number a
-- panel reports about devices is scoped like the list beside it (item 5).
--
-- ===========================================================================
-- 1. The device policy gains the person
-- ===========================================================================
--
-- Until now `device` chained to `project` and nothing finer (008), so any
-- project member saw every handset in the project — the last table in the
-- schema outside the team boundary. Migration 012 parked this here on
-- purpose: a device row carries no answers, and "a supervisor sees their
-- team's devices" is a monitoring requirement, so it gets its policy where
-- the monitoring is, with the registration path in view.
--
-- No new column is needed. `device.user_id` has carried the signed-in person
-- since item 1 binds it at login, so the chain device -> person -> team
-- already exists, and the policy is the shape `submission`'s uncased branch
-- already uses: `dcp_in_list('app.visible_user_ids', user_id)`.
--
-- ---------------------------------------------------------------------------
-- USING and WITH CHECK are deliberately different. Do not make them match.
-- ---------------------------------------------------------------------------
--
-- Reading a device is scoped to the person holding it. Writing one is not,
-- and cannot be: `POST /api/v1/devices` is public and anonymous by design
-- (proposal §4, and it is one of the three pinned public routes). A handset
-- registers BEFORE anybody has signed in on it, so at INSERT there is no
-- person to name and the row is written with `user_id IS NULL`. A check that
-- demanded the row belong to the principal would refuse every first
-- registration on earth.
--
-- A later reader will meet this asymmetry, read it as an oversight, and make
-- the two sides match. That change breaks enrolment for every new device, and
-- nothing below the API can see it: the failure is a fresh handset that
-- cannot register, on a path with no session and no principal. This paragraph
-- is here for that reader. It is the same class as the bidi isolates once
-- removed as cosmetic (docs/known-breaks.md 55) — a thing that looks like an
-- accident, is not, and gets tidied away unless the reason sits where the
-- change would be made.
--
-- An unbound device therefore belongs to nobody and is visible only
-- org-wide, which is the honest answer: it is in no supervisor's team because
-- it is in nobody's hands yet. The consequence for monitoring is that the
-- device panel's count and its list must both come from this one policy, or
-- they disagree for exactly the rows nobody owns.

SELECT dcp_policy('device',
    'project_id IN (SELECT id FROM project) AND ('
    '   dcp_org_wide()'
    ' OR dcp_in_list(''app.visible_user_ids'', user_id))',
    'project_id IN (SELECT id FROM project) AND ('
    '   dcp_org_wide()'
    ' OR user_id IS NULL'
    ' OR user_id = dcp_principal(''app.user_id''))');

-- ===========================================================================
-- 2. A number this server did not compute
-- ===========================================================================
--
-- Pending ops live in the device's outbox. `device.last_counter` is the
-- highest logical counter this server has ACCEPTED and says nothing about
-- what is queued behind it: ops created since the last successful push have
-- never been mentioned to it, and the gap is invisible for exactly those.
-- No query can fix that, because the number is not in this database.
--
-- So the device reports it, and the columns are named for what they are. A
-- column called `pending_ops` sitting beside `last_counter` would be read as
-- this server's own count inside a month, and a dashboard would then report
-- "0 pending" for a handset holding forty unsent interviews — which is worse
-- than reporting nothing, because it is trusted. `reported_at` is not
-- `updated_at` for the same reason: it is when the DEVICE said so, not when
-- this row was touched, and a screen that renders the figure without it is
-- rendering a claim with no date on it.

ALTER TABLE device
    ADD COLUMN reported_pending_ops integer,
    ADD COLUMN reported_at timestamptz;

-- ===========================================================================
-- 3. The four statements that must work before anybody has signed in
-- ===========================================================================
--
-- The policy above cannot be seen through by a principal with no person on
-- it, and there are exactly four places where that principal is the only one
-- there is:
--
--   * registration checks whether the handset is already known;
--   * registration CREATES the row;
--   * registration refreshes its platform metadata;
--   * the LOGIN reads the row it is about to bind — at login there is no
--     session yet, which is what the login is for.
--
-- The second of those was missed when this migration was written, on the
-- reasoning that the write policy admits `user_id IS NULL` and so the insert
-- needs nothing. It does not: an `INSERT ... RETURNING` is a write AND a
-- read, PostgreSQL applies the read policy to the returned row, and refuses
-- it reporting the WRITE policy's error — "new row violates row-level
-- security policy" — which sends the next reader to the wrong clause. The
-- ORM returns the server-side defaults on every insert, so the path was
-- always a RETURNING. A fresh handset answered HTTP 500 and no test saw it,
-- because every API test drives the app organisation-wide.
--
-- These are definer functions for the same reason `dcp_login_lookup` and
-- `dcp_session_lookup` are (010): the authentication path cannot be asked to
-- authenticate itself first. Each is one statement, narrow, and named for the
-- caller that needs it, so widening the policy was never the alternative.
--
-- The one that binds only ever writes the person doing the login, so it
-- cannot be used to hand somebody else's handset to a third party.

CREATE FUNCTION dcp_device_by_id(the_device text)
    RETURNS TABLE (id text, project_id text, user_id text, revoked_at timestamptz)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public
    AS $$
        SELECT d.id, d.project_id, d.user_id, d.revoked_at
        FROM device d WHERE d.id = the_device;
    $$;

CREATE FUNCTION dcp_device_register(the_device text, the_project text,
                                    the_platform text, the_os text, the_app text)
    RETURNS TABLE (id text, project_id text)
    LANGUAGE sql SECURITY DEFINER SET search_path = public
    AS $$
        INSERT INTO device (id, project_id, user_id, platform, os_version, app_version)
        VALUES (the_device, the_project, NULL, the_platform, the_os, the_app)
        RETURNING device.id, device.project_id;
    $$;

CREATE FUNCTION dcp_device_seen(the_device text, the_platform text,
                                the_os text, the_app text) RETURNS void
    LANGUAGE sql SECURITY DEFINER SET search_path = public
    AS $$
        UPDATE device
           SET platform = the_platform,
               os_version = coalesce(the_os, os_version),
               app_version = coalesce(the_app, app_version)
         WHERE id = the_device;
    $$;

CREATE FUNCTION dcp_bind_device(the_device text, person text) RETURNS void
    LANGUAGE sql SECURITY DEFINER SET search_path = public
    AS $$
        UPDATE device SET user_id = person, bound_at = now() WHERE id = the_device;
    $$;

-- The registering function writes `user_id NULL` and nothing else: it cannot
-- be called to hand a handset to a person, which is what keeps a definer
-- function on a public route narrow enough to be safe.

REVOKE ALL ON FUNCTION dcp_device_by_id(text),
    dcp_device_register(text, text, text, text, text),
    dcp_device_seen(text, text, text, text),
    dcp_bind_device(text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION dcp_device_by_id(text),
    dcp_device_register(text, text, text, text, text),
    dcp_device_seen(text, text, text, text),
    dcp_bind_device(text, text) TO dcp_app;
