"""Generates the initial conformance vector set.

Kept as a script rather than hand-written JSON so the vectors stay consistent
and are cheap to extend. Run: python conformance/generate_vectors.py
"""

import json
import pathlib

OUT = pathlib.Path(__file__).parent / "vectors"


def lit(v):
    return {"op": "lit", "value": v}


def ref(p):
    return {"op": "ref", "path": p}


def op(name, *args):
    return {"op": name, "args": list(args)}


def call(fn, *args):
    return {"op": "call", "fn": fn, "args": list(args)}


def q(qid, dtype, **kw):
    node = {"type": "question", "id": qid, "dataType": dtype,
            "label": {"en": qid.replace("_", " ").title()}}
    node.update(kw)
    return node


def form(fid, children, **kw):
    f = {"irVersion": "0.1", "formId": fid, "version": 1,
         "title": {"en": fid}, "defaultLanguage": "en",
         "languages": ["en"], "children": children}
    f.update(kw)
    return f


VECTORS = []


def vector(vid, description, spec, f, steps, context=None):
    VECTORS.append({
        "id": vid,
        "description": description,
        "spec": spec,
        "form": f,
        "context": context or {"today": "2026-08-28"},
        "steps": steps,
    })


# --------------------------------------------------------------------------
# Relevance
# --------------------------------------------------------------------------

vector(
    "relevance-001",
    "A question is hidden when its relevance expression is false",
    "5.2",
    form("rel1", [
        q("sex", "select_one", choices={"kind": "inline", "items": [
            {"value": "m", "label": {"en": "Male"}},
            {"value": "f", "label": {"en": "Female"}}]}),
        q("pregnant", "boolean", relevant=op("eq", ref("sex"), lit("f"))),
    ]),
    [
        {"expect": {"relevant": {"pregnant": True}}},
        {"set": {"sex": "m"}, "expect": {"relevant": {"pregnant": False}}},
        {"set": {"sex": "f"}, "expect": {"relevant": {"pregnant": True}}},
    ],
)

vector(
    "relevance-002",
    "Null relevance shows the question — never hide data because of missing input",
    "4.4.7",
    form("rel2", [
        q("age", "integer"),
        q("employed", "boolean", relevant=op("gte", ref("age"), lit(18))),
    ]),
    [
        # age is null -> gte yields null -> relevance coerces null to true
        {"expect": {"relevant": {"employed": True}}},
        {"set": {"age": 17}, "expect": {"relevant": {"employed": False}}},
        {"set": {"age": 18}, "expect": {"relevant": {"employed": True}}},
    ],
)

vector(
    "relevance-003",
    "A non-relevant field retains its value but is excluded from answers",
    "5.3",
    form("rel3", [
        q("has_job", "boolean"),
        q("employer", "text", relevant=op("eq", ref("has_job"), lit(True))),
    ]),
    [
        {"set": {"has_job": True, "employer": "Acme"}},
        {"expect": {"relevant": {"employer": True}, "values": {"employer": "Acme"}}},
        {"set": {"has_job": False},
         "expect": {"relevant": {"employer": False}, "values": {"employer": "Acme"}}},
        {"set": {"has_job": True},
         "expect": {"relevant": {"employer": True}, "values": {"employer": "Acme"}}},
    ],
)

vector(
    "relevance-004",
    "Group relevance is inherited by every child",
    "2.2",
    form("rel4", [
        q("consent", "boolean"),
        {"type": "group", "id": "details", "label": {"en": "Details"},
         "relevant": op("eq", ref("consent"), lit(True)),
         "children": [q("name", "text"), q("phone", "text")]},
    ]),
    [
        {"set": {"consent": False},
         "expect": {"relevant": {"name": False, "phone": False}}},
        {"set": {"consent": True},
         "expect": {"relevant": {"name": True, "phone": True}}},
    ],
)

# --------------------------------------------------------------------------
# Null semantics — the section most likely to diverge between engines
# --------------------------------------------------------------------------

vector(
    "null-001",
    "false dominates null in AND; true dominates null in OR",
    "4.4.5, 4.4.6",
    form("null1", [
        q("a", "boolean"),
        q("b", "boolean"),
        q("and_result", "boolean", calculate=op("and", ref("a"), ref("b"))),
        q("or_result", "boolean", calculate=op("or", ref("a"), ref("b"))),
    ]),
    [
        # a=false, b=null -> AND is false (false dominates), OR is null
        {"set": {"a": False},
         "expect": {"values": {"and_result": False, "or_result": None}}},
        # a=true, b=null -> AND is null, OR is true (true dominates)
        {"set": {"a": True},
         "expect": {"values": {"and_result": None, "or_result": True}}},
        {"set": {"b": True},
         "expect": {"values": {"and_result": True, "or_result": True}}},
    ],
)

vector(
    "null-002",
    "Comparison with null yields null, not false",
    "4.4.3",
    form("null2", [
        q("x", "integer"),
        q("cmp", "boolean", calculate=op("gt", ref("x"), lit(10))),
        q("is_missing", "boolean", calculate=call("is_null", ref("x"))),
    ]),
    [
        {"expect": {"values": {"cmp": None, "is_missing": True}}},
        {"set": {"x": 11}, "expect": {"values": {"cmp": True, "is_missing": False}}},
    ],
)

vector(
    "null-003",
    "Arithmetic with null yields null; division by zero yields null",
    "4.4.2, 4.4.8",
    form("null3", [
        q("a", "integer"),
        q("b", "integer"),
        q("total", "integer", calculate=op("add", ref("a"), ref("b"))),
        q("ratio", "decimal", calculate=op("div", ref("a"), ref("b"))),
    ]),
    [
        {"set": {"a": 5}, "expect": {"values": {"total": None, "ratio": None}}},
        {"set": {"b": 0}, "expect": {"values": {"total": 5, "ratio": None}}},
        {"set": {"b": 2}, "expect": {"values": {"total": 7, "ratio": 2.5}}},
    ],
)

# --------------------------------------------------------------------------
# Calculations and dependency ordering
# --------------------------------------------------------------------------

vector(
    "calculate-001",
    "Chained calculations resolve in dependency order regardless of document order",
    "5.1, 5.2",
    form("calc1", [
        # c depends on b, b depends on a, but they are declared out of order
        q("c", "integer", calculate=op("mul", ref("b"), lit(2))),
        q("b", "integer", calculate=op("add", ref("a"), lit(10))),
        q("a", "integer"),
    ]),
    [
        {"set": {"a": 5}, "expect": {"values": {"b": 15, "c": 30}}},
        {"set": {"a": 1}, "expect": {"values": {"b": 11, "c": 22}}},
    ],
)

vector(
    "calculate-002",
    "age_years computes whole years and respects the birthday boundary",
    "4.3",
    form("calc2", [
        q("dob", "date"),
        q("age", "integer", calculate=call("age_years", ref("dob"))),
    ]),
    [
        {"set": {"dob": "2000-08-28"}, "expect": {"values": {"age": 26}}},
        {"set": {"dob": "2000-08-29"}, "expect": {"values": {"age": 25}}},
        {"set": {"dob": None}, "expect": {"values": {"age": None}}},
    ],
    context={"today": "2026-08-28"},
)

vector(
    "calculate-003",
    "round uses half away from zero, not banker's rounding",
    "4.5",
    form("calc3", [
        q("x", "decimal"),
        q("r", "integer", calculate=call("round", ref("x"))),
    ]),
    [
        {"set": {"x": 2.5}, "expect": {"values": {"r": 3}}},
        {"set": {"x": 3.5}, "expect": {"values": {"r": 4}}},
        {"set": {"x": -2.5}, "expect": {"values": {"r": -3}}},
    ],
)

# --------------------------------------------------------------------------
# Constraints and required
# --------------------------------------------------------------------------

vector(
    "constraint-001",
    "A constraint only fails on an answered, relevant field",
    "6",
    form("con1", [
        q("age", "integer",
          constraint=op("and", op("gte", ref("age"), lit(0)),
                        op("lte", ref("age"), lit(120))),
          constraintMessage={"en": "Age must be between 0 and 120"}),
    ]),
    [
        {"expect": {"valid": {"age": True}}},
        {"set": {"age": 150},
         "expect": {"valid": {"age": False}, "errors": {"age": ["constraint"]}}},
        {"set": {"age": 30}, "expect": {"valid": {"age": True}}},
    ],
)

vector(
    "constraint-002",
    "A required, relevant, unanswered field is invalid; hiding it makes the form valid",
    "6",
    form("con2", [
        q("has_children", "boolean"),
        q("child_count", "integer", required=True,
          relevant=op("eq", ref("has_children"), lit(True))),
    ]),
    [
        {"set": {"has_children": True},
         "expect": {"valid": {"child_count": False},
                    "errors": {"child_count": ["required"]},
                    "formValid": False}},
        {"set": {"has_children": False}, "expect": {"formValid": True}},
        {"set": {"has_children": True, "child_count": 2},
         "expect": {"formValid": True}},
    ],
)

vector(
    "constraint-003",
    "Conditional required: only required when another answer demands it",
    "2.1",
    form("con3", [
        q("employed", "boolean"),
        q("employer", "text", required=op("eq", ref("employed"), lit(True))),
    ]),
    [
        {"set": {"employed": False}, "expect": {"required": {"employer": False},
                                                "formValid": True}},
        {"set": {"employed": True}, "expect": {"required": {"employer": True},
                                               "formValid": False}},
    ],
)

# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------

vector(
    "determinism-001",
    "Answer arrival order does not affect the final state",
    "5.2",
    form("det1", [
        q("a", "integer"),
        q("b", "integer"),
        q("total", "integer", calculate=op("add", ref("a"), ref("b"))),
        q("flag", "boolean", calculate=op("gt", ref("total"), lit(10))),
    ]),
    [
        {"set": {"a": 4}},
        {"set": {"b": 9}},
        {"expect": {"values": {"total": 13, "flag": True}}},
    ],
)

vector(
    "determinism-002",
    "The same answers applied in reverse order produce the same state",
    "5.2",
    form("det2", [
        q("a", "integer"),
        q("b", "integer"),
        q("total", "integer", calculate=op("add", ref("a"), ref("b"))),
        q("flag", "boolean", calculate=op("gt", ref("total"), lit(10))),
    ]),
    [
        {"set": {"b": 9}},
        {"set": {"a": 4}},
        {"expect": {"values": {"total": 13, "flag": True}}},
    ],
)

# --------------------------------------------------------------------------
# Selects
# --------------------------------------------------------------------------

vector(
    "select-001",
    "selected() tests membership in a multi-select; order is insensitive",
    "4.1",
    form("sel1", [
        q("symptoms", "select_multiple", choices={"kind": "inline", "items": [
            {"value": "fever", "label": {"en": "Fever"}},
            {"value": "cough", "label": {"en": "Cough"}},
            {"value": "rash", "label": {"en": "Rash"}}]}),
        q("has_fever", "boolean",
          calculate=op("selected", ref("symptoms"), lit("fever"))),
        q("n", "integer", calculate=call("count_selected", ref("symptoms"))),
    ]),
    [
        {"expect": {"values": {"has_fever": None, "n": 0}}},
        {"set": {"symptoms": ["cough", "fever"]},
         "expect": {"values": {"has_fever": True, "n": 2}}},
        {"set": {"symptoms": ["rash"]},
         "expect": {"values": {"has_fever": False, "n": 1}}},
    ],
)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for existing in OUT.glob("*.json"):
        existing.unlink()
    for v in VECTORS:
        path = OUT / f"{v['id']}.json"
        path.write_text(json.dumps(v, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {len(VECTORS)} vectors to {OUT}")


if __name__ == "__main__":
    main()
