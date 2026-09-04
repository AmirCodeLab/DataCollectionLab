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
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ulid import new_ulid
from app.modules.crypto.envelope import check_sensitivity_propagation
from app.modules.entities.models import Dataset, DatasetVersion, FormVersionDataset
from app.modules.form_engine.expression import forbidden_regex_feature
from app.modules.form_engine.runtime import CompiledForm
from app.modules.forms.models import Form, FormDeployment, FormVersion
from app.modules.forms.schemas import (
    DatasetPin,
    DeployedFormVersion,
    EnvironmentKind,
    FormListResponse,
    FormSummary,
    FormVersionDocument,
    ImportRecord,
    PublishVersionResponse,
)
from app.modules.projects.models import Device, Environment
from app.modules.submissions.models import Submission


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


def dataset_keys(compiled: CompiledForm) -> list[str]:
    """Every `choices.dataset` key the form names (Form IR §3), in field order.

    Read off the compiled form rather than by walking the raw document, so that
    a question the engine did not compile cannot contribute a key — a pin for a
    list nothing selects from would be a claim about the form that is not true.
    """
    found: list[str] = []
    for field_id in compiled.order:
        choices = compiled.fields[field_id].node.get("choices")
        if not isinstance(choices, dict) or choices.get("kind") != "dataset":
            continue
        key = choices.get("dataset")
        if isinstance(key, str) and key not in found:
            found.append(key)
    return found


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

    # A regex §4.6 forbids.
    #
    # This has to be refused here because evaluation can no longer report it.
    # §4.7 makes evaluation total — a pattern using lookahead is null, the
    # constraint coerces null to true (§4.4.7), and the validation an author
    # wrote silently does not happen. That is the right behaviour on a device,
    # where there is nobody to tell; it makes this the only place left that can
    # say so, and a rule that never fires is worse than no rule.
    violations = [
        f"{field_id}: the pattern {pattern!r} uses `{feature}`, which RE2 cannot "
        "express (Form IR §4.6). Backtracking on a respondent's answer is a way "
        "to hang a phone, so this pattern would never be applied — the "
        "constraint would pass for everybody."
        for field_id, pattern, feature in _forbidden_patterns(compiled)
    ]
    violations += check_sensitivity_propagation(compiled)
    if violations:
        raise PublishRefused(violations)
    return compiled


def _forbidden_patterns(compiled: CompiledForm) -> list[tuple[str, str, str]]:
    """Every `regex()` literal pattern in the form that §4.6 does not permit."""
    found: list[tuple[str, str, str]] = []

    def walk(node: Any, field_id: str) -> None:
        if not isinstance(node, dict):
            return
        if node.get("op") == "call" and node.get("fn") == "regex":
            args = node.get("args") or []
            if len(args) > 1 and isinstance(args[1], dict) and args[1].get("op") == "lit":
                pattern = args[1].get("value")
                if isinstance(pattern, str):
                    feature = forbidden_regex_feature(pattern)
                    if feature is not None:
                        found.append((field_id, pattern, feature))
        for arg in node.get("args") or []:
            walk(arg, field_id)

    for field_id, field in compiled.fields.items():
        for key in ("relevant", "constraint", "calculate", "required", "readOnly", "default"):
            walk(field.node.get(key), field_id)
    return found


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


async def _stored_dataset_pins(session: AsyncSession, form_version_id: str) -> dict[str, str]:
    """Dataset key -> dataset version id, as this form version was published."""
    rows = await session.execute(
        select(FormVersionDataset.dataset_key, FormVersionDataset.dataset_version_id).where(
            FormVersionDataset.form_version_id == form_version_id
        )
    )
    return {key: version_id for key, version_id in rows}


async def _resolve_dataset_pins(
    session: AsyncSession,
    *,
    project_id: str,
    compiled: CompiledForm,
    requested: list[DatasetPin],
) -> list[DatasetPin]:
    """Which dataset version each `choices.dataset` key resolves to, forever.

    Refuses rather than resolves in all four ways it can go wrong, because each
    of them produces a form that works today and cannot be explained later:

      a key with no pin      the list would have to be resolved at read time,
                             against whatever is newest — the same mistake as
                             validating a v1 answer against v2's choice list
      a pin with no key      a claim about this form that is not true. Usually
                             the caller published the wrong form's datasets
      a pin twice            two answers to one question, and no way to say
                             which one the answers were collected against
      another project's      reference data crossing a project boundary, which
                             is a disclosure and not a mistake in ordering

    Nothing here defaults. A publish with no pins for a form that names no
    datasets is the ordinary case and returns an empty list; a publish with no
    pins for a form that names three is refused with all three named.
    """
    keys = dataset_keys(compiled)
    by_key: dict[str, DatasetPin] = {}
    violations: list[str] = []

    for pin in requested:
        if pin.key in by_key:
            violations.append(
                f"the dataset `{pin.key}` is pinned twice, to "
                f"{by_key[pin.key].dataset_version_id} and {pin.dataset_version_id}. "
                "A form version has one view of each list and there is no way to "
                "say which of these the answers were collected against."
            )
            continue
        by_key[pin.key] = pin

    missing = [key for key in keys if key not in by_key]
    if missing:
        violations.append(
            "this form chooses from "
            + ", ".join(f"`{k}`" for k in missing)
            + " and nothing says which version of "
            + ("those lists" if len(missing) > 1 else "that list")
            + " it was published against. A form version is pinned to its "
            "reference data at publish (Form IR §3), because resolving a key "
            "later would let a draft see whatever is newest — publish the "
            "dataset first and pass its `datasetVersionId`."
        )

    extra = sorted(set(by_key) - set(keys))
    if extra:
        violations.append(
            "pinned "
            + ", ".join(f"`{k}`" for k in extra)
            + ", which no question in this form chooses from. A pin that nothing "
            "references says this version depends on data it does not."
        )

    # One query for all of them: a form with five lists should not cost five
    # round trips, and the checks below need the rows anyway.
    wanted = [pin.dataset_version_id for key, pin in by_key.items() if key in keys]
    rows: dict[str, tuple[str, str]] = {}
    if wanted:
        found = await session.execute(
            select(DatasetVersion.id, DatasetVersion.dataset_id, Dataset.dataset_key,
                   Dataset.project_id)
            .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
            .where(DatasetVersion.id.in_(wanted))
        )
        for version_id, _dataset_id, dataset_key, owner in found:
            rows[version_id] = (dataset_key, owner)

    for key in keys:
        found_pin = by_key.get(key)
        if found_pin is None:
            continue
        pin = found_pin
        row = rows.get(pin.dataset_version_id)
        if row is None:
            violations.append(
                f"`{key}` is pinned to dataset version {pin.dataset_version_id}, "
                "which does not exist. Publish the dataset before the form that "
                "chooses from it."
            )
            continue
        dataset_key, owner = row
        if owner != project_id:
            # Not an ordering mistake. Reference data belongs to a project, and
            # a form in one project pinned to another's would deliver that
            # project's villages to these devices.
            violations.append(
                f"`{key}` is pinned to a dataset version belonging to a different "
                "project. Reference data does not cross a project boundary."
            )
        elif dataset_key != key:
            violations.append(
                f"`{key}` is pinned to a version of `{dataset_key}`. The form asks "
                f"for `{key}`, so this pin would give the question a different "
                "list from the one it names."
            )

    if violations:
        raise PublishRefused(violations)
    return [by_key[key] for key in keys]


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
    datasets: list[DatasetPin] | None = None,
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
    pins = await _resolve_dataset_pins(
        session, project_id=project_id, compiled=compiled, requested=datasets or []
    )

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
        # Same IR, and it must be the same view of the same reference data.
        # Identical questions over a different village list is a different form
        # in every way that matters to somebody reading the answers back.
        stored = await _stored_dataset_pins(session, existing.id)
        moved = [
            f"`{pin.key}` was published against dataset version "
            f"{stored[pin.key]} and this call pins it to {pin.dataset_version_id}"
            for pin in pins
            if pin.key in stored and stored[pin.key] != pin.dataset_version_id
        ]
        if moved:
            raise PublishRefused(
                [
                    f"{compiled.form_id} v{compiled.version} is already published and "
                    + "; ".join(moved)
                    + ". A published version's choice lists cannot move underneath "
                    "the answers collected against them — publish a new version."
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
            datasets=pins,
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

    # Pinned in the same transaction as the version itself. A version that
    # exists without its pins is a form whose lists resolve to nothing, and it
    # would be reachable by any reader between the two commits.
    session.add_all(
        [
            FormVersionDataset(
                form_version_id=version.id,
                dataset_key=pin.key,
                dataset_version_id=pin.dataset_version_id,
            )
            for pin in pins
        ]
    )
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
        datasets=pins,
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


async def compiled_form_for_submission(
    session: AsyncSession, submission_id: str
) -> CompiledForm | None:
    """The compiled form one submission was collected under.

    **The caller does not choose a version, and that is the point.** Form IR §9
    binds a submission to the version it was collected under, and §6.3 makes
    that binding load-bearing now that membership is validated: a value that was
    in v1's choice list and was removed in v2 is still correct for a submission
    collected under v1. Validating it against v2 would reject data that was right
    when it was collected — which is worse than not checking at all, because it
    destroys good answers instead of admitting bad ones, and it would surface
    months later as "the server is losing our data".

    This is the server's `FormCatalog.compiledFormForSubmission` (break 30). The
    client stopped being able to get this wrong by having nothing to pass; the
    same is done here rather than trusted to whoever writes the enforcement.
    There is deliberately **no** `version` parameter and no sibling function
    that takes one.

    Nothing on the push path validates values yet — §6.4's server column is not
    built. This exists first so that when it is, there is one way to obtain a
    form and it is already the right one.

    Returns None when the submission is unknown, or when its form version has
    been deleted; both are the honest answer rather than a fallback to some
    other version.
    """
    row = (
        await session.execute(
            select(FormVersion.ir)
            .join(Submission, Submission.form_version_id == FormVersion.id)
            .where(Submission.id == submission_id)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return CompiledForm(cast(dict[str, Any], row))


async def compiled_forms_for_submissions(
    session: AsyncSession, submission_ids: Sequence[str]
) -> dict[str, CompiledForm]:
    """`compiled_form_for_submission` for many submissions, in one query.

    Same rule, same shape: **no version parameter and no sibling that takes
    one.** An export runs over thousands of submissions sitting on whatever
    version each was collected under, and asking one at a time is thousands of
    round trips — but the fix for that is a batch of the same question, never a
    caller that looks up a version once and reuses it, which is exactly break
    40 with a loop around it.

    Submissions whose form version has been deleted are absent from the result,
    the same honest answer the singular gives as None. One `CompiledForm` object
    is shared by every submission on that version: compiling is not cheap and
    the object is immutable in every way this repository uses it.
    """
    if not submission_ids:
        return {}

    rows = (
        await session.execute(
            select(Submission.id, FormVersion.id, FormVersion.ir)
            .join(FormVersion, FormVersion.id == Submission.form_version_id)
            .where(Submission.id.in_(list(submission_ids)))
        )
    ).all()

    compiled: dict[str, CompiledForm] = {}
    by_version: dict[str, CompiledForm] = {}
    for submission_id, version_id, ir in rows:
        if version_id not in by_version:
            by_version[version_id] = CompiledForm(cast(dict[str, Any], ir))
        compiled[submission_id] = by_version[version_id]
    return compiled
