"""People, teams and roles: writes that the database decides.

Nothing here checks whether the asker may do what they are asking. The route
has already read the courtesy permission; the policies of 010_people.sql read
the principal — the same permissions, projects and teams — on every row this
module writes, and refuse what is outside the asker's authority. A refusal
surfaces as `Refused`, which the route turns into a 403 naming it.

The one decision this module deliberately does not make: whether a new
membership is active or waiting. The column's DEFAULT does (§3.2, §3.3), from
`user.approve` on the connection, so the service inserts no status and reads
back what the database chose.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import insert, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Executable

from app.core.ulid import new_ulid
from app.infrastructure.database import Principal
from app.modules.auth.models import (
    PlatformOrgMembership,
    PlatformUser,
    RolePermission,
    UserRole,
)
from app.modules.auth.models import (
    Role as RoleRow,
)
from app.modules.auth.passwords import hash_password
from app.modules.people.schemas import (
    CreatePersonRequest,
    CreateRoleRequest,
    CreateTeamRequest,
    Grant,
    GrantRequest,
    PeopleFailure,
    Person,
    Role,
    Team,
    TeamMember,
    TeamMembership,
)
from app.modules.projects.models import ProjectMember
from app.modules.projects.models import Team as TeamRow


class Refused(Exception):
    """The database, or the data, said no: `reason` is the contract."""

    def __init__(self, status_code: int, reason: PeopleFailure, message: str) -> None:
        super().__init__(f"{reason}: {message}")
        self.status_code = status_code
        self.reason: PeopleFailure = reason
        self.message = message


def _refused_by_policy(error: DBAPIError) -> bool:
    return "row-level security" in str(error.orig)


OUTSIDE = Refused(
    403,
    "outside_your_authority",
    "The database refused this: it is outside what your roles allow — a role above your "
    "own, a team or project outside your scope, or a state only an approver may set.",
)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

_PEOPLE_SQL = text(
    """
    SELECT u.id, u.username, u.display_name, u.created_at, u.last_login_at,
           m.status, m.membership_kind, m.created_by, m.approved_by, m.approved_at,
           m.deactivated_at,
           c.display_name AS created_by_name, a.display_name AS approved_by_name
    FROM platform_user u
    JOIN platform_org_membership m ON m.user_id = u.id
    LEFT JOIN platform_user c ON c.id = m.created_by
    LEFT JOIN platform_user a ON a.id = m.approved_by
    ORDER BY (m.status = 'pending_approval') DESC, u.display_name, u.id
    """
)

_GRANTS_SQL = text(
    """
    SELECT ur.id, ur.user_id, ur.role_id, r.name AS role_name, ur.scope_kind,
           ur.project_id, ur.team_id, t.name AS team_name, ur.granted_at
    FROM user_role ur
    JOIN role r ON r.id = ur.role_id
    LEFT JOIN team t ON t.id = ur.team_id
    WHERE ur.revoked_at IS NULL
    ORDER BY ur.granted_at
    """
)

_TEAMS_OF_SQL = text(
    """
    SELECT pm.user_id, pm.project_id, pm.team_id, t.name AS team_name
    FROM project_member pm
    LEFT JOIN team t ON t.id = pm.team_id
    WHERE pm.status = 'active'
    """
)


async def list_people(session: AsyncSession) -> list[Person]:
    """Everyone the policies show the asker, with their grants and teams."""
    rows = (await session.execute(_PEOPLE_SQL)).mappings().all()
    grants: dict[str, list[Grant]] = {}
    for g in (await session.execute(_GRANTS_SQL)).mappings():
        grants.setdefault(g["user_id"], []).append(
            Grant(
                id=g["id"],
                role_id=g["role_id"],
                role_name=g["role_name"],
                scope_kind=g["scope_kind"],
                project_id=g["project_id"],
                team_id=g["team_id"],
                team_name=g["team_name"],
                granted_at=g["granted_at"].isoformat(),
            )
        )
    teams: dict[str, list[TeamMembership]] = {}
    for t in (await session.execute(_TEAMS_OF_SQL)).mappings():
        teams.setdefault(t["user_id"], []).append(
            TeamMembership(
                project_id=t["project_id"], team_id=t["team_id"], team_name=t["team_name"]
            )
        )
    return [
        Person(
            id=row["id"],
            username=row["username"],
            display_name=row["display_name"],
            membership_status=row["status"],
            membership_kind=row["membership_kind"],
            created_by=row["created_by"],
            created_by_name=row["created_by_name"],
            created_at=row["created_at"].isoformat(),
            approved_by_name=row["approved_by_name"],
            approved_at=_iso(row["approved_at"]),
            deactivated_at=_iso(row["deactivated_at"]),
            last_login_at=_iso(row["last_login_at"]),
            grants=grants.get(row["id"], []),
            teams=teams.get(row["id"], []),
        )
        for row in rows
    ]


async def get_person(session: AsyncSession, user_id: str) -> Person:
    for person in await list_people(session):
        if person.id == user_id:
            return person
    raise Refused(404, "not_found", "No such person is visible to you.")


# ---------------------------------------------------------------------------
# Writing people
# ---------------------------------------------------------------------------


async def create_person(
    session: AsyncSession, request: CreatePersonRequest, principal: Principal
) -> Person:
    """A person, their membership, their first role, and their team.

    One transaction: the person is visible to their creator through
    `created_by`, the membership's status is the database's choice, the grant
    and the team membership are refused if outside the creator's scope. A
    supervisor with one team who names none gets that team (§3.2: an
    enumerator created by a supervisor lands in that supervisor's team).
    """
    role = await session.get(RoleRow, request.role_id)
    if role is None:
        raise Refused(404, "not_found", "No such role is visible to you.")
    team_id = request.team_id
    if role.scope_kind == "team" and team_id is None and len(principal.team_ids) == 1:
        team_id = principal.team_ids[0]
    project_id = request.project_id
    if project_id is None and team_id is not None:
        team = await session.get(TeamRow, team_id)
        project_id = team.project_id if team is not None else None

    user_id = new_ulid()
    me = principal.user_id or None
    try:
        await _guarded(
            session,
            insert(PlatformUser).values(
                id=user_id,
                organization_id=principal.org_id,
                username=request.username,
                display_name=request.display_name,
                password_hash=hash_password(request.password),
                created_by=me,
            ),
        )
    except IntegrityError as error:
        raise Refused(
            409, "already_exists", f"The username {request.username!r} is taken."
        ) from error
    # No status: the DEFAULT decides from user.approve on the connection.
    await _guarded(
        session,
        insert(PlatformOrgMembership).values(
            organization_id=principal.org_id,
            user_id=user_id,
            org_role="member",
            membership_kind=request.membership_kind,
            created_by=me,
        ),
    )
    await _guarded(
        session,
        insert(UserRole).values(
            id=new_ulid(),
            user_id=user_id,
            role_id=role.id,
            scope_kind=role.scope_kind,
            project_id=project_id if role.scope_kind == "project" else None,
            team_id=team_id if role.scope_kind == "team" else None,
            granted_by=me,
        ),
    )
    if project_id is not None:
        await _guarded(
            session,
            insert(ProjectMember).values(
                project_id=project_id, user_id=user_id, team_id=team_id, added_by=me
            ),
        )
    return await get_person(session, user_id)


async def _guarded(session: AsyncSession, statement: Executable) -> int:
    """One statement inside a SAVEPOINT. A statement rather than a flush: a
    failed flush closes the session's transaction, a failed statement inside
    a savepoint closes only the savepoint, and the policy's refusal becomes
    `Refused` with the transaction still usable."""
    try:
        async with session.begin_nested():
            result = await session.execute(statement)
    except IntegrityError:
        raise
    except DBAPIError as error:
        if _refused_by_policy(error):
            raise OUTSIDE from error
        raise
    return int(getattr(result, "rowcount", 0) or 0)


async def _execute_guarded(session: AsyncSession, statement: str, params: dict[str, object]) -> int:
    """`_guarded` for raw SQL. A statement that touched no row is `not_found`
    to the caller — the row is either absent or outside the asker's view,
    which to them is the same."""
    return await _guarded(session, text(statement).bindparams(**params))


async def approve(session: AsyncSession, user_id: str, principal: Principal) -> Person:
    touched = await _execute_guarded(
        session,
        "UPDATE platform_org_membership SET status = 'active', approved_by = :me, "
        "approved_at = now() WHERE user_id = :user_id AND organization_id = :org "
        "AND status = 'pending_approval'",
        {"me": principal.user_id or None, "user_id": user_id, "org": principal.org_id},
    )
    if touched == 0:
        raise Refused(404, "not_found", "No pending membership for that person is visible to you.")
    return await get_person(session, user_id)


async def deactivate(session: AsyncSession, user_id: str, principal: Principal) -> Person:
    touched = await _execute_guarded(
        session,
        "UPDATE platform_org_membership SET status = 'deactivated', deactivated_at = now() "
        "WHERE user_id = :user_id AND organization_id = :org AND status <> 'deactivated'",
        {"user_id": user_id, "org": principal.org_id},
    )
    if touched == 0:
        raise Refused(404, "not_found", "No active membership for that person is visible to you.")
    return await get_person(session, user_id)


async def reactivate(session: AsyncSession, user_id: str, principal: Principal) -> Person:
    """§3.4: reactivation is a status change on the same person, never a
    second account. It is an approval, and needs the same permission."""
    touched = await _execute_guarded(
        session,
        "UPDATE platform_org_membership SET status = 'active', deactivated_at = NULL, "
        "approved_by = :me, approved_at = now() "
        "WHERE user_id = :user_id AND organization_id = :org AND status = 'deactivated'",
        {"me": principal.user_id or None, "user_id": user_id, "org": principal.org_id},
    )
    if touched == 0:
        raise Refused(404, "not_found", "No deactivated membership for that person is visible.")
    return await get_person(session, user_id)


async def grant(
    session: AsyncSession, user_id: str, request: GrantRequest, principal: Principal
) -> Person:
    role = await session.get(RoleRow, request.role_id)
    if role is None:
        raise Refused(404, "not_found", "No such role is visible to you.")
    await _guarded(
        session,
        insert(UserRole).values(
            id=new_ulid(),
            user_id=user_id,
            role_id=role.id,
            scope_kind=role.scope_kind,
            project_id=request.project_id if role.scope_kind == "project" else None,
            team_id=request.team_id if role.scope_kind == "team" else None,
            granted_by=principal.user_id or None,
        ),
    )
    return await get_person(session, user_id)


async def revoke(session: AsyncSession, user_id: str, grant_id: str) -> Person:
    touched = await _execute_guarded(
        session,
        "UPDATE user_role SET revoked_at = now() "
        "WHERE id = :grant_id AND user_id = :user_id AND revoked_at IS NULL",
        {"grant_id": grant_id, "user_id": user_id},
    )
    if touched == 0:
        raise Refused(404, "not_found", "No such live grant is visible to you.")
    return await get_person(session, user_id)


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------

_TEAM_MEMBERS_SQL = text(
    """
    SELECT pm.team_id, pm.user_id, u.display_name, m.status
    FROM project_member pm
    JOIN platform_user u ON u.id = pm.user_id
    JOIN platform_org_membership m ON m.user_id = u.id
    WHERE pm.status = 'active' AND pm.project_id = :project_id AND pm.team_id IS NOT NULL
    ORDER BY u.display_name
    """
)


async def list_teams(session: AsyncSession, project_id: str) -> list[Team]:
    rows = (
        await session.execute(
            select(TeamRow).where(TeamRow.project_id == project_id).order_by(TeamRow.name)
        )
    ).scalars()
    members: dict[str, list[TeamMember]] = {}
    for m in (await session.execute(_TEAM_MEMBERS_SQL, {"project_id": project_id})).mappings():
        members.setdefault(m["team_id"], []).append(
            TeamMember(
                user_id=m["user_id"], display_name=m["display_name"], membership_status=m["status"]
            )
        )
    return [
        Team(
            id=t.id,
            project_id=t.project_id,
            name=t.name,
            parent_team_id=t.parent_team_id,
            members=members.get(t.id, []),
        )
        for t in rows
    ]


async def create_team(session: AsyncSession, request: CreateTeamRequest) -> Team:
    team_id = new_ulid()
    await _guarded(
        session,
        insert(TeamRow).values(
            id=team_id,
            project_id=request.project_id,
            name=request.name,
            parent_team_id=request.parent_team_id,
        ),
    )
    return Team(
        id=team_id,
        project_id=request.project_id,
        name=request.name,
        parent_team_id=request.parent_team_id,
        members=[],
    )


async def add_team_member(
    session: AsyncSession, team_id: str, user_id: str, principal: Principal
) -> Team:
    """An existing person is selected, not created (§3.2): the project
    membership is written or moved, and no approval is involved."""
    team = await session.get(TeamRow, team_id)
    if team is None:
        raise Refused(404, "not_found", "No such team is visible to you.")
    existing = await session.get(ProjectMember, (team.project_id, user_id))
    if existing is None:
        await _guarded(
            session,
            insert(ProjectMember).values(
                project_id=team.project_id,
                user_id=user_id,
                team_id=team.id,
                added_by=principal.user_id or None,
            ),
        )
    else:
        session.expunge(existing)
        await _execute_guarded(
            session,
            "UPDATE project_member SET team_id = :team_id, status = 'active', removed_at = NULL "
            "WHERE project_id = :project_id AND user_id = :user_id",
            {"team_id": team.id, "project_id": team.project_id, "user_id": user_id},
        )
    for t in await list_teams(session, team.project_id):
        if t.id == team.id:
            return t
    raise Refused(404, "not_found", "The team is no longer visible to you.")


async def remove_team_member(session: AsyncSession, team_id: str, user_id: str) -> Team:
    team = await session.get(TeamRow, team_id)
    if team is None:
        raise Refused(404, "not_found", "No such team is visible to you.")
    touched = await _execute_guarded(
        session,
        "UPDATE project_member SET status = 'removed', removed_at = now(), team_id = NULL "
        "WHERE project_id = :project_id AND user_id = :user_id AND team_id = :team_id",
        {"project_id": team.project_id, "user_id": user_id, "team_id": team.id},
    )
    if touched == 0:
        raise Refused(404, "not_found", "That person is not in this team, as far as you can see.")
    for t in await list_teams(session, team.project_id):
        if t.id == team.id:
            return t
    raise Refused(404, "not_found", "The team is no longer visible to you.")


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


async def list_roles(session: AsyncSession, principal: Principal) -> list[Role]:
    rows = (
        await session.execute(select(RoleRow).order_by(RoleRow.builtin.desc(), RoleRow.name))
    ).scalars().all()
    permissions: dict[str, list[str]] = {}
    for rp in (await session.execute(select(RolePermission))).scalars():
        permissions.setdefault(rp.role_id, []).append(rp.permission)
    mine = set(principal.permissions)
    return [
        Role(
            id=r.id,
            name=r.name,
            scope_kind=r.scope_kind,
            builtin=r.builtin,
            permissions=sorted(permissions.get(r.id, [])),
            grantable="user.assign_role" in mine and set(permissions.get(r.id, [])) <= mine,
        )
        for r in rows
    ]


async def create_role(
    session: AsyncSession, request: CreateRoleRequest, principal: Principal
) -> Role:
    role_id = new_ulid()
    try:
        await _guarded(
            session,
            insert(RoleRow).values(
                id=role_id,
                organization_id=principal.org_id,
                name=request.name,
                scope_kind=request.scope_kind,
                builtin=False,
            ),
        )
    except IntegrityError as error:
        raise Refused(409, "already_exists", f"A role named {request.name!r} exists.") from error
    for permission in sorted(set(request.permissions)):
        await _guarded(
            session, insert(RolePermission).values(role_id=role_id, permission=permission)
        )
    for r in await list_roles(session, principal):
        if r.id == role_id:
            return r
    raise Refused(404, "not_found", "The role is no longer visible to you.")


async def set_role_permissions(
    session: AsyncSession, role_id: str, permissions: Sequence[str], principal: Principal
) -> Role:
    """The difference, row by row: each insert and each delete is the
    database's to refuse — a permission the editor lacks, a standard role."""
    role = await session.get(RoleRow, role_id)
    if role is None:
        raise Refused(404, "not_found", "No such role is visible to you.")
    wanted = set(permissions)
    current = {
        rp.permission
        for rp in (
            await session.execute(select(RolePermission).where(RolePermission.role_id == role_id))
        ).scalars()
    }
    for permission in sorted(current - wanted):
        touched = await _execute_guarded(
            session,
            "DELETE FROM role_permission WHERE role_id = :role_id AND permission = :permission",
            {"role_id": role_id, "permission": permission},
        )
        if touched == 0:
            raise OUTSIDE
    for permission in sorted(wanted - current):
        await _guarded(
            session, insert(RolePermission).values(role_id=role_id, permission=permission)
        )
    for r in await list_roles(session, principal):
        if r.id == role_id:
            return r
    raise Refused(404, "not_found", "The role is no longer visible to you.")

