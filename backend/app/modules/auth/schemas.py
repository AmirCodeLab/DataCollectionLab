"""Wire types for /auth (proposal §3, §4).

`Permission` is the closed set from `role_permission_name_check` in
008_identity.sql (+ 009), mirrored here the way `SubmissionStatus` mirrors its
CHECK constraint, and generated into the console's contract as `PERMISSIONS`:
a screen checks a permission by name from that list and never a role.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

type Permission = Literal[
    "user.create",
    "user.approve",
    "user.deactivate",
    "user.assign_role",
    "team.manage",
    "sample.upload",
    "sample.assign",
    "form.edit",
    "form.publish",
    "form.deploy",
    "submission.view",
    "submission.review",
    "export.download",
    "device.revoke",
    "project.manage",
]

#: The same set, iterable — the courtesy check and the seed read it.
PERMISSIONS: tuple[str, ...] = (
    "user.create",
    "user.approve",
    "user.deactivate",
    "user.assign_role",
    "team.manage",
    "sample.upload",
    "sample.assign",
    "form.edit",
    "form.publish",
    "form.deploy",
    "submission.view",
    "submission.review",
    "export.download",
    "device.revoke",
    "project.manage",
)

type SessionKind = Literal["console", "app"]

type ScopeKind = Literal["organization", "project", "team", "none"]

#: Why a login was refused. `pending_approval` and `deactivated` are the
#: membership's status, read after the session policy refused the row — the
#: refusal itself is the policy's, not a check here (008_identity.sql §7).
type LoginFailure = Literal[
    "invalid_credentials",
    "pending_approval",
    "deactivated",
    "no_membership",
    "device_unknown",
    "device_revoked",
    "device_required",
]


class LoginRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=1000)
    #: `console` from the web console; `app` from a handset, which must also
    #: name its device — the login binds it (proposal §4).
    kind: SessionKind = "console"
    device_id: str | None = Field(default=None, alias="deviceId", max_length=64)
    #: Which organisation this login is for. Absent means the deployment's
    #: configured one (ORGANIZATION_SLUG); multi-tenant provisioning is what
    #: makes it required, from the hostname or from this field.
    organization: str | None = Field(default=None, max_length=200)


class LoginError(BaseModel):
    reason: LoginFailure
    message: str


class LoginErrorResponse(BaseModel):
    detail: LoginError


class Me(BaseModel):
    """Who this session is, and what it may do. Everything a screen needs to
    decide what to render; nothing it needs to keep."""

    model_config = ConfigDict(populate_by_name=True)

    user_id: str = Field(serialization_alias="userId")
    username: str | None
    display_name: str = Field(serialization_alias="displayName")
    organization_id: str = Field(serialization_alias="organizationId")
    organization_slug: str = Field(serialization_alias="organizationSlug")
    session_kind: SessionKind = Field(serialization_alias="sessionKind")
    device_id: str | None = Field(serialization_alias="deviceId")
    scope_kind: ScopeKind = Field(serialization_alias="scopeKind")
    permissions: list[Permission]
    expires_at: str = Field(serialization_alias="expiresAt")


class LogoutResponse(BaseModel):
    status: Literal["logged_out"]
