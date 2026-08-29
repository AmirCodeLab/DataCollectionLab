"""Read queries for forms. Authoring lands in Phase 1."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.forms.models import Form, FormVersion
from app.modules.forms.schemas import FormListResponse, FormSummary


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
