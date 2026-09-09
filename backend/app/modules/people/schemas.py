"""Wire types for /people, /teams and /roles (pilot scope §3).

What a screen needs to render a person, a team and a role — and nothing a
screen would have to keep. The statuses are the database's closed sets,
mirrored the way `SubmissionStatus` is.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.auth.schemas import Permission, ScopeKind

type MembershipStatus = Literal["active", "pending_approval", "deactivated"]
type MembershipKind = Literal["permanent", "temporary"]
type GrantScope = Literal["organization", "project", "team"]


class Grant(BaseModel):
    """A role held in a scope."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    role_id: str = Field(serialization_alias="roleId")
    role_name: str = Field(serialization_alias="roleName")
    scope_kind: GrantScope = Field(serialization_alias="scopeKind")
    project_id: str | None = Field(serialization_alias="projectId")
    team_id: str | None = Field(serialization_alias="teamId")
    team_name: str | None = Field(serialization_alias="teamName")
    granted_at: str = Field(serialization_alias="grantedAt")


class TeamMembership(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    project_id: str = Field(serialization_alias="projectId")
    team_id: str | None = Field(serialization_alias="teamId")
    team_name: str | None = Field(serialization_alias="teamName")


class Person(BaseModel):
    """A person as the asker may see them: the policies decide who is here."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    username: str | None
    display_name: str = Field(serialization_alias="displayName")
    membership_status: MembershipStatus = Field(serialization_alias="membershipStatus")
    membership_kind: MembershipKind = Field(serialization_alias="membershipKind")
    #: Who created them, and when — what a supervisor reads to know their
    #: person is waiting on someone else, not lost.
    created_by: str | None = Field(serialization_alias="createdBy")
    created_by_name: str | None = Field(serialization_alias="createdByName")
    created_at: str = Field(serialization_alias="createdAt")
    approved_by_name: str | None = Field(serialization_alias="approvedByName")
    approved_at: str | None = Field(serialization_alias="approvedAt")
    deactivated_at: str | None = Field(serialization_alias="deactivatedAt")
    last_login_at: str | None = Field(serialization_alias="lastLoginAt")
    grants: list[Grant]
    teams: list[TeamMembership]


class PersonListResponse(BaseModel):
    people: list[Person]


class CreatePersonRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    username: str = Field(min_length=1, max_length=200)
    display_name: str = Field(alias="displayName", min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=1000)
    #: The role they hold, in the scope the role's kind names. A team-scope
    #: role needs `teamId`; a project-scope role needs `projectId`.
    role_id: str = Field(alias="roleId", min_length=1)
    project_id: str | None = Field(default=None, alias="projectId")
    team_id: str | None = Field(default=None, alias="teamId")
    membership_kind: MembershipKind = Field(default="permanent", alias="membershipKind")


class GrantRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    role_id: str = Field(alias="roleId", min_length=1)
    project_id: str | None = Field(default=None, alias="projectId")
    team_id: str | None = Field(default=None, alias="teamId")


#: Why a request was refused by the database rather than the route: the
#: policies read the same authority the screen shows, and this is what it
#: reads as when they disagree.
type PeopleFailure = Literal["outside_your_authority", "not_found", "already_exists"]


class PeopleError(BaseModel):
    reason: PeopleFailure
    message: str


class PeopleErrorResponse(BaseModel):
    detail: PeopleError


# --- teams -------------------------------------------------------------------


class TeamMember(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    user_id: str = Field(serialization_alias="userId")
    display_name: str = Field(serialization_alias="displayName")
    membership_status: MembershipStatus = Field(serialization_alias="membershipStatus")


class Team(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    project_id: str = Field(serialization_alias="projectId")
    name: str
    parent_team_id: str | None = Field(serialization_alias="parentTeamId")
    members: list[TeamMember]


class TeamListResponse(BaseModel):
    teams: list[Team]


class CreateTeamRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    project_id: str = Field(alias="projectId", min_length=1)
    name: str = Field(min_length=1, max_length=200)
    parent_team_id: str | None = Field(default=None, alias="parentTeamId")


class AddTeamMemberRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    user_id: str = Field(alias="userId", min_length=1)


# --- roles -------------------------------------------------------------------


class Role(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    scope_kind: ScopeKind = Field(serialization_alias="scopeKind")
    builtin: bool
    permissions: list[Permission]
    #: Whether the asker may grant this role: every permission it carries is
    #: one they hold. The database enforces the same rule; this is so a
    #: screen offers what will be accepted.
    grantable: bool


class RoleListResponse(BaseModel):
    roles: list[Role]


class CreateRoleRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1, max_length=200)
    scope_kind: GrantScope = Field(alias="scopeKind")
    permissions: list[Permission] = Field(default_factory=list)


class RolePermissionsRequest(BaseModel):
    permissions: list[Permission]
