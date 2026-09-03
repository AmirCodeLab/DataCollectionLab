"""Export, from the database — the one place a submission becomes a file.

Two bindings are load-bearing here and both are made rather than checked:

  - **A submission is projected against the version it was collected under**,
    through `forms.service.compiled_forms_for_submissions` — the batched form of
    the function that takes no version parameter (break 40). An export of a form
    spans every version its submissions sit on, and reading them all against the
    newest would rename columns and drop answers that were correct when they
    were collected.
  - **A code becomes a name through that version's dataset pins**, through
    `entities.service.dataset_rows_for_submissions` — likewise no version
    parameter (break 42). Resolving `V000023` any other way gives last month's
    village name, and nothing about the file would show it.

Neither is a check that could be forgotten: there is no function here that can
be handed a version.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.entities.service import dataset_rows_for_submissions
from app.modules.form_engine.projection import project_for_export
from app.modules.form_engine.runtime import CompiledForm
from app.modules.forms.models import Form, FormVersion
from app.modules.forms.service import compiled_forms_for_submissions
from app.modules.submissions.fold import Fold, fold_ops
from app.modules.submissions.models import (
    Submission,
    SubmissionOp,
    SubmissionWrappedKey,
)

from .manifest import build_manifest
from .plan import build_plan
from .shape import ChoiceLabels, Shape, SubmissionRecord, build_tables
from .writers import Bundle, Format, write_bundle

#: Above this, an export is a job rather than a request. Held here rather than
#: left implicit so the number is visible and can be argued with; item 5 has no
#: job runner yet and a silent truncation would be the worst of both.
DEFAULT_LIMIT = 5000


class ExportTooLarge(Exception):
    """More submissions than one synchronous export will do."""

    def __init__(self, found: int, limit: int) -> None:
        super().__init__(
            f"{found} submissions is more than this export will do in one "
            f"request ({limit}). Narrow it by status or environment."
        )
        self.found = found
        self.limit = limit


async def export_form(
    session: AsyncSession,
    *,
    form_key: str,
    project_id: str | None = None,
    environment_id: str | None = None,
    status: str | None = None,
    language: str | None = None,
    shape: Shape = "long",
    fmt: Format = "csv",
    limit: int = DEFAULT_LIMIT,
) -> Bundle | None:
    """Every matching submission of one form, as a bundle. None if no such form."""
    form = (
        await session.execute(
            _scoped(select(Form).where(Form.form_key == form_key), project_id)
        )
    ).scalar_one_or_none()
    if form is None:
        return None

    rows = (
        (
            await session.execute(
                _filtered(
                    select(Submission)
                    .join(FormVersion, FormVersion.id == Submission.form_version_id)
                    .where(FormVersion.form_id == form.id),
                    environment_id=environment_id,
                    status=status,
                )
                .order_by(Submission.received_at, Submission.id)
                .limit(limit + 1)
            )
        )
        .scalars()
        .all()
    )
    if len(rows) > limit:
        raise ExportTooLarge(len(rows), limit)

    submission_ids = [row.id for row in rows]
    compiled = await compiled_forms_for_submissions(session, submission_ids)
    folds = await _folds(session, submission_ids)
    openable = await _openable_by(session, folds)

    labels = await _labels_by_version(session, compiled, language=language)

    records: list[SubmissionRecord] = []
    for row in rows:
        form_version = compiled.get(row.id)
        if form_version is None:
            # Its form version is gone. Skipping is the honest answer — the
            # alternative is exporting the answers under some other version's
            # column names, which is a file that looks complete and is not.
            continue
        fold = folds.get(row.id, Fold())
        records.append(
            SubmissionRecord(
                submission_id=row.id,
                form_key=form.form_key,
                form_version=form_version.version,
                status=row.status,
                device_id=row.origin_device_id,
                created_by=row.created_by,
                started_at=row.started_at,
                finalized_at=row.finalized_at,
                received_at=row.received_at,
                projection=project_for_export(
                    form_version,
                    stored=fold.data,
                    instances=fold.instances,
                    unreadable=fold.unreadable.keys(),
                ),
                labels=labels.get((form_version.form_id, form_version.version), {}),
            )
        )

    plan = build_plan(sorted(set(compiled.values()), key=lambda f: f.version), language=language)
    tables = build_tables(plan, records, shape=shape, base_name=form.form_key)
    manifest = build_manifest(
        plan,
        tables,
        records,
        form_id=form.form_key,
        form_title=_title(form, compiled, language),
        language=language,
        shape=shape,
        ciphertext_fields=openable,
    )
    return write_bundle(tables, manifest, fmt=fmt)


def _scoped(statement: Select[Any], project_id: str | None) -> Select[Any]:
    return statement if project_id is None else statement.where(Form.project_id == project_id)


def _filtered(
    statement: Select[Any], *, environment_id: str | None, status: str | None
) -> Select[Any]:
    if environment_id is not None:
        statement = statement.where(Submission.environment_id == environment_id)
    if status is not None:
        statement = statement.where(Submission.status == status)
    return statement


async def _folds(session: AsyncSession, submission_ids: Sequence[str]) -> dict[str, Fold]:
    """One fold per submission, from ops read in `(counter, device_id)` order.

    The order is sync §6's and it is why this reads the log rather than
    `submission_state`: the materialised state is a dict in a JSONB column, and
    JSONB does not preserve key order, so the order instances were created in —
    which is the order a roster is displayed and exported in — does not survive
    a round trip through it. It also drops which paths were ciphertext, which is
    the difference between a blank cell and `ENCRYPTED`.
    """
    if not submission_ids:
        return {}
    ops = (
        (
            await session.execute(
                select(SubmissionOp)
                .where(SubmissionOp.submission_id.in_(list(submission_ids)))
                .order_by(SubmissionOp.counter, SubmissionOp.device_id)
            )
        )
        .scalars()
        .all()
    )
    grouped: dict[str, list[SubmissionOp]] = {}
    for op in ops:
        grouped.setdefault(op.submission_id, []).append(op)
    return {
        submission_id: fold_ops(found) for submission_id, found in grouped.items()
    }


async def _openable_by(
    session: AsyncSession, folds: Mapping[str, Fold]
) -> dict[str, tuple[str, ...]]:
    """Field id -> the project key ids whose private half opens it.

    This is the manifest's practical half. "This column is encrypted" tells a
    customer they have a problem; "this column is wrapped to `pk_3f2a`" tells
    them whose key opens it. A field that comes back with an **empty** tuple and
    is still unreadable is its own finding: a value wrapped to nobody.
    """
    content_keys = {
        content_key_id
        for fold in folds.values()
        for content_key_id in fold.unreadable.values()
    }
    if not content_keys:
        return {}

    wraps: dict[str, set[str]] = {}
    for content_key_id, project_key_id in (
        await session.execute(
            select(
                SubmissionWrappedKey.content_key_id, SubmissionWrappedKey.project_key_id
            ).where(SubmissionWrappedKey.content_key_id.in_(sorted(content_keys)))
        )
    ).all():
        wraps.setdefault(content_key_id, set()).add(project_key_id)

    found: dict[str, set[str]] = {}
    for fold in folds.values():
        for path, content_key_id in fold.unreadable.items():
            field_id = path.split("].", 1)[1] if "]." in path else path
            found.setdefault(field_id, set()).update(wraps.get(content_key_id, set()))
    return {field_id: tuple(sorted(keys)) for field_id, keys in found.items()}


async def _labels_by_version(
    session: AsyncSession,
    compiled: Mapping[str, CompiledForm],
    *,
    language: str | None,
) -> dict[tuple[str, int], ChoiceLabels]:
    """Code -> name, per form version, resolved through that version's pins."""
    representatives: dict[tuple[str, int], str] = {}
    for submission_id, form in compiled.items():
        representatives.setdefault((form.form_id, form.version), submission_id)

    forms: dict[tuple[str, int], CompiledForm] = {
        (form.form_id, form.version): form for form in compiled.values()
    }

    # A dataset pin is a property of the form version, so every submission on
    # one version resolves the same rows: asking on behalf of one of them is
    # asking on behalf of all of them, and asking per submission would fetch a
    # 38,000-row village list once per interview.
    keys = {
        query.dataset
        for form in forms.values()
        for field in form.fields.values()
        if (query := field.choice_query) is not None
    }
    rows_for_key: dict[str, Mapping[str, Sequence[Mapping[str, Any]]]] = {
        key: await dataset_rows_for_submissions(
            session, sorted(representatives.values()), key
        )
        for key in sorted(keys)
    }

    labels: dict[tuple[str, int], ChoiceLabels] = {}
    for version_key, form in forms.items():
        wanted = language or str(form.ir.get("defaultLanguage") or "")
        found: dict[str, dict[str, str]] = {}
        for field_id, field in form.fields.items():
            query = field.choice_query
            if query is None:
                found[field_id] = _inline_labels(field.node, wanted)
                continue
            rows = rows_for_key.get(query.dataset, {}).get(
                representatives[version_key], ()
            )
            column = query.label_columns.get(wanted) or next(
                iter(query.label_columns.values()), query.value_column
            )
            found[field_id] = {
                str(row.get(query.value_column)): str(row.get(column, ""))
                for row in rows
                if row.get(query.value_column) is not None
            }
        labels[version_key] = found
    return labels


def _inline_labels(node: Mapping[str, Any], language: str) -> dict[str, str]:
    choices = node.get("choices")
    if not isinstance(choices, dict) or choices.get("kind") != "inline":
        return {}
    found: dict[str, str] = {}
    for item in choices.get("items") or []:
        labels = item.get("label") or {}
        text = labels.get(language)
        if text is None and labels:
            text = next(iter(labels.values()))
        if text is not None:
            found[str(item.get("value"))] = str(text)
    return found


def _title(
    form: Form, compiled: Mapping[str, CompiledForm], language: str | None
) -> str | None:
    for candidate in sorted(compiled.values(), key=lambda f: f.version, reverse=True):
        titles = candidate.ir.get("title")
        if isinstance(titles, dict) and titles:
            wanted = language or str(candidate.ir.get("defaultLanguage") or "")
            return str(titles.get(wanted) or next(iter(titles.values())))
    return form.title
