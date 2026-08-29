"""Wire types for device self-registration (specs/sync-protocol-v0.1.md §4).

The wire format is camelCase; models alias to the backend's snake_case.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.crypto.envelope import PUBLIC_KEY_BYTES

DevicePlatform = Literal["android", "ios", "desktop", "web"]

# Machine-readable outcomes. Clients branch on these, never on the prose in
# `message`, and never on the status code alone — a bare 409 gave a developer
# no way to tell "you forgot to seed the database" from "this device belongs
# somewhere else".
RegisterStatus = Literal["registered", "already_registered"]
RegisterFailure = Literal[
    # No project exists to attach the device to — almost always an unseeded
    # database (scripts/seed_dev.py).
    "project_not_found",
    # Several projects exist and nothing says which one; enrollment must be
    # explicit rather than guessed.
    "project_ambiguous",
    # The device is already registered to a different project than the one it
    # would resolve to now — typically a reseeded or swapped database.
    "project_mismatch",
    "device_revoked",
]


class DeviceRegisterRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    device_id: str = Field(alias="deviceId", min_length=1, max_length=64)
    platform: DevicePlatform
    os_version: str | None = Field(default=None, alias="osVersion", max_length=200)
    app_version: str | None = Field(default=None, alias="appVersion", max_length=200)


class DeviceRegisterResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    device_id: str = Field(serialization_alias="deviceId")
    project_id: str = Field(serialization_alias="projectId")
    status: RegisterStatus


# Both mirror CHECK constraints in migrations/schema/001_initial.sql.
SecurityMode = Literal["standard", "field_level", "project_e2e"]
KeyRole = Literal["primary", "backup", "recovery"]


class ProjectKeyOut(BaseModel):
    """One recipient a content key must be wrapped to (envelope §4.1).

    Public keys only. The private half is generated in the browser at project
    creation, downloaded by the user, and never transmitted to the server —
    so there is nothing secret to leak here.
    """

    model_config = ConfigDict(populate_by_name=True)

    key_id: str = Field(serialization_alias="keyId")
    public_key: str = Field(serialization_alias="publicKey")  # 32 bytes, hex
    role: KeyRole
    label: str


class DeviceCryptoResponse(BaseModel):
    """What a device needs before it can encrypt anything (sync §4).

    Fetched every sync rather than once at registration: rotation (envelope §8)
    adds keys that a device registered last month would otherwise never wrap
    to, and a submission wrapped to a stale recipient set is data its intended
    recovery holder cannot open.
    """

    model_config = ConfigDict(populate_by_name=True)

    device_id: str = Field(serialization_alias="deviceId")
    project_id: str = Field(serialization_alias="projectId")
    security_mode: SecurityMode = Field(serialization_alias="securityMode")
    # Revoked keys are never returned: revocation stops future wrapping (§8).
    project_keys: list[ProjectKeyOut] = Field(serialization_alias="projectKeys")


class ProjectSummary(BaseModel):
    """One project, enough for the console to name it and route to it."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    slug: str
    security_mode: SecurityMode = Field(serialization_alias="securityMode")
    active_key_count: int = Field(serialization_alias="activeKeyCount")
    created_at: datetime = Field(serialization_alias="createdAt")
    archived_at: datetime | None = Field(serialization_alias="archivedAt")


class ProjectListResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    projects: list[ProjectSummary]


class ProjectKeyCreate(BaseModel):
    """A public key being registered as a recipient (envelope §4.1).

    `extra="forbid"`, deliberately. The private key is generated in the browser
    and downloaded by the user; it must never reach the server. A client that
    sends one — under any field name — gets a 422 naming the field rather than
    a 201 and a silently ignored secret sitting in a request log.

    An X25519 private key is 32 bytes and so is a public key, so no server can
    tell one from the other by looking. That is exactly why the guarantee has to
    be structural: the server never asks for a private key, accepts no field
    that could carry one, and refuses anything shaped like a key container.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    # Raw X25519 public key, 32 bytes, lowercase hex — the same encoding every
    # other binary field of the envelope uses.
    public_key: str = Field(alias="publicKey")
    role: KeyRole
    # Who holds the matching private key. This is the only thing that will
    # identify the holder when someone needs the data back in two years.
    label: str = Field(min_length=1, max_length=200)

    @field_validator("public_key")
    @classmethod
    def _is_a_bare_public_key(cls, value: str) -> str:
        lowered = value.strip().lower()
        # A PEM block, a JWK, or an OpenSSH line can all carry a PRIVATE key,
        # and a server that unwrapped one would be storing the secret it exists
        # not to hold. Refuse the containers outright; take raw hex only.
        for marker in ("-----", "begin", "private", '"d"', "{", "ssh-", "pkcs"):
            if marker in lowered:
                raise ValueError(
                    "publicKey must be 32 bytes of raw hex, not a key file or "
                    "container. The private key must never leave the browser."
                )
        try:
            raw = bytes.fromhex(lowered)
        except ValueError as exc:
            raise ValueError("publicKey must be hex") from exc
        if len(raw) != PUBLIC_KEY_BYTES:
            raise ValueError(f"publicKey must be {PUBLIC_KEY_BYTES} bytes")
        return lowered


class ProjectKeyDetail(ProjectKeyOut):
    """A stored recipient key, as the console lists it."""

    model_config = ConfigDict(populate_by_name=True)

    project_id: str = Field(serialization_alias="projectId")
    created_at: datetime = Field(serialization_alias="createdAt")
    revoked_at: datetime | None = Field(serialization_alias="revokedAt")


class ProjectKeyListResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    project_id: str = Field(serialization_alias="projectId")
    security_mode: SecurityMode = Field(serialization_alias="securityMode")
    keys: list[ProjectKeyDetail]


class DeviceRegisterError(BaseModel):
    """Body of a failed registration, under the usual `detail` key."""

    model_config = ConfigDict(populate_by_name=True)

    reason: RegisterFailure
    # Prose for a human reading a log or an app's sync error; says what to do
    # about it. Never parsed.
    message: str
