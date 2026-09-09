"""The sample, cases and assignment: reads under the policies, writes through
the two SQL functions 012_cases.sql provides.

Nothing here decides who may see or hold a case. `dcp_case_in_scope` does, on
the asker's principal, for every row this module reads; `dcp_assign_case` and
`dcp_upsert_cases` run with the caller's policies applying inside, so a
supervisor assigning outside their team or a case to a person not under it is
refused by the database and surfaces as `Refused(outside_your_authority)`.

Uploading a sample is publishing a dataset version (Form IR §3, unchanged)
with one more thing: the rows are keyed by the composite key the upload
names (§3.1's escaping rule), written into each row as `case_key`, and one
case is made per key — kept across re-uploads, withdrawn with a tombstone
when its key is gone.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ulid import new_ulid
from app.infrastructure.database import Principal
from app.modules.cases.schemas import (
    AssignedCase,
    Case,
    CaseFailure,
    CaseHolder,
    SampleUploadResponse,
)
from app.modules.entities import service as datasets
from app.modules.entities.case_key import CaseKeyRefused, key_of

#: The column the composed key is written into on every sample row, and the
#: one a `rowSource` filter compares: `$row.case_key = _metadata.case_key`.
CASE_KEY_COLUMN = "case_key"


class Refused(Exception):
    def __init__(self, status_code: int, reason: CaseFailure, message: str) -> None:
        super().__init__(f"{reason}: {message}")
        self.status_code = status_code
        self.reason: CaseFailure = reason
        self.message = message


OUTSIDE = Refused(
    403,
    "outside_your_authority",
    "The database refused this: the case, team or person is outside what your roles "
    "allow, or the person is not in the team that holds the case.",
)


def _refused_by_policy(error: DBAPIError) -> bool:
    return "row-level security" in str(error.orig)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

# The cases the policy shows, with the live holder at each level, the newest
# sample row behind each, and how many submissions the asker may see on it.
_CASES_SQL = text(
    """
    SELECT c.id, c.project_id, c.dataset_key, c.case_key, c.status, c.priority, c.due_at,
           ta.team_id, t.name AS team_name, ta.assigned_at AS team_assigned_at,
           pa.user_id, u.display_name AS user_name, pa.assigned_at AS person_assigned_at,
           (SELECT r.data FROM dataset_record r
              JOIN dataset_version v ON v.id = r.dataset_version_id
              JOIN dataset d ON d.id = v.dataset_id
             WHERE d.project_id = c.project_id AND d.dataset_key = c.dataset_key
               AND r.record_key = c.case_key
             ORDER BY v.version DESC LIMIT 1) AS data,
           (SELECT count(*) FROM submission s WHERE s.case_id = c.id) AS submissions
    FROM case_record c
    LEFT JOIN assignment ta ON ta.case_id = c.id AND ta.released_at IS NULL
                            AND ta.team_id IS NOT NULL
    LEFT JOIN team t ON t.id = ta.team_id
    LEFT JOIN assignment pa ON pa.case_id = c.id AND pa.released_at IS NULL
                            AND pa.user_id IS NOT NULL
    LEFT JOIN platform_user u ON u.id = pa.user_id
    WHERE c.project_id = :project_id
    ORDER BY c.priority DESC, c.case_key, c.id
    """
)


async def list_cases(session: AsyncSession, project_id: str) -> list[Case]:
    rows = (await session.execute(_CASES_SQL, {"project_id": project_id})).mappings().all()
    return [
        Case(
            id=row["id"],
            project_id=row["project_id"],
            dataset_key=row["dataset_key"],
            case_key=row["case_key"],
            status=row["status"],
            priority=row["priority"],
            due_at=_iso(row["due_at"]),
            data=dict(row["data"] or {}),
            holder=CaseHolder(
                team_id=row["team_id"],
                team_name=row["team_name"],
                user_id=row["user_id"],
                user_name=row["user_name"],
                assigned_at=_iso(row["person_assigned_at"] or row["team_assigned_at"]),
            ),
            submissions=int(row["submissions"]),
        )
        for row in rows
    ]


# The assignment statement for a device (sync §5): every case held by the
# device's person, complete, so a release is noticed by absence.
_ASSIGNED_SQL = text(
    """
    SELECT c.id, c.case_key, c.dataset_key, c.status, c.priority, c.due_at,
           (SELECT r.data FROM dataset_record r
              JOIN dataset_version v ON v.id = r.dataset_version_id
              JOIN dataset d ON d.id = v.dataset_id
             WHERE d.project_id = c.project_id AND d.dataset_key = c.dataset_key
               AND r.record_key = c.case_key
             ORDER BY v.version DESC LIMIT 1) AS data
    FROM assignment a
    JOIN case_record c ON c.id = a.case_id
    WHERE a.released_at IS NULL AND a.user_id = :user_id
    ORDER BY c.priority DESC, c.case_key, c.id
    """
)


async def assigned_to(session: AsyncSession, user_id: str) -> list[AssignedCase]:
    rows = (await session.execute(_ASSIGNED_SQL, {"user_id": user_id})).mappings().all()
    return [
        AssignedCase(
            case_id=row["id"],
            case_key=row["case_key"],
            dataset_key=row["dataset_key"],
            status=row["status"],
            priority=row["priority"],
            due_at=_iso(row["due_at"]),
            data=dict(row["data"] or {}),
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Writing: the two functions, with the caller's policies inside
# ---------------------------------------------------------------------------


async def _guarded(session: AsyncSession, sql: str, params: dict[str, Any]) -> Any:
    """One statement inside a SAVEPOINT: a policy refusal becomes `Refused`
    with the transaction still usable."""
    try:
        async with session.begin_nested():
            result = await session.execute(text(sql), params)
            return result.mappings().all() if getattr(result, "returns_rows", False) else []
    except DBAPIError as error:
        if _refused_by_policy(error):
            raise OUTSIDE from error
        raise


async def assign(
    session: AsyncSession, case_id: str, *, team_id: str | None, user_id: str | None
) -> None:
    if (team_id is None) == (user_id is None):
        raise Refused(400, "bad_request", "Name exactly one of teamId or userId.")
    await _guarded(
        session,
        "SELECT dcp_assign_case(:c, :team, :person, :id)",
        {"c": case_id, "team": team_id, "person": user_id, "id": new_ulid()},
    )


async def assign_many(
    session: AsyncSession, case_ids: Sequence[str], *, team_id: str | None, user_id: str | None
) -> int:
    """The split: many cases to one holder, one statement each inside the
    request's transaction — all or nothing, and each held to the policy."""
    for case_id in case_ids:
        await assign(session, case_id, team_id=team_id, user_id=user_id)
    return len(case_ids)


async def upload_sample(
    session: AsyncSession,
    *,
    project_id: str,
    dataset_key: str,
    key_columns: Sequence[str],
    rows: list[dict[str, Any]],
    name: str | None,
    principal: Principal,
) -> SampleUploadResponse:
    """Publish the sample as a dataset version keyed by the composite key,
    then make, reopen and withdraw cases by key."""
    if not key_columns:
        raise Refused(400, "bad_request", "Name at least one key column.")
    missing = [column for column in key_columns if rows and column not in rows[0]]
    if missing:
        raise Refused(
            400, "bad_request", f"The sample has no column named {', '.join(missing)}."
        )
    keyed: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        try:
            key = key_of(row, key_columns)
        except CaseKeyRefused as refusal:
            raise Refused(
                400,
                "bad_key_row",
                f"row {index}: {refusal}",
            ) from refusal
        keyed.append({**row, CASE_KEY_COLUMN: key})

    try:
        published = await datasets.publish_dataset_version(
            session,
            project_id=project_id,
            dataset_key=dataset_key,
            rows=keyed,
            key_column=CASE_KEY_COLUMN,
            name=name,
        )
    except datasets.DatasetRefused as refusal:
        raise Refused(400, "bad_key_row", "; ".join(refusal.reasons)) from refusal
    except DBAPIError as error:
        if _refused_by_policy(error):
            raise OUTSIDE from error
        raise
    # The columns the key was composed from, on the dataset, so an export can
    # split it back (A4).
    await _guarded(
        session,
        "UPDATE dataset SET key_columns = :columns WHERE id = :id",
        {"columns": list(key_columns), "id": published.dataset_id},
    )
    keys = [row[CASE_KEY_COLUMN] for row in keyed]
    counts = await _guarded(
        session,
        "SELECT * FROM dcp_upsert_cases(:p, :d, :keys, :ids)",
        {"p": project_id, "d": dataset_key, "keys": keys, "ids": [new_ulid() for _ in keys]},
    )
    made = counts[0]
    return SampleUploadResponse(
        dataset_key=dataset_key,
        dataset_version_id=published.dataset_version_id,
        version=published.version,
        row_count=published.row_count,
        created_version=published.created,
        key_columns=list(key_columns),
        cases_created=int(made["created"]),
        cases_reopened=int(made["reopened"]),
        cases_withdrawn=int(made["withdrawn"]),
        warnings=list(published.warnings),
    )
