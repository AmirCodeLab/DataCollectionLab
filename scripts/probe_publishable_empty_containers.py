#!/usr/bin/env python3
"""Six form shapes that publish clean and ask nobody anything.

    python scripts/probe_publishable_empty_containers.py

Backs `docs/phase3-item0-builder-scope.md` §0.2. Each shape puts a question
inside a container that can never yield a screen, plus one ordinary question
outside it. On 6 September 2026 every one compiled, passed `check_publishable`,
and was reported askable by `askable_question_ids()` — so the reachability
refusal written for defect 14 would have passed all six even if it had been
moved onto the publish path. `screen_relevant` then returned False for the
container at runtime and the question inside it was never asked: defect 14's
symptom with nothing between the author and the handset to catch it.

Since build-order step 2 (`app/modules/form_engine/reachability.py`) four of
the six are REFUSED, the statically-false leaf publishes with the §10.3
warning, and the empty field-list group publishes clean — nothing inside,
nothing lost. These six shapes are `conformance/reachability` 001–006,
verbatim and in this order, and `test_the_six_shapes_are_the_probe_s_own`
fails if the two drift apart. Run this to see the gate's current answer.

The original probe was lost with the analysis it backed (rule 12). This script
was rewritten on 6 September 2026 from the recorded output and reproduces it
exactly, line for line.
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.modules.form_engine.expression import CompileError  # noqa: E402
from app.modules.form_engine.runtime import FormInstance  # noqa: E402
from app.modules.form_engine.screens import (  # noqa: E402
    build_screen_plan,
    relevant_screens,
)
from app.modules.forms.service import PublishRefused, check_publishable  # noqa: E402

FALSE: dict[str, Any] = {"op": "lit", "value": False}


def label(text: str) -> dict[str, str]:
    return {"en": text}


def question(qid: str, data_type: str = "text", **extra: Any) -> dict[str, Any]:
    return {"type": "question", "id": qid, "dataType": data_type, "label": label(qid), **extra}


def form(form_id: str, children: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "irVersion": "0.1",
        "formId": form_id,
        "version": 1,
        "title": label(form_id),
        "defaultLanguage": "en",
        "languages": ["en"],
        "children": children,
    }


SHAPES: list[tuple[str, dict[str, Any]]] = [
    (
        "empty inline roster, no add",
        form(
            "p1",
            [
                {
                    "type": "repeat",
                    "id": "r1",
                    "label": label("r1"),
                    "children": [question("a1")],
                    "rowSource": {
                        "kind": "inline",
                        "items": [],
                        "allowAdd": False,
                        "allowDelete": False,
                    },
                },
                question("q1"),
            ],
        ),
    ),
    (
        "countExpr = 0",
        form(
            "p2",
            [
                {
                    "type": "repeat",
                    "id": "r2",
                    "label": label("r2"),
                    "children": [question("a2")],
                    "countExpr": {"op": "lit", "value": 0},
                },
                question("q2"),
            ],
        ),
    ),
    (
        "statically false relevant (group)",
        form(
            "p3",
            [
                {
                    "type": "group",
                    "id": "g3",
                    "label": label("g3"),
                    "relevant": FALSE,
                    "children": [question("a3")],
                },
                question("q3"),
            ],
        ),
    ),
    (
        "statically false relevant (question)",
        form("p4", [question("a4", relevant=FALSE), question("q4")]),
    ),
    (
        "empty field-list group",
        form(
            "p5",
            [
                {
                    "type": "group",
                    "id": "g5",
                    "label": label("g5"),
                    "appearance": "field-list",
                    "children": [],
                },
                question("q5"),
            ],
        ),
    ),
    (
        "maxInstances 0, enumerator repeat",
        form(
            "p6",
            [
                {
                    "type": "repeat",
                    "id": "r6",
                    "label": label("r6"),
                    "children": [question("a6")],
                    "maxInstances": 0,
                },
                question("q6"),
            ],
        ),
    ),
]


def probe(name: str, ir: dict[str, Any]) -> str:
    try:
        compiled = check_publishable(ir)
    except (PublishRefused, CompileError) as exc:
        return f"{name:36} REFUSED  {exc}"

    plan = build_screen_plan(ir)
    instance = FormInstance(compiled)
    askable = sorted(plan.askable_question_ids())
    live = sorted(
        {qid for index in relevant_screens(plan, instance) for qid in plan[index].question_ids}
    )
    return (
        f"{name:36} PUBLISHES  askable={askable}  "
        f"live={live}  warnings={list(compiled.warnings)}"
    )


def main() -> int:
    for name, ir in SHAPES:
        print(probe(name, ir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
