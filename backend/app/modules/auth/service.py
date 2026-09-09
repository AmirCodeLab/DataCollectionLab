"""Login, the session, and the principal a person's roles amount to.

Three rules, each somewhere a query cannot skip:

- **Whether a person may hold a session is the session policy's decision,
  not this module's.** `login` inserts the `platform_session` row and lets
  `008_identity.sql` §7 refuse it: a `pending_approval` or `deactivated`
  membership fails WITH CHECK, and that failure is the refusal. The membership
  status is read afterwards only to *name* the reason in the response. There
  is deliberately no `if status != 'active'` before the insert — one rule, one
  place, and a second copy here would be the one that drifts.
- **A deactivated person is logged out by the policy.** Their session rows
  stop being visible under USING, so `resolve` finds nothing and the next
  request is a 401. No revoke job, nothing to forget.
- **Scope is a policy on the connection, not a filter in a query** (proposal
  §5). What this module computes from `user_role` is the *principal* —
  `scope_kind` and `visible_user_ids` — and hands it to the connection layer;
  `submission`'s policy reads it there, on every query, including the export
  nobody thought of.

The organisation is known before any of this runs: the session this module is
handed is already scoped to one (`app.api.access.get_db`), so `platform_user`
is readable by username under the ordinary policy and never by an
unrestricted read (ERD §1).
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import insert, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ulid import new_ulid
from app.infrastructure.database import Principal
from app.modules.auth.models import PlatformSession, PlatformUser
from app.modules.auth.passwords import verify_password
from app.modules.auth.schemas import LoginFailure
from app.modules.projects.models import Device

#: The handset's placeholder before it knows who holds it (`SubmissionStore`
#: default). The server attributes such ops to the session's person.
LOCAL_ACTOR = "usr_local"

#: How often `last_used_at` is written: a sliding expiry costs a write per
#: request otherwise, and five minutes of slack on a thirty-day window is
#: nothing.
TOUCH_INTERVAL = timedelta(minutes=5)


class LoginRefused(Exception):
    """A refusal a client can act on: `reason` is the contract, `message` explains."""

    def __init__(self, status_code: int, reason: LoginFailure, message: str) -> None:
        super().__init__(f"{reason}: {message}")
        self.status_code = status_code
        self.reason: LoginFailure = reason
        self.message = message


@dataclass(frozen=True)
class Identity:
    """A resolved session: the person, the principal their roles amount to,
    and the permissions the courtesy check reads."""

    session_id: str
    user_id: str
    username: str | None
    display_name: str
    kind: str
    device_id: str | None
    principal: Principal
    permissions: frozenset[str]
    expires_at: datetime


@dataclass(frozen=True)
class Login:
    token: str
    identity: Identity


def hash_token(token: str) -> str:
    """The cookie carries the token; the row holds its hash, so a copy of the
    table logs nobody in. SHA-256 is right here — the token is 256 bits of
    entropy, not a password — and argon2 would only slow every request."""
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------------------
# The principal a person's roles amount to
# ---------------------------------------------------------------------------

_SCOPE_SQL = text(
    """
    WITH RECURSIVE grants AS (
        SELECT ur.scope_kind, ur.project_id, ur.team_id
        FROM user_role ur
        WHERE ur.user_id = :user_id AND ur.revoked_at IS NULL
    ),
    teams AS (
        SELECT g.team_id AS id FROM grants g WHERE g.team_id IS NOT NULL
        UNION
        SELECT t.id FROM team t JOIN teams ON t.parent_team_id = teams.id
    )
    SELECT
        (SELECT bool_or(scope_kind = 'organization') FROM grants) AS org_wide,
        (SELECT bool_or(scope_kind = 'project') FROM grants) AS project_wide,
        (SELECT bool_or(scope_kind = 'team') FROM grants) AS team_wide,
        (SELECT coalesce(array_agg(DISTINCT pm.user_id), '{}')
           FROM project_member pm
          WHERE pm.status = 'active'
            AND (pm.project_id IN (SELECT project_id FROM grants WHERE scope_kind = 'project')
                 OR pm.team_id IN (SELECT id FROM teams))) AS visible
    """
)

_PERMISSIONS_SQL = text(
    """
    SELECT DISTINCT rp.permission
    FROM user_role ur
    JOIN role_permission rp ON rp.role_id = ur.role_id
    WHERE ur.user_id = :user_id AND ur.revoked_at IS NULL
    """
)


async def principal_for(
    session: AsyncSession, user: PlatformUser, org_slug: str
) -> tuple[Principal, frozenset[str]]:
    """The widest live grant decides `scope_kind`; the people in every granted
    project and team (and its sub-teams) are `visible_user_ids`, plus the
    person themself — one's own work is always one's own to see."""
    row = (await session.execute(_SCOPE_SQL, {"user_id": user.id})).mappings().one()
    if row["org_wide"]:
        scope_kind = "organization"
    elif row["project_wide"]:
        scope_kind = "project"
    elif row["team_wide"]:
        scope_kind = "team"
    else:
        scope_kind = ""
    visible = tuple(sorted({user.id, *row["visible"]}))
    permissions = frozenset(
        (await session.execute(_PERMISSIONS_SQL, {"user_id": user.id})).scalars()
    )
    principal = Principal(
        org_id=user.organization_id,
        org_slug=org_slug,
        user_id=user.id,
        scope_kind=scope_kind,
        visible_user_ids=visible,
    )
    return principal, permissions


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


def _is_policy_refusal(error: DBAPIError) -> bool:
    return "row-level security" in str(error.orig)


async def login(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    kind: str,
    device_id: str | None,
    org_slug: str,
    ttl: timedelta,
) -> Login:
    user = (
        await session.execute(select(PlatformUser).where(PlatformUser.username == username))
    ).scalar_one_or_none()
    # One answer for "no such person" and "wrong password", and the hash is
    # checked either way so the two take the same time.
    if not verify_password(user.password_hash if user else None, password) or user is None:
        raise LoginRefused(401, "invalid_credentials", "Wrong username or password.")

    if kind == "app":
        if device_id is None:
            raise LoginRefused(400, "device_required", "An app login must name its device.")
        device = await session.get(Device, device_id)
        if device is None:
            raise LoginRefused(
                403, "device_unknown", "This device has not registered. Sync once first."
            )
        if device.revoked_at is not None:
            raise LoginRefused(403, "device_revoked", "This device has been revoked.")

    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    session_id = new_ulid()
    expires_at = now + ttl
    try:
        # The gate. One INSERT inside a SAVEPOINT, so that a refusal leaves
        # the transaction usable for reading the reason. A statement rather
        # than a flush: a failed flush closes the session's transaction, a
        # failed statement inside a savepoint closes only the savepoint.
        async with session.begin_nested():
            await session.execute(
                insert(PlatformSession).values(
                    id=session_id,
                    user_id=user.id,
                    kind=kind,
                    device_id=device_id if kind == "app" else None,
                    token_hash=hash_token(token),
                    expires_at=expires_at,
                )
            )
    except DBAPIError as error:
        if not _is_policy_refusal(error):
            raise
        status = (
            await session.execute(
                text(
                    "SELECT status FROM platform_org_membership "
                    "WHERE user_id = :user_id AND organization_id = :org_id"
                ),
                {"user_id": user.id, "org_id": user.organization_id},
            )
        ).scalar_one_or_none()
        if status == "pending_approval":
            raise LoginRefused(
                403,
                "pending_approval",
                "This account is waiting for approval by an administrator.",
            ) from error
        if status == "deactivated":
            raise LoginRefused(403, "deactivated", "This account has been deactivated.") from error
        raise LoginRefused(
            403, "no_membership", "This account is not a member of the organisation."
        ) from error

    if kind == "app":
        # Registered is not bound (proposal §4): the login is what binds the
        # device to a person, and the app session names it.
        device = await session.get(Device, device_id)
        assert device is not None
        device.user_id = user.id
        device.bound_at = now
    user.last_login_at = now

    principal, permissions = await principal_for(session, user, org_slug)
    identity = Identity(
        session_id=session_id,
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        kind=kind,
        device_id=device_id if kind == "app" else None,
        principal=principal,
        permissions=permissions,
        expires_at=expires_at,
    )
    return Login(token=token, identity=identity)


# ---------------------------------------------------------------------------
# Every request after that
# ---------------------------------------------------------------------------


async def resolve(
    session: AsyncSession, token: str, *, org_slug: str, ttl: timedelta
) -> Identity | None:
    """The identity a cookie names, or None.

    None covers every way a session stops being one: no such token, expired,
    revoked, and — with no code here about it — a membership that is no
    longer active, because the policy on `platform_session` hides the row.
    """
    now = datetime.now(UTC)
    row = (
        await session.execute(
            select(PlatformSession).where(
                PlatformSession.token_hash == hash_token(token),
                PlatformSession.revoked_at.is_(None),
                PlatformSession.expires_at > now,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    user = await session.get(PlatformUser, row.user_id)
    if user is None:
        return None
    if row.last_used_at is None or now - row.last_used_at > TOUCH_INTERVAL:
        row.last_used_at = now
        row.expires_at = now + ttl
    principal, permissions = await principal_for(session, user, org_slug)
    return Identity(
        session_id=row.id,
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        kind=row.kind,
        device_id=row.device_id,
        principal=principal,
        permissions=permissions,
        expires_at=row.expires_at,
    )


async def logout(session: AsyncSession, session_id: str) -> None:
    row = await session.get(PlatformSession, session_id)
    if row is not None and row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        row.revoked_reason = "logout"
