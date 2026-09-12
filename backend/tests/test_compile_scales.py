"""Compiling a form is linear-ish in its size, and the tie-break still holds.

No conformance vector can see either claim, and they fail in opposite ways.

A vector fixes the inputs and compares the outputs, so it sees the *order*
`_topological_order` produces and nothing about what that order cost. For the
life of this repository the ready set was a list re-sorted with
`key=self.order.index` — a linear scan per element per iteration — and every
form anyone had ever compiled was three screens, where the difference is
unmeasurable. On the 2,128-question questionnaire in
`docs/scale-run-2026-09-12-sindh.md` it was **16.3 seconds** against 10 ms,
paid once per import and once per compile, and the Kotlin engine had never had
it: `Runtime.kt` keeps its document index in a map. Two engines agreeing
exactly and differing by three orders of magnitude is precisely what the
vectors cannot report. Break 226.

The second test is the other half of the same change. A min-heap over document
positions and a re-sorted list agree only while the heap is keyed on position
rather than on insertion — and a form where they disagree needs the dependency
edges to *cross* document order, which is the fixture property that matters and
the one a sequential fixture cannot supply (docs/project-conventions.md, "A
sequential fixture cannot see an ordering bug").
"""

from __future__ import annotations

import time
from typing import Any

from app.modules.form_engine.runtime import CompiledForm


def _question(qid: str, **extra: Any) -> dict[str, Any]:
    node: dict[str, Any] = {
        "type": "question",
        "id": qid,
        "dataType": "text",
        "label": {"en": qid},
    }
    node.update(extra)
    return node


def _big_form(questions: int, sections: int) -> dict[str, Any]:
    """A questionnaire shaped like the Sindh listing: sections, gates, relevance.

    The density is what matters. Roughly half the questions carry a `relevant`
    reading their section's first question, so about half start at indegree
    zero — which is what makes the ready set large and the re-sort expensive.
    """
    per_section = questions // sections
    children: list[dict[str, Any]] = []
    made = 0
    for section in range(sections):
        gate = f"s{section}gate"
        inner: list[dict[str, Any]] = [_question(gate, dataType="integer")]
        made += 1
        for index in range(per_section - 1):
            if made >= questions:
                break
            qid = f"s{section}q{index}"
            node = _question(qid)
            if index % 2 == 0:
                node["relevant"] = {
                    "op": "gt",
                    "args": [{"op": "ref", "path": gate}, {"op": "lit", "value": 0}],
                }
            inner.append(node)
            made += 1
        children.append(
            {
                "type": "group",
                "id": f"sec{section}",
                "label": {"en": f"{section}"},
                "children": inner,
            }
        )
    return {
        "irVersion": "0.1",
        "formId": "scale",
        "version": 1,
        "title": {"en": "scale"},
        "defaultLanguage": "en",
        "languages": ["en"],
        "children": children,
    }


def test_a_two_thousand_question_form_compiles_in_under_two_seconds() -> None:
    form = _big_form(questions=2000, sections=90)
    started = time.perf_counter()
    compiled = CompiledForm(form)
    elapsed = time.perf_counter() - started

    assert len(compiled.fields) == 1980
    # 10 ms on the machine this was written on, and about 14 s on the code it
    # replaced. Two seconds is a 200x margin over the pass and a 7x margin
    # under the failure, which is the room a shared CI runner needs — a bound
    # tight enough to go red on a slow morning stops being read.
    assert elapsed < 2.0, f"compiling 2,000 questions took {elapsed:.1f}s"


def test_the_tie_break_is_document_order_when_dependencies_cross_it() -> None:
    """Two independent fields ready at once come out in document order.

    The fixture is deliberately not sequential: `c_third` is a calculate
    reading the field before it, so it leaves the ready set and re-enters it
    *after* `d_fourth` has been pushed. Insertion order and document order
    disagree from that point on, and only a heap keyed on position gets it
    right. With the edges pointing the other way the two answers coincide and
    the assertion is worth nothing.
    """
    form = {
        "irVersion": "0.1",
        "formId": "ties",
        "version": 1,
        "title": {"en": "ties"},
        "defaultLanguage": "en",
        "languages": ["en"],
        "children": [
            _question("a_first", dataType="integer"),
            _question("b_second", dataType="integer"),
            _question("c_third", calculate={"op": "ref", "path": "b_second"}),
            _question("d_fourth", dataType="integer"),
        ],
    }
    order = CompiledForm(form).topo_order
    assert order == ["a_first", "b_second", "c_third", "d_fourth"]
