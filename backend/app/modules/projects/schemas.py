"""Wire types for device self-registration (specs/sync-protocol-v0.1.md §4).

The wire format is camelCase; models alias to the backend's snake_case.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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


class DeviceRegisterError(BaseModel):
    """Body of a failed registration, under the usual `detail` key."""

    model_config = ConfigDict(populate_by_name=True)

    reason: RegisterFailure
    # Prose for a human reading a log or an app's sync error; says what to do
    # about it. Never parsed.
    message: str
