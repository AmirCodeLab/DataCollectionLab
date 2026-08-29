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

from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.ulid import new_ulid
from app.modules.crypto.envelope import is_usable_recipient_key
from app.modules.crypto.models import ProjectKey
from app.modules.crypto.published_test_keys import refusal_for_test_only_key
from app.modules.projects.models import Device, Project
from app.modules.projects.schemas import (
    DeviceCryptoResponse,
    DeviceRegisterRequest,
    DeviceRegisterResponse,
    KeyRole,
    ProjectKeyCreate,
    ProjectKeyDetail,
    ProjectKeyListResponse,
    ProjectKeyOut,
    ProjectListResponse,
    ProjectSummary,
    RegisterFailure,
    SecurityMode,
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


class RecipientSetError(Exception):
    """The project's recipient set is unusable, so no device may wrap to it."""

    def __init__(self, status_code: int, reason: str, message: str) -> None:
        super().__init__(f"{reason}: {message}")
        self.status_code = status_code
        self.reason = reason
        self.message = message


async def device_crypto(session: AsyncSession, device_id: str) -> DeviceCryptoResponse | None:
    """The project's security mode and the public keys to wrap to (sync §4).

    None when the device is unknown or revoked — a device the server will not
    accept ops from has no business learning a project's key set either.

    Raises RecipientSetError when the set holds a key whose private half is
    published (see `crypto/published_test_keys.py`) and this is not a
    development environment. Refusing here rather than at registration alone
    matters because the usual way such a key arrives is not registration: it is
    a development database that got promoted, or a dump restored somewhere it
    should not have been. Silently dropping the key instead would be worse than
    either — the device would wrap to a set nobody chose, and a recovery holder
    would find out years later that their copy was never written.
    """
    device = await session.get(Device, device_id)
    if device is None or device.revoked_at is not None:
        return None

    project = await session.get(Project, device.project_id)
    if project is None:
        return None

    keys = (
        (
            await session.execute(
                select(ProjectKey)
                .where(
                    ProjectKey.project_id == project.id,
                    ProjectKey.revoked_at.is_(None),
                )
                .order_by(ProjectKey.created_at, ProjectKey.id)
            )
        )
        .scalars()
        .all()
    )

    environment = get_settings().environment
    for key in keys:
        refusal = refusal_for_test_only_key(environment, bytes(key.public_key), key.label)
        if refusal is not None:
            raise RecipientSetError(
                409,
                "test_only_key",
                f"Project {project.id} holds recipient key {key.id} ({key.key_role}, "
                f"{key.label!r}), which cannot be used here. {refusal} Revoke that "
                "key before devices sync; submissions already wrapped to it must "
                "be treated as readable by anyone.",
            )

    return DeviceCryptoResponse(
        device_id=device.id,
        project_id=project.id,
        # Both of these are constrained by CHECK constraints in the schema;
        # the ORM types the columns as plain text.
        security_mode=cast(SecurityMode, project.security_mode),
        project_keys=[
            ProjectKeyOut(
                key_id=key.id,
                public_key=bytes(key.public_key).hex(),
                role=cast(KeyRole, key.key_role),
                label=key.label,
            )
            for key in keys
        ],
    )


class KeyRegistrationError(Exception):
    """A refusal a console can show verbatim. `reason` is the contract."""

    def __init__(self, status_code: int, reason: str, message: str) -> None:
        super().__init__(f"{reason}: {message}")
        self.status_code = status_code
        self.reason = reason
        self.message = message


async def list_projects(session: AsyncSession, *, include_archived: bool) -> ProjectListResponse:
    """Every project with its security mode and how many recipients it has.

    The key count is the number that matters operationally: a project in an
    encrypting mode with zero active keys cannot receive data at all — its
    devices refuse to push rather than send answers in the clear.
    """
    statement = select(Project).order_by(Project.name, Project.slug)
    if not include_archived:
        statement = statement.where(Project.archived_at.is_(None))
    projects = (await session.execute(statement)).scalars().all()

    counts: dict[str, int] = {}
    if projects:
        rows = await session.execute(
            select(ProjectKey.project_id, func.count())
            .where(
                ProjectKey.project_id.in_([p.id for p in projects]),
                ProjectKey.revoked_at.is_(None),
            )
            .group_by(ProjectKey.project_id)
        )
        counts = {project_id: count for project_id, count in rows}

    return ProjectListResponse(
        projects=[
            ProjectSummary(
                id=project.id,
                name=project.name,
                slug=project.slug,
                security_mode=cast(SecurityMode, project.security_mode),
                active_key_count=counts.get(project.id, 0),
                created_at=project.created_at,
                archived_at=project.archived_at,
            )
            for project in projects
        ]
    )


def _key_detail(key: ProjectKey) -> ProjectKeyDetail:
    return ProjectKeyDetail(
        key_id=key.id,
        project_id=key.project_id,
        public_key=bytes(key.public_key).hex(),
        role=cast(KeyRole, key.key_role),
        label=key.label,
        created_at=key.created_at,
        revoked_at=key.revoked_at,
    )


async def list_project_keys(
    session: AsyncSession, project_id: str, *, include_revoked: bool
) -> ProjectKeyListResponse | None:
    """The project's recipient keys. None when there is no such project."""
    project = await session.get(Project, project_id)
    if project is None:
        return None

    statement = select(ProjectKey).where(ProjectKey.project_id == project_id)
    if not include_revoked:
        statement = statement.where(ProjectKey.revoked_at.is_(None))
    keys = (
        (await session.execute(statement.order_by(ProjectKey.created_at, ProjectKey.id)))
        .scalars()
        .all()
    )

    return ProjectKeyListResponse(
        project_id=project.id,
        security_mode=cast(SecurityMode, project.security_mode),
        keys=[_key_detail(key) for key in keys],
    )


async def add_project_key(
    session: AsyncSession, project_id: str, request: ProjectKeyCreate
) -> ProjectKeyDetail:
    """Register a public key as a recipient (encryption envelope §4.1, §4.3).

    Public keys only, and this is the only way one gets in. The server never
    generates a project keypair: it would hold the private half at the moment of
    creation, and `project_e2e` would be a promise the architecture could not
    keep.
    """
    project = await session.get(Project, project_id)
    if project is None:
        raise KeyRegistrationError(404, "project_not_found", f"No project {project_id}.")
    if project.archived_at is not None:
        raise KeyRegistrationError(
            409, "project_archived", "An archived project takes no new keys."
        )

    public_key = bytes.fromhex(request.public_key)
    if not is_usable_recipient_key(public_key):
        # A small-order point drives every exchange to an all-zero secret, so
        # this "recipient" would be one anybody could impersonate — while
        # looking on every screen like real redundancy.
        raise KeyRegistrationError(
            422,
            "degenerate_public_key",
            "That public key cannot carry a shared secret. It is a small-order "
            "point, not a usable X25519 key — generate a fresh keypair.",
        )

    duplicate = (
        await session.execute(
            select(ProjectKey).where(
                ProjectKey.project_id == project_id,
                ProjectKey.public_key == public_key,
                ProjectKey.revoked_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        # Wrapping twice to one holder is not redundancy. Accepting it would
        # let a project show three recipients and lose everything to one lost
        # laptop (§4.3).
        raise KeyRegistrationError(
            409,
            "duplicate_public_key",
            f"That public key is already registered as {duplicate.id} "
            f"({duplicate.key_role}, {duplicate.label!r}). A second copy of one "
            "key is not a second recipient.",
        )

    refusal = refusal_for_test_only_key(get_settings().environment, public_key, request.label)
    if refusal is not None:
        # A published private key beside real data is not a degraded guarantee,
        # it is no guarantee — and it looks identical to a real recipient on
        # every screen that lists one.
        raise KeyRegistrationError(422, "test_only_key", refusal)

    key = ProjectKey(
        id=new_ulid(),
        project_id=project_id,
        public_key=public_key,
        key_role=request.role,
        label=request.label,
    )
    session.add(key)
    await session.flush()
    await session.refresh(key)
    return _key_detail(key)
