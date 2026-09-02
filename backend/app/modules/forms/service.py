"""Read queries for forms, the one path a version becomes published by, and the
manifest a device syncs its forms from.

Everything that publishes — the API endpoint, scripts/seed_dev.py — goes through
`publish_version`, so a form cannot enter the database without having passed the
Form IR §10 error checks. That includes sensitivity propagation (encryption
envelope §5.2): a check that only some publish paths run is not a check.

Publishing and deploying are separate: a published version is immutable content,
and a deployment is a statement that one environment should be running it. Only
the second reaches a device. `deployed_versions_for_device` is the read side —
the manifest behind `GET /sync/pull?scope=forms` (sync §5).
"""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ulid import new_ulid
from app.modules.crypto.envelope import check_sensitivity_propagation
from app.modules.form_engine.runtime import CompiledForm
from app.modules.forms.models import Form, FormDeployment, FormVersion
from app.modules.forms.schemas import (
    DeployedFormVersion,
    EnvironmentKind,
    FormListResponse,
    FormSummary,
    FormVersionDocument,
    ImportRecord,
    PublishVersionResponse,
)
from app.modules.projects.models import Device, Environment


class PublishRefused(Exception):
    """The form is not publishable. `violations` says exactly why.

    Separate from CompileError because these are checks over an IR that already
    compiles: the form is well-formed and still must not ship.
    """

    def __init__(self, violations: list[str]) -> None:
        super().__init__("; ".join(violations))
        self.violations = violations


def ir_checksum(ir: dict[str, Any]) -> str:
    """Content address of an IR document, stable across key order.

    Algorithm-prefixed so a stored checksum stays readable when a second one
    exists. Not the envelope's canonical_json: this addresses a form document,
    not a value under a key, and the two must be free to diverge.
    """
    canonical = json.dumps(ir, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def check_publishable(ir: dict[str, Any]) -> CompiledForm:
    """Compile a form and run every check that blocks publish (Form IR §10).

    Raises CompileError for a malformed document and PublishRefused for a
    sensitivity leak — a field that is not `sensitive` reading one that is,
    which would defeat field_level encryption (envelope §5.2). The check runs
    in every security mode: a project's mode is fixed at creation, but a form
    is copied between projects, and a leak that only shows up after the copy is
    a leak that ships.
    """
    compiled = CompiledForm(ir)

    # A form with no questions in it.
    #
    # Checked here rather than in the importer because it is true of any form
    # however it arrived, and because *reporting* it is not enough — the blank
    # ODK XLSForm Template imported to a valid, compilable form with zero
    # questions and passed every check there was. It compiled, both engines
    # agreed, the vectors were green, and it would have deployed to a phone as
    # an interview with nothing to ask.
    #
    # The lesson generalises past this one case. The importer's coverage ledger
    # answers "was everything present accounted for", and is structurally blind
    # to "was anything present at all": an empty sheet has no cells to account
    # for, so the ledger is perfectly satisfied by nothing. Emptiness needs
    # asking about directly, at the gate that matters.
    if not compiled.fields:
        raise PublishRefused(
            [
                "this form has no questions, so there would be nothing to collect. "
                "A form must have at least one question to be published."
            ]
        )

    violations = check_sensitivity_propagation(compiled)
    if violations:
        raise PublishRefused(violations)
    return compiled


async def list_forms(session: AsyncSession, *, include_archived: bool) -> FormListResponse:
    """Every form with its version numbers, title order."""
    statement = select(Form).order_by(Form.title, Form.form_key)
    if not include_archived:
        statement = statement.where(Form.archived_at.is_(None))
    forms = (await session.execute(statement)).scalars().all()

    versions: dict[str, list[int]] = {}
    if forms:
        rows = await session.execute(
            select(FormVersion.form_id, FormVersion.version)
            .where(FormVersion.form_id.in_([f.id for f in forms]))
            .order_by(FormVersion.form_id, FormVersion.version)
        )
        for form_id, version in rows:
            versions.setdefault(form_id, []).append(version)

    return FormListResponse(
        forms=[
            FormSummary(
                id=form.id,
                form_id=form.form_key,
                title=form.title,
                versions=versions.get(form.id, []),
                archived_at=form.archived_at,
            )
            for form in forms
        ]
    )


async def publish_version(
    session: AsyncSession,
    *,
    project_id: str,
    ir: dict[str, Any],
    title: str | None = None,
    published_by: str | None = None,
    form_id: str | None = None,
    form_version_id: str | None = None,
    deploy_to: list[EnvironmentKind] | None = None,
    import_record: ImportRecord | None = None,
) -> PublishVersionResponse:
    """Publish one immutable form version, or explain why it cannot be.

    Idempotent by content: re-publishing a version whose IR checksum already
    matches returns the stored row untouched. Re-publishing a version number
    with *different* content is refused — published versions are immutable
    (specs/erd-v0.1.md §4), and a device in the field has that exact IR compiled
    into a submission it has not synced yet.

    `deploy_to` names the environments that should run this version. Publishing
    without it stores a version no device will ever be told about (sync §5), so
    the response reports what is actually deployed either way — the difference
    between "it is in the database" and "it is on the phones".

    `form_id` / `form_version_id` let a caller pin the row ids it wants (the dev
    seed does, so a reseed is stable); both default to fresh ULIDs.
    """
    compiled = check_publishable(ir)

    # A version imported with unresolved errors does not publish.
    #
    # The importer already returns `publishable: false` and the CLI already
    # exits 1, but both of those are advice to whoever ran them. This is the
    # server refusing, which is the difference between a report somebody may
    # not have read and a version that cannot reach a phone. Each of these
    # errors is something that changes what the form asks or collects — a
    # `relevant` that could not be translated, a question type no client can
    # present, a choice label that would be read out as `${name1}`.
    #
    # Omitting the import record is not a way round it. It is a claim that this
    # version was not imported, recorded as such in the row, and that claim is
    # what somebody reads in six months when they ask where the form came from.
    if import_record is not None:
        blocking = [d for d in import_record.diagnostics if d.severity == "error"]
        if blocking:
            raise PublishRefused(
                [
                    f"{d.message} ({d.sheet} row {d.row}, column '{d.column}')"
                    if d.sheet and d.row
                    else d.message
                    for d in blocking
                ]
            )

    checksum = ir_checksum(ir)

    form = (
        await session.execute(
            select(Form).where(Form.project_id == project_id, Form.form_key == compiled.form_id)
        )
    ).scalar_one_or_none()
    if form is None:
        default_language = ir.get("defaultLanguage", "en")
        form = Form(
            id=form_id or new_ulid(),
            project_id=project_id,
            form_key=compiled.form_id,
            title=title or ir.get("title", {}).get(default_language, compiled.form_id),
        )
        session.add(form)
        await session.flush()

    existing = (
        await session.execute(
            select(FormVersion).where(
                FormVersion.form_id == form.id, FormVersion.version == compiled.version
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.ir_checksum != checksum:
            raise PublishRefused(
                [
                    f"{compiled.form_id} v{compiled.version} is already published with "
                    f"different content ({existing.ir_checksum} != {checksum}). "
                    "Published versions are immutable — publish a new version."
                ]
            )
        return PublishVersionResponse(
            id=existing.id,
            form_id=form.form_key,
            version=existing.version,
            ir_checksum=existing.ir_checksum,
            published_at=existing.published_at,
            created=False,
            warnings=compiled.warnings,
            # Re-publishing identical content is a no-op for the version and
            # still an opportunity to deploy it: a caller correcting a form that
            # was published but never deployed asks for exactly this.
            deployments=await deploy_version(
                session, project_id=project_id, form_version_id=existing.id, kinds=deploy_to
            ),
        )

    version = FormVersion(
        id=form_version_id or new_ulid(),
        form_id=form.id,
        version=compiled.version,
        ir=ir,
        ir_checksum=checksum,
        published_at=func.now(),
        published_by=published_by,
        # All five together or all five NULL — the database enforces it. A
        # version published from hand-written IR was not imported, and NULL is
        # the honest record of that rather than an empty report claiming an
        # import that found nothing wrong.
        import_source_name=import_record.source_name if import_record else None,
        import_source_sha256=import_record.source_sha256 if import_record else None,
        import_report=(
            {
                "diagnostics": [
                    d.model_dump(by_alias=True) for d in import_record.diagnostics
                ]
            }
            if import_record
            else None
        ),
        import_importer_version=import_record.importer_version if import_record else None,
        imported_at=func.now() if import_record else None,
    )
    session.add(version)
    await session.flush()

    return PublishVersionResponse(
        id=version.id,
        form_id=form.form_key,
        version=version.version,
        ir_checksum=checksum,
        # func.now() is unresolved until the transaction commits; report the
        # publish time rather than issue a round trip to read it back.
        published_at=datetime.now(tz=UTC),
        created=True,
        warnings=compiled.warnings,
        deployments=await deploy_version(
            session, project_id=project_id, form_version_id=version.id, kinds=deploy_to
        ),
    )


async def deploy_version(
    session: AsyncSession,
    *,
    project_id: str,
    form_version_id: str,
    kinds: list[EnvironmentKind] | None,
) -> list[EnvironmentKind]:
    """Deploy one version to the named environments, and report every one it is
    now deployed to.

    Idempotent, and deliberately additive: deploying to `production` does not
    retire `staging`, because they are separate statements about separate
    environments. Retiring is its own act and has no caller yet — see
    docs/known-defects.md.

    An environment kind the project does not have is skipped rather than
    created. Environments are provisioned with the project; inventing one here
    would deploy a form to a place nothing is enrolled in, which reads as
    success and reaches nobody.
    """
    environments = {
        env.kind: env.id
        for env in (
            await session.execute(select(Environment).where(Environment.project_id == project_id))
        ).scalars()
    }

    for kind in kinds or []:
        environment_id = environments.get(kind)
        if environment_id is None:
            continue
        already = (
            await session.execute(
                select(FormDeployment).where(
                    FormDeployment.environment_id == environment_id,
                    FormDeployment.form_version_id == form_version_id,
                    FormDeployment.retired_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if already is None:
            session.add(
                FormDeployment(
                    id=new_ulid(),
                    environment_id=environment_id,
                    form_version_id=form_version_id,
                )
            )
    await session.flush()

    # `Environment.kind` is a plain text column; the CHECK constraint is what
    # keeps it inside the closed set, and mypy cannot see a CHECK constraint.
    by_id: dict[str, EnvironmentKind] = {
        env_id: cast(EnvironmentKind, kind) for kind, env_id in environments.items()
    }
    deployed = (
        await session.execute(
            select(FormDeployment.environment_id).where(
                FormDeployment.form_version_id == form_version_id,
                FormDeployment.retired_at.is_(None),
            )
        )
    ).scalars()
    # Sorted so the response does not depend on insertion order.
    return sorted(
        {by_id[env_id] for env_id in deployed if env_id in by_id},
        key=_ENVIRONMENT_ORDER.index,
    )


# Preference order when a device's environment has to be resolved, and the sort
# order for a deployment list. Mirrors _ENVIRONMENT_PREFERENCE in
# app/modules/sync/service.py, which resolves the environment a submission is
# recorded against; the two must agree, or a device would collect on forms from
# one environment and file its submissions under another.
_ENVIRONMENT_ORDER: list[EnvironmentKind] = ["production", "staging", "development"]


async def device_environment_id(session: AsyncSession, device: Device) -> str | None:
    """Which environment's forms this device runs.

    Derived from the device's project rather than stored on the device, because
    nothing yet enrolls a device into a named environment — there is no auth
    layer and no enrollment UI. The derivation is the same one the push path
    uses to file a submission (sync service `_ENVIRONMENT_PREFERENCE`), so a
    device cannot be handed forms from one environment while its data is
    recorded against another.

    That is a limitation, not a design: a project with both a staging and a
    production environment gives every device production, and there is no way to
    put one phone on staging. Filed in docs/known-defects.md.
    """
    environments = {
        env.kind: env.id
        for env in (
            await session.execute(
                select(Environment).where(Environment.project_id == device.project_id)
            )
        ).scalars()
    }
    return next((environments[k] for k in _ENVIRONMENT_ORDER if k in environments), None)


async def deployed_versions_for_device(
    session: AsyncSession, device_id: str
) -> list[DeployedFormVersion] | None:
    """The form manifest for one device (sync §5, `scope=forms`).

    Every version deployed to this device's environment and not retired —
    **versions**, plural and by design. A device keeps and must be offered every
    version it might still hold a draft against, not only the newest: a
    submission is validated against the version it was collected under (Form IR
    §9), and an enumerator can be holding a v2 draft on the morning v3 deploys.
    Sending only the latest would leave that draft unopenable on its own device.

    None when the device is unknown or revoked — the same answer
    `/devices/{id}/media-policy` gives, and for the same reason: a device the
    server will not accept data from has no business learning a project's forms.
    """
    device = (
        await session.execute(select(Device).where(Device.id == device_id))
    ).scalar_one_or_none()
    if device is None or device.revoked_at is not None:
        return None

    environment_id = await device_environment_id(session, device)
    if environment_id is None:
        return []

    rows = await session.execute(
        select(
            FormVersion.id,
            Form.form_key,
            FormVersion.version,
            Form.title,
            FormVersion.ir_checksum,
            FormDeployment.deployed_at,
        )
        .join(FormVersion, FormVersion.id == FormDeployment.form_version_id)
        .join(Form, Form.id == FormVersion.form_id)
        .where(
            FormDeployment.environment_id == environment_id,
            FormDeployment.retired_at.is_(None),
        )
        .order_by(Form.form_key, FormVersion.version)
    )
    return [
        DeployedFormVersion(
            form_version_id=row.id,
            form_id=row.form_key,
            version=row.version,
            title=row.title,
            ir_checksum=row.ir_checksum,
            deployed_at=row.deployed_at,
        )
        for row in rows
    ]


async def get_form_version(
    session: AsyncSession, form_version_id: str
) -> FormVersionDocument | None:
    """One published version and its IR, addressed by its immutable row id.

    Not scoped to a device. The manifest is what decides which versions a device
    is told to fetch; this returns the document behind an id the caller already
    holds, and the row can never change under it (specs/erd-v0.1.md §4).
    """
    row = (
        await session.execute(
            select(
                FormVersion.id,
                Form.form_key,
                FormVersion.version,
                Form.title,
                FormVersion.ir,
                FormVersion.ir_checksum,
                FormVersion.published_at,
            )
            .join(Form, Form.id == FormVersion.form_id)
            .where(FormVersion.id == form_version_id)
        )
    ).one_or_none()
    if row is None:
        return None
    return FormVersionDocument(
        form_version_id=row.id,
        form_id=row.form_key,
        version=row.version,
        title=row.title,
        ir_checksum=row.ir_checksum,
        published_at=row.published_at,
        form=row.ir,
    )
