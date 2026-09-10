"""Wire types for supervisor monitoring (item 5, analysis §5).

Every figure here is a `COUNT` over the same policy-carrying table its list
reads, so the number a screen shows and the rows behind it are the same
answer. The shapes carry two things beyond the numbers, and both are
deliberate: **whose scope** produced them, and **when the device said so** for
the one figure this server did not compute.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: How wide the asker's view is, in their own words. A supervisor's figures are
#: their team's and say so; nothing on a monitoring screen is a bare number
#: whose scope the reader has to infer (item 5, D2).
type ScopeKind = Literal["organization", "project", "team", "none"]


class DayCount(BaseModel):
    """One day's finished interviews, by the day the enumerator finished."""

    date: str
    count: int


class Overview(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    scope_kind: ScopeKind = Field(serialization_alias="scopeKind")
    #: "your team", "this project", "the organisation" — rendered beside every
    #: figure, so "none" never has to be read as "none anywhere".
    scope_label: str = Field(serialization_alias="scopeLabel")

    #: Cases held by a person, in scope: the denominator of progress (D3).
    cases_assigned: int = Field(serialization_alias="casesAssigned")
    #: Of those, cases carrying a submission the enumerator has finished.
    cases_covered: int = Field(serialization_alias="casesCovered")
    submissions: int
    #: Work with no case behind it. Counted apart rather than folded into a
    #: percentage, which it would inflate for reasons unrelated to the sample.
    uncased_submissions: int = Field(serialization_alias="uncasedSubmissions")
    devices: int

    #: Outstanding quality flags, or **null when nothing can raise one**: no
    #: quality rule exists for this project, so a zero here would be an empty
    #: table wearing a measurement's clothes (item 5, D2 and A7). The console
    #: renders the card only when this is a number.
    flags_outstanding: int | None = Field(serialization_alias="flagsOutstanding")

    #: By `finalized_at` — the day the work was done, not the day it arrived.
    per_day: list[DayCount] = Field(serialization_alias="perDay")


class EnumeratorProgress(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    user_id: str = Field(serialization_alias="userId")
    display_name: str = Field(serialization_alias="displayName")
    assigned: int
    covered: int
    finalized: int
    last_sync_at: str | None = Field(serialization_alias="lastSyncAt")


class EnumeratorListResponse(BaseModel):
    enumerators: list[EnumeratorProgress]


class AreaProgress(BaseModel):
    """One area's slice **of what the asker may see**, never the area's total.

    A supervisor's row for an area they share with another team is their part
    of it. Showing the area's true total would be a leak; labelling their part
    as the area's total would be a lie. So the label says whose it is (§2,
    failure 5).
    """

    area: str
    assigned: int
    covered: int


class AreaListResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    #: Which column of the sample row this grouped by, so a reader can tell
    #: what "area" meant here.
    column: str | None
    areas: list[AreaProgress]


class DeviceStatus(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    device_id: str = Field(serialization_alias="deviceId")
    person: str | None
    platform: str
    app_version: str | None = Field(serialization_alias="appVersion")
    last_sync_at: str | None = Field(serialization_alias="lastSyncAt")
    #: The device's own count of what is queued on it, and when it said so.
    #: Never this server's: `last_counter` is what was accepted, and what is
    #: behind it has never been mentioned here (item 5, A6). Rendered together
    #: or not at all — "3 pending" and "3 pending, as of 08:14" are different
    #: claims, and a supervisor acts on the second at four in the afternoon.
    reported_pending_ops: int | None = Field(serialization_alias="reportedPendingOps")
    reported_at: str | None = Field(serialization_alias="reportedAt")


class DeviceListResponse(BaseModel):
    devices: list[DeviceStatus]
