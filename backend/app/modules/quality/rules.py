"""Reading and writing a project's quality rules, and one submission's verdict.

Every query here runs on the request's connection under the request's
principal. `quality_rule` chains to its project and `quality_flag` to its
submission, so who may see a rule and who may see a flag are decided in 016
and not repeated here (item 6, D4).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ulid import new_ulid
from app.modules.quality.schemas import (
    FlagView,
    QualityRuleIn,
    QualityRuleListResponse,
    QualityRuleOut,
    ReviewEntry,
    SubmissionQualityResponse,
)
from app.modules.quality.service import NOT_EVALUATED, RuleRefused, check_definition

_RULE_COLUMNS = "id, name, definition, severity, enabled, form_id, created_at"


def _rule(row: Any) -> QualityRuleOut:
    return QualityRuleOut(
        id=row["id"],
        name=row["name"],
        definition=row["definition"],
        severity=row["severity"],
        enabled=row["enabled"],
        form_id=row["form_id"],
        created_at=row["created_at"],
    )


async def list_rules(session: AsyncSession, project_id: str) -> QualityRuleListResponse:
    rows = (
        (
            await session.execute(
                text(
                    f"SELECT {_RULE_COLUMNS} FROM quality_rule "
                    "WHERE project_id = :p ORDER BY name, id"
                ),
                {"p": project_id},
            )
        )
        .mappings()
        .all()
    )
    return QualityRuleListResponse(rules=[_rule(row) for row in rows])


async def create_rule(
    session: AsyncSession, project_id: str, request: QualityRuleIn
) -> QualityRuleOut:
    check_definition(request.definition)
    import json

    row = (
        (
            await session.execute(
                text(
                    "INSERT INTO quality_rule "
                    "(id, project_id, form_id, name, definition, severity, enabled) "
                    "VALUES (:id, :p, :form, :name, CAST(:definition AS jsonb), :sev, :on) "
                    f"RETURNING {_RULE_COLUMNS}"
                ),
                {
                    "id": new_ulid(),
                    "p": project_id,
                    "form": request.form_id,
                    "name": request.name,
                    "definition": json.dumps(request.definition),
                    "sev": request.severity,
                    "on": request.enabled,
                },
            )
        )
        .mappings()
        .one()
    )
    return _rule(row)


async def update_rule(
    session: AsyncSession, rule_id: str, request: QualityRuleIn
) -> QualityRuleOut:
    check_definition(request.definition)
    import json

    row = (
        (
            await session.execute(
                text(
                    "UPDATE quality_rule SET name = :name, "
                    "definition = CAST(:definition AS jsonb), severity = :sev, "
                    "enabled = :on, form_id = :form WHERE id = :id "
                    f"RETURNING {_RULE_COLUMNS}"
                ),
                {
                    "id": rule_id,
                    "name": request.name,
                    "definition": json.dumps(request.definition),
                    "sev": request.severity,
                    "on": request.enabled,
                    "form": request.form_id,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise RuleRefused("not_found", "No such rule, or not one you may edit.")
    return _rule(row)


_FLAGS_SQL = """
    SELECT id, rule_id, rule_name, severity, outcome, detail, path,
           created_at, resolved_at
    FROM quality_flag
    WHERE submission_id = :s AND resolved_at IS NULL
    ORDER BY CASE severity WHEN 'error' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
             rule_name, id
"""

_REVIEWS_SQL = """
    SELECT r.id, r.decision, r.comment, r.created_at, u.display_name AS reviewer
    FROM review r
    LEFT JOIN platform_user u ON u.id = r.reviewer_id
    WHERE r.submission_id = :s
    ORDER BY r.created_at DESC, r.id DESC
"""


def _flag(row: Any) -> FlagView:
    return FlagView(
        id=row["id"],
        rule_id=row["rule_id"],
        rule_name=row["rule_name"],
        severity=row["severity"],
        outcome=row["outcome"],
        detail=row["detail"],
        path=row["path"],
        created_at=row["created_at"],
        resolved_at=row["resolved_at"],
    )


async def submission_quality(
    session: AsyncSession, submission_id: str
) -> SubmissionQualityResponse:
    """What the rules said, split by whether they ran.

    Two lists, not one with a field to read. A reviewer skimming a single list
    would take its length as "how much is wrong", and a rule that could not be
    evaluated is not something wrong — it is something unchecked, which is a
    different thing to do about it.
    """
    flags = (
        (await session.execute(text(_FLAGS_SQL), {"s": submission_id})).mappings().all()
    )
    reviews = (
        (await session.execute(text(_REVIEWS_SQL), {"s": submission_id})).mappings().all()
    )
    return SubmissionQualityResponse(
        flags=[_flag(row) for row in flags if row["outcome"] != NOT_EVALUATED],
        unevaluated=[_flag(row) for row in flags if row["outcome"] == NOT_EVALUATED],
        reviews=[
            ReviewEntry(
                id=row["id"],
                decision=row["decision"],
                comment=row["comment"],
                reviewer=row["reviewer"],
                created_at=row["created_at"],
            )
            for row in reviews
        ],
    )
