"""Six form shapes that publish clean and ask nobody anything.

Backs docs/phase3-item0-builder-scope.md §0.2. Each shape puts a question
inside a container that can never yield a screen, plus one ordinary question
outside it. Every one compiles, passes check_publishable, and is reported
askable by askable_question_ids() -- so the reachability refusal written for
defect 14 would pass all six even if it were moved onto the publish path.
screen_relevant then returns False for the container at runtime and the inside
question is never asked. That is defect 14's symptom with nothing to catch it.

Run:  ./backend/.venv/bin/python scripts/probe_publishable_empty_containers.py

The original probe was lost with the analysis (rule 12). This script was
rewritten on 6 September 2026 from the recorded output and reproduces it
exactly, line for line, including the empty warnings -- which are empty
because the three warnings that would flag shapes 2, 3 and 4 are named in
Form IR §10.3 and implemented by neither engine (known defect 17).
"""
import sys, json
sys.path.insert(0, "backend")
from app.modules.forms.service import check_publishable, PublishRefused
from app.modules.form_engine.runtime import FormInstance, CompileError
from app.modules.form_engine.screens import build_screen_plan, relevant_screens

L = lambda s: {"en": s}
FALSE = {"op": "lit", "value": False}

def q(i, dt="text"):
    return {"type": "question", "id": i, "dataType": dt, "label": L(i)}

def form(fid, children):
    return {"irVersion": "0.1", "formId": fid, "version": 1, "title": L(fid),
            "defaultLanguage": "en", "languages": ["en"], "children": children}

shapes = [
 ("empty inline roster, no add", form("p1", [
    {"type": "repeat", "id": "r1", "label": L("r1"), "children": [q("a1")],
     "rowSource": {"kind": "inline", "items": [], "allowAdd": False, "allowDelete": False}},
    q("q1")])),
 ("countExpr = 0", form("p2", [
    {"type": "repeat", "id": "r2", "label": L("r2"), "children": [q("a2")],
     "countExpr": {"op": "lit", "value": 0}},
    q("q2")])),
 ("statically false relevant (group)", form("p3", [
    {"type": "group", "id": "g3", "label": L("g3"), "relevant": FALSE, "children": [q("a3")]},
    q("q3")])),
 ("statically false relevant (question)", form("p4", [
    dict(q("a4"), relevant=FALSE),
    q("q4")])),
 ("empty field-list group", form("p5", [
    {"type": "group", "id": "g5", "label": L("g5"), "appearance": "field-list", "children": []},
    q("q5")])),
 ("maxInstances 0, enumerator repeat", form("p6", [
    {"type": "repeat", "id": "r6", "label": L("r6"), "children": [q("a6")], "maxInstances": 0},
    q("q6")])),
]

for name, ir in shapes:
    try:
        compiled = check_publishable(ir)
        verdict, warns = "PUBLISHES", compiled.warnings
    except (PublishRefused, CompileError) as e:
        print(f"{name:36} REFUSED  {e}")
        continue
    plan = build_screen_plan(ir)
    inst = FormInstance(compiled)
    askable = sorted(plan.askable_question_ids())
    live = sorted({qid for i in relevant_screens(plan, inst) for qid in plan[i].question_ids})
    print(f"{name:36} {verdict}  askable={askable}  live={live}  warnings={list(warns)}")
