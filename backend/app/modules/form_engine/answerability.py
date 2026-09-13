"""Questions a form shows and nobody can answer, decided from the document alone.

Form IR §10.2. The sibling of `reachability.py`, and the distinction is worth
holding: reachability asks whether a question reaches a **screen**, this asks
whether a question that reached one can be **answered**. A form can pass the
first and fail the second, which is exactly what happened.

One finding today: **a `note` carrying `required`.**

§2.1 gives a note no value and nothing can give it one, so `required` on one is
permanently blocking under §6.2. The submission can never be finalised, and
`first_blocking_screen` sends the enumerator to a screen holding a sentence and
nothing to answer. That is defect 15's family — a blocking field nobody can
answer — with the opposite shape: defect 15 is a `calculate`, which has no
screen at all, so there is nowhere to send anyone; this has a screen with
nothing on it.

**`required` present at all is the refusal**, not `required` evaluating true. A
statically-false one is merely pointless, and distinguishing the two would leave
an author one edit away from a form that cannot be finished.

A `constraint` or a `readOnly` on a note is equally meaningless and is
deliberately **not** refused: a constraint over null coerces true (§4.4.7), a
readOnly over null coerces false, and both are inert. Only `required` changes
what the form does.

## Why this is a §10 rule and collectability is not

Both refuse a form at publish, and they are not the same kind of statement.
"A question that stores no value cannot be required" is true of a **document**,
wherever it is read — so both engines implement it, `conformance/answerability`
compares them, and a builder cannot accept what the server refuses. "No client
can present a `time` question" is true of an **app version**, so it lives in
`app/modules/forms/collectability.py`, has no Kotlin twin and carries no vector
(`docs/project-conventions.md`, "A statement about an app version is not a
statement a vector can hold").

The Kotlin twin is `shared/form-engine/.../Answerability.kt`. Both must produce
the same violations in the same order; `docs/known-defects.md` 31 is where the
rule came from, and it came from an author writing it by accident.
"""

from __future__ import annotations

from typing import Any

#: Every §2.1 dataType that holds no value. `note` is the whole list, and the
#: set exists rather than a literal so that a second valueless type arrives here
#: rather than in a second copy of this rule somewhere else.
VALUELESS_TYPES = frozenset({"note"})


def _questions(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every question node in document order, containers walked through."""
    found: list[dict[str, Any]] = []
    for node in nodes:
        if node.get("type") == "question":
            found.append(node)
        children = node.get("children")
        if children:
            found.extend(_questions(children))
    return found


def required_valueless_message(node_id: str, data_type: str) -> str:
    """The one sentence both engines and the importer say."""
    return (
        f"'{node_id}' is a `{data_type}`, which holds no value (Form IR §2.1), and it "
        "is marked `required`. Nothing can ever answer it, so this submission could "
        "never be finalised and the enumerator would be sent to a screen with nothing "
        "on it (Form IR §10.2, §6.2)."
    )


def check_answerability(ir: dict[str, Any]) -> list[str]:
    """Violations that block publish, in document order. Empty when none."""
    return [
        required_valueless_message(node["id"], node["dataType"])
        for node in _questions(ir.get("children", []))
        if node.get("dataType") in VALUELESS_TYPES and node.get("required") is not None
    ]
