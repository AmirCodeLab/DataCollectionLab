"""Wire types for device self-registration (specs/sync-protocol-v0.1.md §4).

The wire format is camelCase; models alias to the backend's snake_case.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DevicePlatform = Literal["android", "ios", "desktop", "web"]


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
    status: Literal["registered", "already_registered"]
