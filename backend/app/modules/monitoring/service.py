"""What a supervisor may count, asked the way they may list it (item 5).

Every figure below is a `COUNT` or a `GROUP BY` over the same policy-carrying
table the corresponding list route reads, executed on the request's connection
under the request's principal. Row-level security filters an aggregate exactly
as it filters a select, so a number and the rows behind it are the same answer
**by construction** — and that holds only while nobody writes a second query
"for counting".

So, ruled out here and named so the next person has to argue with it: no
summary table, no materialised counter, no background refresh, no admin
connection, no caching across requests. If a figure ever needs to be faster
than a count, the answer is an index, not a copy of the number.

`tests/test_monitoring_scope.py` is the guard at the policy level and
`tests/test_monitoring.py` at the route level: for a supervisor — not only for
an admin, who passes a wide-open policy by definition — the aggregate equals
the enumeration, is strictly less than the organisation-wide figure, and
matches the fixture's expected subset.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database import Principal
from app.modules.monitoring.schemas import (
    AreaListResponse,
    AreaProgress,
    DayCount,
    DeviceListResponse,
    DeviceStatus,
    EnumeratorListResponse,
    EnumeratorProgress,
    Overview,
)

#: How many days of "finished per day" a screen gets. Two weeks is what a
#: supervisor looks back over in the field; a longer window is a report.
PER_DAY_WINDOW = 14

#: A case counts as covered once the enumerator has finished with it. `draft`
#: has not been finished; `rejected` and `correction_required` have come back
#: and are work again (item 5, §3.3).
COVERED_STATUSES = ("finalized", "in_review", "approved")

_SCOPE_LABELS = {
    "organization": "the organisation",
    "project": "this project",
    "team": "your team",
    "none": "nothing you can see",
}


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


# ---------------------------------------------------------------------------
# The counts
# ---------------------------------------------------------------------------

# Cases held by a person, and how many of those carry finished work. One
# statement, so the numerator and the denominator cannot come from two
# different views of `assignment`.
_PROGRESS_SQL = """
    SELECT count(*) AS assigned,
           count(*) FILTER (WHERE EXISTS (
               SELECT 1 FROM submission s
                WHERE s.case_id = c.id AND s.status = ANY(:covered)
           )) AS covered
    FROM case_record c
    JOIN assignment a ON a.case_id = c.id AND a.released_at IS NULL
                     AND a.user_id IS NOT NULL
    WHERE c.project_id = :project_id
"""


async def overview(session: AsyncSession, project_id: str, principal: Principal) -> Overview:
    progress = (
        (
            await session.execute(
                text(_PROGRESS_SQL),
                {"project_id": project_id, "covered": list(COVERED_STATUSES)},
            )
        )
        .mappings()
        .one()
    )
    submissions = (
        await session.execute(
            text("SELECT count(*) FROM submission WHERE project_id = :p"),
            {"p": project_id},
        )
    ).scalar_one()
    uncased = (
        await session.execute(
            text("SELECT count(*) FROM submission WHERE project_id = :p AND case_id IS NULL"),
            {"p": project_id},
        )
    ).scalar_one()
    devices = (
        await session.execute(
            text("SELECT count(*) FROM device WHERE project_id = :p"), {"p": project_id}
        )
    ).scalar_one()

    per_day = (
        (
            await session.execute(
                text(
                    "SELECT (finalized_at AT TIME ZONE 'UTC')::date AS day, count(*) AS n "
                    "FROM submission "
                    "WHERE project_id = :p AND finalized_at IS NOT NULL "
                    "  AND finalized_at >= now() - make_interval(days => :days) "
                    "GROUP BY day ORDER BY day"
                ),
                {"p": project_id, "days": PER_DAY_WINDOW},
            )
        )
        .mappings()
        .all()
    )

    return Overview(
        scope_kind=principal.scope_kind or "none",
        scope_label=_SCOPE_LABELS.get(principal.scope_kind or "none", "your scope"),
        cases_assigned=int(progress["assigned"]),
        cases_covered=int(progress["covered"]),
        submissions=int(submissions),
        uncased_submissions=int(uncased),
        devices=int(devices),
        flags_outstanding=await flags_outstanding(session, project_id),
        per_day=[DayCount(date=row["day"].isoformat(), count=int(row["n"])) for row in per_day],
    )


async def flags_outstanding(session: AsyncSession, project_id: str) -> int | None:
    """Open quality flags, or **None when nothing can raise one**.

    `quality_flag` has existed since 001 and has no writer: item 6 is where
    rules run on arrival. A zero here would be an empty table rendered as a
    measurement — the same lie as a server-derived pending count, and the
    version people trust because it looks like data. So the absence of any
    rule for this project is reported as "not measurable", and the console
    renders the card only when this is a number (A7).
    """
    rules = (
        await session.execute(
            text("SELECT count(*) FROM quality_rule WHERE project_id = :p"), {"p": project_id}
        )
    ).scalar_one()
    if int(rules) == 0:
        return None
    return int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM quality_flag f "
                    "JOIN submission s ON s.id = f.submission_id "
                    "WHERE s.project_id = :p AND f.resolved_at IS NULL"
                ),
                {"p": project_id},
            )
        ).scalar_one()
    )


_ENUMERATORS_SQL = """
    SELECT u.id, u.display_name,
           count(DISTINCT a.case_id) AS assigned,
           count(DISTINCT a.case_id) FILTER (WHERE EXISTS (
               SELECT 1 FROM submission s
                WHERE s.case_id = a.case_id AND s.status = ANY(:covered)
           )) AS covered,
           (SELECT count(*) FROM submission s2
             WHERE s2.created_by = u.id AND s2.project_id = :project_id
               AND s2.status = ANY(:covered)) AS finalized,
           (SELECT max(d.last_sync_at) FROM device d WHERE d.user_id = u.id) AS last_sync_at
    FROM platform_user u
    LEFT JOIN assignment a ON a.user_id = u.id AND a.released_at IS NULL
    LEFT JOIN case_record c ON c.id = a.case_id AND c.project_id = :project_id
    GROUP BY u.id, u.display_name
    HAVING count(DISTINCT a.case_id) > 0
        OR (SELECT count(*) FROM submission s3
             WHERE s3.created_by = u.id AND s3.project_id = :project_id) > 0
    ORDER BY u.display_name
"""


async def enumerators(session: AsyncSession, project_id: str) -> EnumeratorListResponse:
    """Per person, over the people this principal may see.

    `platform_user` carries item 1's policy, so who appears here is the same
    set the people screen lists — a supervisor's team, and themselves.
    """
    rows = (
        (
            await session.execute(
                text(_ENUMERATORS_SQL),
                {"project_id": project_id, "covered": list(COVERED_STATUSES)},
            )
        )
        .mappings()
        .all()
    )
    return EnumeratorListResponse(
        enumerators=[
            EnumeratorProgress(
                user_id=row["id"],
                display_name=row["display_name"],
                assigned=int(row["assigned"]),
                covered=int(row["covered"]),
                finalized=int(row["finalized"]),
                last_sync_at=_iso(row["last_sync_at"]),
            )
            for row in rows
        ]
    )


_AREAS_SQL = """
    SELECT coalesce(r.data ->> :column, '(no area)') AS area,
           count(*) AS assigned,
           count(*) FILTER (WHERE EXISTS (
               SELECT 1 FROM submission s
                WHERE s.case_id = c.id AND s.status = ANY(:covered)
           )) AS covered
    FROM case_record c
    JOIN assignment a ON a.case_id = c.id AND a.released_at IS NULL
                     AND a.user_id IS NOT NULL
    LEFT JOIN LATERAL (
        SELECT dr.data FROM dataset_record dr
          JOIN dataset_version dv ON dv.id = dr.dataset_version_id
          JOIN dataset d ON d.id = dv.dataset_id
         WHERE d.project_id = c.project_id AND d.dataset_key = c.dataset_key
           AND dr.record_key = c.case_key
         ORDER BY dv.version DESC LIMIT 1
    ) r ON true
    WHERE c.project_id = :project_id
    GROUP BY area
    ORDER BY area
"""


async def areas(session: AsyncSession, project_id: str) -> AreaListResponse:
    """Progress grouped by a column of the sample row.

    Which column is not invented here: migration 013 records what the
    composite key was composed from, and the first of those is the area
    (`settlementCode` in RCons's sample). A project with no sample has no
    area column, and the answer is an empty list rather than a guess.
    """
    column = (
        await session.execute(
            text(
                "SELECT key_columns[1] FROM dataset "
                "WHERE project_id = :p AND key_columns IS NOT NULL "
                "ORDER BY dataset_key LIMIT 1"
            ),
            {"p": project_id},
        )
    ).scalar_one_or_none()
    if column is None:
        return AreaListResponse(column=None, areas=[])
    rows = (
        (
            await session.execute(
                text(_AREAS_SQL),
                {
                    "project_id": project_id,
                    "column": column,
                    "covered": list(COVERED_STATUSES),
                },
            )
        )
        .mappings()
        .all()
    )
    return AreaListResponse(
        column=column,
        areas=[
            AreaProgress(
                area=row["area"], assigned=int(row["assigned"]), covered=int(row["covered"])
            )
            for row in rows
        ],
    )


async def devices(session: AsyncSession, project_id: str) -> DeviceListResponse:
    """The handsets this principal may see, with what each last said.

    Since 015 that is the handsets of people they may see: a supervisor's own
    enumerators, and a device nobody has signed in on belongs to nobody and
    appears only for an organisation-wide principal. The count on the overview
    is this same table under this same policy, which is what stops the panel
    and its total disagreeing about the rows with no owner.
    """
    rows = (
        (
            await session.execute(
                text(
                    "SELECT d.id, d.platform, d.app_version, d.last_sync_at, "
                    "       d.reported_pending_ops, d.reported_at, u.display_name AS person "
                    "FROM device d "
                    "LEFT JOIN platform_user u ON u.id = d.user_id "
                    "WHERE d.project_id = :p "
                    "ORDER BY u.display_name NULLS LAST, d.id"
                ),
                {"p": project_id},
            )
        )
        .mappings()
        .all()
    )
    return DeviceListResponse(
        devices=[
            DeviceStatus(
                device_id=row["id"],
                person=row["person"],
                platform=row["platform"],
                app_version=row["app_version"],
                last_sync_at=_iso(row["last_sync_at"]),
                reported_pending_ops=row["reported_pending_ops"],
                reported_at=_iso(row["reported_at"]),
            )
            for row in rows
        ]
    )
