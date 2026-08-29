"""Device self-registration (specs/sync-protocol-v0.1.md §4).

A fresh install generates a device id the server has never seen; without a
registration step every op it pushes is rejected `not_authorized`. Registration
is idempotent — a device that re-registers (reinstall, lost flag) gets
`already_registered`, which clients treat as success — but a revoked device can
never register its way back in.

Phase 0 has no enrollment tokens or authentication yet, so a device attaches to
the deployment's single active project and an unassigned user; a deployment
with several projects must enroll devices explicitly (spec §11).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Device, Project
from app.modules.projects.schemas import (
    DeviceRegisterRequest,
    DeviceRegisterResponse,
    RegisterFailure,
)

# Placeholder until enrollment binds a real user; user_id has no FK.
_UNASSIGNED_USER = "usr_unassigned"

_SEED_HINT = "Run scripts/seed_dev.py to create the development project."


class RegistrationError(Exception):
    """A refusal a client can act on: `reason` is the contract, `message` explains."""

    def __init__(self, status_code: int, reason: RegisterFailure, message: str) -> None:
        super().__init__(f"{reason}: {message}")
        self.status_code = status_code
        self.reason: RegisterFailure = reason
        self.message = message


async def _sole_project_id(session: AsyncSession) -> str:
    projects = (
        (
            await session.execute(
                select(Project.id)
                .where(Project.archived_at.is_(None))
                .order_by(Project.created_at, Project.id)
                .limit(2)
            )
        )
        .scalars()
        .all()
    )
    if not projects:
        raise RegistrationError(
            409,
            "project_not_found",
            f"The server has no active project to register this device against. {_SEED_HINT}",
        )
    if len(projects) > 1:
        # Attaching to an arbitrary project would silently misfile field data.
        raise RegistrationError(
            409,
            "project_ambiguous",
            "Several active projects exist, so the target cannot be inferred. "
            "Enroll the device against a specific project.",
        )
    return projects[0]


async def register_device(
    session: AsyncSession, request: DeviceRegisterRequest
) -> DeviceRegisterResponse:
    device = await session.get(Device, request.device_id)
    if device is not None:
        if device.revoked_at is not None:
            raise RegistrationError(
                403,
                "device_revoked",
                "This device has been revoked and cannot re-register.",
            )
        # A known device whose project no longer resolves to its own means the
        # database changed underneath it (reseeded, restored, pointed
        # elsewhere). Silently accepting would file its ops under a project it
        # was never enrolled in.
        expected_project_id = await _sole_project_id(session)
        if device.project_id != expected_project_id:
            raise RegistrationError(
                409,
                "project_mismatch",
                f"Device is registered to project {device.project_id}, but this server "
                f"resolves to {expected_project_id}. Clear the device's local database "
                "to enroll it afresh.",
            )
        # Refresh the diagnostic metadata; identity and project stay fixed.
        device.platform = request.platform
        device.os_version = request.os_version or device.os_version
        device.app_version = request.app_version or device.app_version
        return DeviceRegisterResponse(
            device_id=device.id, project_id=device.project_id, status="already_registered"
        )

    device = Device(
        id=request.device_id,
        project_id=await _sole_project_id(session),
        user_id=_UNASSIGNED_USER,
        platform=request.platform,
        os_version=request.os_version,
        app_version=request.app_version,
    )
    session.add(device)
    await session.flush()
    return DeviceRegisterResponse(
        device_id=device.id, project_id=device.project_id, status="registered"
    )
