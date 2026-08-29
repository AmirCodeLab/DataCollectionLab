"""Read queries for forms, and the one path a version becomes published by.

Everything that publishes — the API endpoint, scripts/seed_dev.py — goes through
`publish_version`, so a form cannot enter the database without having passed the
Form IR §10 error checks. That includes sensitivity propagation (encryption
envelope §5.2): a check that only some publish paths run is not a check.
"""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ulid import new_ulid
from app.modules.crypto.envelope import check_sensitivity_propagation
from app.modules.form_engine.runtime import CompiledForm
from app.modules.forms.models import Form, FormVersion
from app.modules.forms.schemas import (
    FormListResponse,
    FormSummary,
    PublishVersionResponse,
)


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
) -> PublishVersionResponse:
    """Publish one immutable form version, or explain why it cannot be.

    Idempotent by content: re-publishing a version whose IR checksum already
    matches returns the stored row untouched. Re-publishing a version number
    with *different* content is refused — published versions are immutable
    (specs/erd-v0.1.md §4), and a device in the field has that exact IR compiled
    into a submission it has not synced yet.

    `form_id` / `form_version_id` let a caller pin the row ids it wants (the dev
    seed does, so a reseed is stable); both default to fresh ULIDs.
    """
    compiled = check_publishable(ir)
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
        )

    version = FormVersion(
        id=form_version_id or new_ulid(),
        form_id=form.id,
        version=compiled.version,
        ir=ir,
        ir_checksum=checksum,
        published_at=func.now(),
        published_by=published_by,
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
    )
