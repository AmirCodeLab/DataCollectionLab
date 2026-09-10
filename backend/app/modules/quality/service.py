"""Running a project's quality rules over a submission, on arrival (item 6).

A rule is an **IR expression**. `quality_rule.definition` is `jsonb`, IR
expressions are JSON, and `form_engine.expression.evaluate` already reads them
in Python and in Kotlin under 116 conformance vectors. RCons's
`plausible_ranges.json` is 34 KB of range checks and a range check is
`and(gte(ref, lit), lte(ref, lit))`. Inventing a second expression language
here would put two evaluators in one product, which is the drift the whole
architecture is arranged to prevent (item 6, D5).

**A rule holds when its expression is true.** A flag is raised when it is
false — the same polarity `constraint` has in the IR, so an author who has
written one has written the other.

**And a rule that could not run is not a pass.** The server cannot read a
`field_level` or `project_e2e` submission: the console decrypts in the browser
with a key the server has never held. `Fold.unreadable` already names every
path whose current value is ciphertext. A rule that references one of those
paths is recorded as `not_evaluated` — a row, not an absence — because a
reviewer approving on the strength of an empty flag list is the failure that
turns a quality feature into a quality risk (item 6, D3).

Null is the third answer and is not a violation either. §4.4 of the IR is
null-propagating on purpose: a rule about an unanswered question has nothing
to say about it, and `is_not_null` is how an author asks for the other
behaviour.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ulid import new_ulid
from app.modules.form_engine.expression import (
    CompileError,
    EvalContext,
    EvaluationError,
    evaluate,
)

#: What a flag row's `outcome` may say. `violation` is a rule that ran and did
#: not hold; `not_evaluated` is a rule that could not run at all.
VIOLATION = "violation"
NOT_EVALUATED = "not_evaluated"


@dataclass(frozen=True)
class Rule:
    id: str
    name: str
    definition: Mapping[str, Any]
    severity: str
    path: str | None = None


@dataclass(frozen=True)
class Outcome:
    """One rule's verdict on one submission, or its refusal to give one."""

    rule: Rule
    outcome: str
    detail: Mapping[str, Any]


def _refs(expr: Any, into: set[str]) -> None:
    """Every `ref` path an expression reads, however deep.

    Walked rather than pattern-matched: a rule is arbitrary IR, and a
    reference inside the third argument of a `coalesce` is still a reference.
    """
    if isinstance(expr, Mapping):
        if expr.get("op") == "ref" and isinstance(expr.get("path"), str):
            into.add(expr["path"])
        for value in expr.values():
            _refs(value, into)
    elif isinstance(expr, Sequence) and not isinstance(expr, str | bytes):
        for item in expr:
            _refs(item, into)


def paths_read(definition: Mapping[str, Any]) -> set[str]:
    found: set[str] = set()
    _refs(definition, found)
    return found


def evaluate_rules(
    rules: Iterable[Rule],
    values: Mapping[str, Any],
    unreadable: Mapping[str, str],
    *,
    known_paths: Iterable[str] = (),
    now: datetime | None = None,
) -> list[Outcome]:
    """Every rule's verdict, in the order given.

    A rule that holds produces nothing: this returns only what a reviewer has
    to be told about. `unreadable` is the fold's, so "could not read" is the
    server's own record of what it holds rather than a guess from the
    project's security mode — a `field_level` project has readable and
    unreadable answers in the same submission, and only the fold knows which
    is which.

    `known_paths` is every field the submission's form declares. It matters
    because `values` is the **fold**, which holds answered paths only, while
    the engine on a device resolves every declared field and gives null for
    the ones nobody has answered. Without this, a rule about an optional
    question that was skipped would raise `unresolvable reference` and be
    reported as not checked — thousands of times, on every clean submission.
    A reference to something the form does not declare is a different fact and
    stays an error, because it is the author's mistake and silence would hide
    it.
    """
    moment = now or datetime.now(tz=UTC)
    resolved: dict[str, Any] = {path: None for path in known_paths}
    resolved.update(values)
    context = EvalContext(values=resolved, today=moment.date(), now=moment)
    declared = set(resolved)
    outcomes: list[Outcome] = []

    for rule in rules:
        reads = paths_read(rule.definition)
        unknown = sorted(reads - declared - set(unreadable))
        if unknown:
            outcomes.append(
                Outcome(
                    rule=rule,
                    outcome=NOT_EVALUATED,
                    detail={"reason": "unknown_path", "paths": unknown},
                )
            )
            continue
        blind = sorted(reads & set(unreadable))
        if blind:
            outcomes.append(
                Outcome(
                    rule=rule,
                    outcome=NOT_EVALUATED,
                    detail={"reason": "encrypted", "paths": blind},
                )
            )
            continue
        try:
            held = evaluate(rule.definition, context)
        except (EvaluationError, CompileError) as failure:
            # A rule that cannot be evaluated is not a rule that was passed.
            # The author's mistake is reported to the reviewer as "not
            # checked", never swallowed into a clean bill.
            outcomes.append(
                Outcome(
                    rule=rule,
                    outcome=NOT_EVALUATED,
                    detail={"reason": "invalid", "message": str(failure)},
                )
            )
            continue
        if held is None or held is True:
            # Null is not a violation (IR §4.4): a rule about an unanswered
            # question has nothing to say about it.
            continue
        outcomes.append(
            Outcome(rule=rule, outcome=VIOLATION, detail={"reason": "failed"})
        )

    return outcomes


_RULES_SQL = """
    SELECT r.id, r.name, r.definition, r.severity
    FROM quality_rule r
    JOIN submission s ON s.project_id = r.project_id
    JOIN form_version fv ON fv.id = s.form_version_id
    WHERE s.id = :submission_id AND r.enabled
      AND (r.form_id IS NULL OR r.form_id = fv.form_id)
    ORDER BY r.name, r.id
"""


async def rules_for(session: AsyncSession, submission_id: str) -> list[Rule]:
    """The enabled rules that apply to one submission's form.

    Read on the request's connection under the request's principal, like
    everything else — which for the push path is the enumerator's, and
    `quality_rule` chains to the project they are pushing into.
    """
    rows = (
        (await session.execute(text(_RULES_SQL), {"submission_id": submission_id}))
        .mappings()
        .all()
    )
    return [
        Rule(
            id=row["id"],
            name=row["name"],
            definition=row["definition"],
            severity=row["severity"],
        )
        for row in rows
    ]


async def record(
    session: AsyncSession, submission_id: str, outcomes: Sequence[Outcome]
) -> None:
    """Replace this submission's open flags with what the rules just said.

    Re-evaluation resolves what no longer holds and raises what now does; it
    never edits a row. A flag a reviewer read stays exactly as they read it,
    with the rule's definition **as it was then** beside it, so a rule edited
    afterwards cannot rewrite the history of a decision made under it.
    """
    await session.execute(
        text(
            "UPDATE quality_flag SET resolved_at = now() "
            "WHERE submission_id = :s AND resolved_at IS NULL"
        ),
        {"s": submission_id},
    )
    for outcome in outcomes:
        await session.execute(
            text(
                "INSERT INTO quality_flag "
                "(id, submission_id, rule_id, path, severity, outcome, rule_name,"
                " rule_definition, detail) "
                "VALUES (:id, :s, :rule, :path, :sev, :outcome, :name,"
                " CAST(:definition AS jsonb), CAST(:detail AS jsonb))"
            ),
            {
                "id": new_ulid(),
                "s": submission_id,
                "rule": outcome.rule.id,
                "path": outcome.rule.path,
                "sev": outcome.rule.severity,
                "outcome": outcome.outcome,
                "name": outcome.rule.name,
                "definition": _json(outcome.rule.definition),
                "detail": _json(outcome.detail),
            },
        )


def _json(value: Any) -> str:
    import json

    return json.dumps(value)


_FIELDS_SQL = """
    SELECT fv.ir FROM submission s
    JOIN form_version fv ON fv.id = s.form_version_id
    WHERE s.id = :submission_id
"""


def _question_ids(nodes: Any, into: set[str]) -> None:
    if not isinstance(nodes, list):
        return
    for node in nodes:
        if not isinstance(node, Mapping):
            continue
        if node.get("type") == "question" and isinstance(node.get("id"), str):
            into.add(node["id"])
        _question_ids(node.get("children"), into)


async def declared_paths(session: AsyncSession, submission_id: str) -> set[str]:
    """Every question the submission's own form version declares.

    Its **own** version, not the newest: a rule is evaluated against the form
    the interview was collected under, the same rule the export and the
    handset already follow (Form IR §9, break 30).
    """
    ir = (
        await session.execute(text(_FIELDS_SQL), {"submission_id": submission_id})
    ).scalar_one_or_none()
    if not isinstance(ir, Mapping):
        return set()
    found: set[str] = set()
    _question_ids(ir.get("children"), found)
    return found


async def evaluate_and_record(
    session: AsyncSession,
    submission_id: str,
    values: Mapping[str, Any],
    unreadable: Mapping[str, str],
) -> list[Outcome]:
    """Run the project's rules over a submission and write what they said.

    Called from the push transaction, beside the fold it reads — so a flag can
    never describe a state the submission was never in, and there is no worker
    and no eventual consistency to reason about (item 6, D3).
    """
    rules = await rules_for(session, submission_id)
    if not rules:
        # Nothing to say, and nothing to resolve: a project with no rules has
        # no flags, and clearing here would be a write on every push forever.
        return []
    outcomes = evaluate_rules(
        rules,
        values,
        unreadable,
        known_paths=await declared_paths(session, submission_id),
    )
    await record(session, submission_id, outcomes)
    return outcomes


# ---------------------------------------------------------------------------
# Rules, as a project manages them
# ---------------------------------------------------------------------------


class RuleRefused(Exception):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


def check_definition(definition: Mapping[str, Any]) -> None:
    """Compile a rule before storing it.

    A rule that cannot be evaluated is refused **at the author**, with the
    compiler's own message. The alternative is discovering it as
    `not_evaluated` on every submission afterwards, which is a queue full of
    the same author error wearing the clothes of an encrypted answer.
    """
    probe = EvalContext(
        values=_Anything(), today=datetime.now(tz=UTC).date(), now=datetime.now(tz=UTC)
    )
    try:
        evaluate(dict(definition), probe)
    except CompileError as failure:
        raise RuleRefused("invalid_expression", str(failure)) from failure
    except EvaluationError:
        # A type error against the probe's values is not an author error: the
        # real values decide, and §4.4 answers null rather than raising for
        # every ordinary mismatch.
        return


class _Anything(Mapping[str, Any]):
    """Every path resolves, to null. Compiling is about shape, not answers."""

    def __getitem__(self, key: str) -> Any:
        return None

    def __iter__(self) -> Any:
        return iter(())

    def __len__(self) -> int:
        return 0

    def __contains__(self, key: object) -> bool:
        return True
