"""What a dataset row is: its content address, and what makes its key usable.

Pulled out of `service.py` so that two callers can share one copy of the rules
rather than each having its own:

  `service.publish_dataset_version`  refuses a dataset whose keys are unusable
  `forms.xlsform.datasets`           says the same thing at import time, in the
                                     report, before anybody uploads anything

Two copies of "a key may not be blank" would be a second answer to the same
question, and the one an author saw would be whichever code path they happened
to reach. Worse, the import report would say a file is fine and the publish
would then refuse it — the `publishable` flag disagreeing with the gate, which
is the failure `test_publishable_means_the_publish_gate_agrees` exists for.

Nothing here touches a database or a session, deliberately: the importer runs in
a request that has no transaction and the CLI runs with no server at all.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from app.modules.crypto.envelope import canonical_json


def row_hash(data: dict[str, Any]) -> str:
    """SHA-256 over the row's canonical JSON.

    `canonical_json` is the envelope's (§5.1) — sorted keys, no spaces, UTF-8,
    no NaN — and it is reused rather than replaced because it already has a
    conformance vector proving two implementations agree on it. A second
    serialisation invented here would be a second thing to keep in step, and
    the symptom of getting it wrong is every row looking changed.
    """
    return "sha256:" + hashlib.sha256(canonical_json(data)).hexdigest()


def version_checksum(rows: list[tuple[str, str]]) -> str:
    """A whole version's content address, from its (key, row_hash) pairs.

    Sorted by key so two servers that inserted the same rows in different
    orders agree. This is what "is this the same dataset" means, and what a
    device compares to know whether it is behind.
    """
    digest = hashlib.sha256()
    for key, digest_of_row in sorted(rows):
        digest.update(key.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(digest_of_row.encode("utf-8"))
        digest.update(b"\x00")
    return "sha256:" + digest.hexdigest()


def content_address(rows: list[dict[str, Any]], key_column: str) -> str:
    """The checksum a set of rows would be published under.

    So that an import report can state the content address of a dataset before
    it is uploaded, and a caller can tell "this is already published" from "this
    is a new version" without a round trip.
    """
    return version_checksum([(str(row[key_column]), row_hash(row)) for row in rows])


@dataclass
class KeyReport:
    """What is wrong with a dataset's keys, and what is merely worth saying.

    `problems` refuse the dataset. `warnings` do not — see `confusable`, which
    is the one case where the honest answer is to report and not act.
    """

    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: Keys appearing on more than one row, sorted. A refusal.
    repeated: list[str] = field(default_factory=list)
    #: How many rows had nothing in the key column. A refusal.
    missing: int = 0
    #: Groups of keys differing only by case or surrounding whitespace. Kept as
    #: separate rows, and named.
    confusable: list[list[str]] = field(default_factory=list)

    @property
    def refused(self) -> bool:
        return bool(self.problems)


def check_keys(rows: list[dict[str, Any]], key_column: str) -> KeyReport:
    """Whether these rows can be published under `key_column`.

    The key is the cell's value, EXACTLY — Form IR §3.1. Not trimmed, not
    case-folded.

    It has to be the same rule as choice matching (§6.3) and this is the
    reason: a dataset-backed select stores a value taken from `valueColumn`,
    and §6.3 then validates that value against the resolved list by exact
    match. Trimming the key here while the stored answer kept its whitespace
    would make a legitimate answer fail membership against the very row it
    came from, and the report would say the value is not in a list that
    visibly contains it.

    Emptiness is still decided after stripping — "   " is no identity at all —
    but what gets stored is what was in the cell.
    """
    report = KeyReport()

    counts: dict[str, int] = {}
    for row in rows:
        raw = row.get(key_column)
        key = "" if raw is None else str(raw)
        if not key.strip():
            report.missing += 1
            continue
        counts[key] = counts.get(key, 0) + 1

    if report.missing:
        report.problems.append(
            f"{report.missing} row(s) have no value in the key column `{key_column}`. "
            "A row with no identity cannot be selected, referred to, or deleted "
            "in a later version."
        )

    report.repeated = sorted(k for k, n in counts.items() if n > 1)
    if report.repeated:
        extra = len(report.repeated) - 5
        shown = ", ".join(report.repeated[:5]) + (f" (+{extra} more)" if extra > 0 else "")
        report.problems.append(
            f"{len(report.repeated)} key(s) in `{key_column}` appear more than once: "
            f"{shown}. Keys identify rows across versions, so a repeated one makes it "
            "impossible to say which row a later change refers to."
        )

    # Keys that differ only by whitespace or case are DIFFERENT rows (§3.1) and
    # are reported rather than merged. They are almost always the same village
    # entered twice — but merging them would be the platform deciding that two
    # rows a customer supplied are one, which is not the platform's decision.
    folded: dict[str, list[str]] = {}
    for key in counts:
        folded.setdefault(key.strip().casefold(), []).append(key)
    report.confusable = [sorted(group) for group in folded.values() if len(group) > 1]
    if report.confusable:
        shown = "; ".join(
            " vs ".join(repr(k) for k in group) for group in report.confusable[:3]
        )
        report.warnings.append(
            f"{len(report.confusable)} key(s) differ only by case or surrounding whitespace "
            f"and are stored as separate rows: {shown}. Form IR §3.1 matches keys "
            "exactly, so these are distinct choices an enumerator will see twice. "
            "They were not merged — that would be this platform deciding two of "
            "your rows are one."
        )

    return report
