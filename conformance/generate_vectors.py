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


def vector(vid, description, spec, f, steps, context=None, datasets=None):
    entry = {
        "id": vid,
        "description": description,
        "spec": spec,
        "form": f,
        "context": context or {"today": "2026-08-28"},
        "steps": steps,
    }
    if datasets is not None:
        # Rows for the dataset-backed lists this form chooses from (§3.2).
        # Inline in the vector because a vector is one self-contained file, and
        # because these are deliberately tiny: what is being compared is the
        # decomposition and the resolution, not a store's speed.
        entry["datasets"] = datasets
    VECTORS.append(entry)


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


# --------------------------------------------------------------------------
# Repeats
# --------------------------------------------------------------------------


def repeat(rid, children, **kw):
    node = {"type": "repeat", "id": rid, "label": {"en": rid.title()},
            "children": children}
    node.update(kw)
    return node


vector(
    "repeat-001",
    "Adding instances creates independent field values per instance",
    "2.3",
    form("rep1", [
        repeat("members", [q("name", "text"), q("age", "integer")]),
    ]),
    [
        {"expect": {"instanceCount": {"members": 0}}},
        {"addInstance": "members"},
        {"addInstance": "members"},
        {"set": {"members[0].name": "Ali", "members[1].name": "Sara"}},
        {"expect": {"instanceCount": {"members": 2},
                    "values": {"members[0].name": "Ali",
                               "members[1].name": "Sara",
                               "members[0].age": None}}},
    ],
)

vector(
    "repeat-002",
    "A bare reference inside a repeat resolves to the current instance",
    "4.2",
    form("rep2", [
        repeat("members", [
            q("dob", "date"),
            q("age", "integer", calculate=call("age_years", ref("dob"))),
        ]),
    ]),
    [
        {"addInstance": "members"},
        {"addInstance": "members"},
        {"set": {"members[0].dob": "2000-01-01", "members[1].dob": "2010-01-01"}},
        {"expect": {"values": {"members[0].age": 26, "members[1].age": 16}}},
    ],
    context={"today": "2026-08-28"},
)

vector(
    "repeat-003",
    "Aggregates over members[].field see every instance",
    "4.2, 4.3",
    form("rep3", [
        repeat("members", [q("income", "decimal")]),
        q("total_income", "decimal", calculate=call("sum", ref("members[].income"))),
        q("member_count", "integer", calculate=call("count", ref("members[].income"))),
    ]),
    [
        {"expect": {"values": {"total_income": 0, "member_count": 0}}},
        {"addInstance": "members"},
        {"addInstance": "members"},
        {"addInstance": "members"},
        {"set": {"members[0].income": 100, "members[1].income": 250}},
        # third instance is unanswered: sum ignores nulls, count counts non-nulls
        {"expect": {"values": {"total_income": 350, "member_count": 2}}},
    ],
)

vector(
    "repeat-004",
    "Deleting an instance removes its data and updates aggregates; "
    "remaining instances keep their values",
    "5.4",
    form("rep4", [
        repeat("members", [q("name", "text"), q("income", "decimal")]),
        q("total", "decimal", calculate=call("sum", ref("members[].income"))),
    ]),
    [
        {"addInstance": "members"},
        {"addInstance": "members"},
        {"addInstance": "members"},
        {"set": {"members[0].name": "A", "members[0].income": 10,
                 "members[1].name": "B", "members[1].income": 20,
                 "members[2].name": "C", "members[2].income": 30}},
        {"expect": {"values": {"total": 60}}},
        {"deleteInstance": {"repeat": "members", "index": 1}},
        # B is gone; A and C keep their values and C is now at position 1
        {"expect": {"instanceCount": {"members": 2},
                    "values": {"members[0].name": "A",
                               "members[1].name": "C",
                               "total": 40}}},
    ],
)

vector(
    "repeat-005",
    "Relevance inside a repeat is evaluated per instance",
    "5.2",
    form("rep5", [
        repeat("members", [
            q("age", "integer"),
            q("school", "text", relevant=op("lt", ref("age"), lit(18))),
        ]),
    ]),
    [
        {"addInstance": "members"},
        {"addInstance": "members"},
        {"set": {"members[0].age": 10, "members[1].age": 40}},
        {"expect": {"relevant": {"members[0].school": True,
                                 "members[1].school": False}}},
    ],
)

vector(
    "repeat-006",
    "countExpr controls the instance count and shrinking discards trailing data",
    "2.3",
    form("rep6", [
        q("household_size", "integer"),
        repeat("members", [q("name", "text")],
               countExpr=ref("household_size")),
    ]),
    [
        {"expect": {"instanceCount": {"members": 0}}},
        {"set": {"household_size": 3}},
        {"expect": {"instanceCount": {"members": 3}}},
        {"set": {"members[0].name": "A", "members[2].name": "C"}},
        {"set": {"household_size": 2}},
        {"expect": {"instanceCount": {"members": 2},
                    "values": {"members[0].name": "A"}}},
    ],
)

vector(
    "repeat-007",
    "A field outside a repeat can reference a specific instance by position",
    "4.2",
    form("rep7", [
        repeat("members", [q("name", "text")]),
        q("head_name", "text", calculate=ref("members[0].name")),
    ]),
    [
        # no instances yet: out-of-range positional read is null, not an error
        {"expect": {"values": {"head_name": None}}},
        {"addInstance": "members"},
        {"set": {"members[0].name": "Ali"}},
        {"expect": {"values": {"head_name": "Ali"}}},
    ],
)

vector(
    "repeat-008",
    "Constraints inside a repeat are validated per instance",
    "6",
    form("rep8", [
        repeat("members", [
            q("age", "integer",
              constraint=op("lte", ref("age"), lit(120)),
              constraintMessage={"en": "Age must be 120 or less"}),
        ]),
    ]),
    [
        {"addInstance": "members"},
        {"addInstance": "members"},
        {"set": {"members[0].age": 30, "members[1].age": 200}},
        {"expect": {"valid": {"members[0].age": True, "members[1].age": False},
                    "errors": {"members[1].age": ["constraint"]},
                    "formValid": False}},
    ],
)



# --------------------------------------------------------------------------
# Dates — runtime dates are ISO text (spec 2.1); today() must compare with a
# date answer as text on every engine. Regression: the Kotlin engine returned
# a distinct date type from today() and threw on `d <= today()`.
# --------------------------------------------------------------------------

vector(
    "date-001",
    "A date answer compares against today() as ISO text",
    "2.1, 4.3",
    form("date1", [
        q("d", "date",
          constraint=op("lte", ref("d"), call("today")),
          constraintMessage={"en": "No future dates"}),
        q("today_echo", "date", calculate=call("today"), readOnly=True),
    ]),
    [
        {"expect": {"values": {"today_echo": "2026-08-28"}}},
        {"set": {"d": "2026-08-27"}, "expect": {"valid": {"d": True}}},
        {"set": {"d": "2026-08-28"}, "expect": {"valid": {"d": True}}},
        {"set": {"d": "2026-08-29"},
         "expect": {"valid": {"d": False}, "errors": {"d": ["constraint"]}}},
        {"set": {"d": None}, "expect": {"valid": {"d": True}}},
    ],
)

vector(
    "date-002",
    "date_diff_days and date_add_days take ISO text; null operands yield null",
    "4.3, 4.4",
    form("date2", [
        q("a", "date"),
        q("diff", "integer",
          calculate=call("date_diff_days", ref("a"), lit("2026-08-20"))),
        q("plus", "date", calculate=call("date_add_days", ref("a"), lit(10))),
    ]),
    [
        {"expect": {"values": {"diff": None, "plus": None}}},
        {"set": {"a": "2026-08-28"},
         "expect": {"values": {"diff": 8, "plus": "2026-09-07"}}},
        {"set": {"a": "2026-02-27"},
         "expect": {"values": {"diff": -174, "plus": "2026-03-09"}}},
    ],
)


# --------------------------------------------------------------------------
# Screen flow (spec 11) — partition and navigation must match on every runtime
# --------------------------------------------------------------------------

def group(gid, children, **kw):
    node = {"type": "group", "id": gid,
            "label": {"en": gid.replace("_", " ").title()}, "children": children}
    node.update(kw)
    return node


vector(
    "screens-001",
    "One question per screen by default; a field-list group is one screen; "
    "plain groups flatten into field-lists; repeats are excluded from the plan",
    "11.1",
    form("scr1", [
        q("a", "text"),
        group("fl", [
            q("b", "integer"),
            group("inner", [q("c", "text")]),
        ], appearance="field-list"),
        group("plain", [
            q("d", "text"),
            {"type": "repeat", "id": "kids", "label": {"en": "Kids"},
             "children": [q("kid_age", "integer")]},
            q("e", "text"),
        ]),
    ]),
    [
        {"expect": {"screens": {
            "count": 4,
            "questions": {"0": ["a"], "1": ["b", "c"], "2": ["d"], "3": ["e"]},
            "groups": {"0": None, "1": "fl", "2": None},
            "sections": {"0": None, "1": None, "2": "plain", "3": "plain"},
        }}},
    ],
)

vector(
    "screens-002",
    "next/previous skip screens with no relevant question; -1 addresses the first",
    "11.2",
    form("scr2", [
        q("consent", "boolean"),
        q("x", "text", relevant=op("eq", ref("consent"), lit(True))),
        group("fl", [
            q("y", "text", relevant=op("eq", ref("consent"), lit(True))),
            q("z", "text", relevant=op("eq", ref("consent"), lit(True))),
        ], appearance="field-list"),
        q("w", "text"),
    ]),
    [
        # consent null -> relevance coerces null to true -> everything shown
        {"expect": {"screens": {
            "relevant": [0, 1, 2, 3],
            "next": {"-1": 0, "0": 1, "1": 2, "3": None},
            "previous": {"0": None, "2": 1, "3": 2},
        }}},
        {"set": {"consent": False},
         "expect": {"screens": {
             "relevant": [0, 3],
             "next": {"-1": 0, "0": 3, "3": None},
             "previous": {"0": None, "3": 0},
         }}},
        {"set": {"consent": True},
         "expect": {"screens": {
             "relevant": [0, 1, 2, 3],
             "next": {"0": 1},
             "previous": {"3": 2},
         }}},
    ],
)

vector(
    "screens-003",
    "A field-list screen stays relevant while any one of its questions is",
    "11.2",
    form("scr3", [
        q("k", "text"),
        group("fl", [
            q("a", "text", relevant=op("eq", ref("k"), lit("a"))),
            q("b", "text", relevant=op("eq", ref("k"), lit("b"))),
        ], appearance="field-list"),
    ]),
    [
        {"set": {"k": "a"},
         "expect": {"screens": {"relevant": [0, 1], "next": {"0": 1}}}},
        {"set": {"k": "b"},
         "expect": {"screens": {"relevant": [0, 1], "next": {"0": 1}}}},
        {"set": {"k": "neither"},
         "expect": {"screens": {"relevant": [0], "next": {"0": None},
                                "previous": {"1": 0}}}},
    ],
)


# --------------------------------------------------------------------------
# Navigation vs finalisation (spec 6.2)
#
# Whether an unanswered required field should stop the enumerator moving on was
# unspecified until §6.2: §11 says nothing about validity, so each platform's UI
# answered it differently and nothing caught that. These five vectors are the
# rule — navigation never gated, finalisation always gated — and the four edges
# that would otherwise be re-decided per client: a non-relevant field that
# retains an invalid value, a soft constraint, a field-list screen, and a
# blocking field inside a repeat with no screen to navigate to.
# --------------------------------------------------------------------------

vector(
    "screens-004",
    "Navigation is never gated on validity; finalisation is. Blocking fields "
    "are reported in document order with the screen to send the enumerator to",
    "6.2",
    form("scr4", [
        q("name", "text", required=True),
        q("age", "integer",
          constraint=op("lte", ref("age"), lit(120)),
          constraintMessage={"en": "Age must be 120 or less"}),
        q("comment", "text"),
    ]),
    [
        # Nothing answered: name blocks, and every screen is still reachable.
        {"expect": {
            "valid": {"name": False},
            "errors": {"name": ["required"]},
            "screens": {
                "count": 3,
                "next": {"-1": 0, "0": 1, "1": 2, "2": None},
                "previous": {"2": 1, "0": None},
                "canFinalize": False,
                "blocking": ["name"],
                "firstBlocking": 0,
            }}},
        # An impossible age adds a second blocker and changes nothing about
        # navigation — next still moves off the screen holding it.
        {"set": {"age": 150},
         "expect": {"screens": {
             "next": {"0": 1, "1": 2},
             "previous": {"1": 0},
             "canFinalize": False,
             "blocking": ["name", "age"],
             "firstBlocking": 0,
         }}},
        # Answering the first blocker moves firstBlocking on to the second.
        {"set": {"name": "Amina"},
         "expect": {"screens": {
             "canFinalize": False,
             "blocking": ["age"],
             "firstBlocking": 1,
         }}},
        {"set": {"age": 40},
         "expect": {
             "formValid": True,
             "screens": {"canFinalize": True, "blocking": [],
                         "firstBlocking": None}}},
    ],
)

vector(
    "screens-005",
    "A field made non-relevant stops blocking finalisation while keeping the "
    "invalid value it was given",
    "6.2",
    form("scr5", [
        q("has_job", "boolean"),
        q("start_year", "integer",
          relevant=op("eq", ref("has_job"), lit(True)),
          constraint=op("gte", ref("start_year"), lit(1900)),
          constraintMessage={"en": "Year must be 1900 or later"}),
    ]),
    [
        {"set": {"has_job": True, "start_year": 1200},
         "expect": {
             "valid": {"start_year": False},
             "screens": {"canFinalize": False, "blocking": ["start_year"],
                         "firstBlocking": 1}}},
        # Relevance turns off: the value is retained (5.3), the field is valid
        # again because it was never asked, and finalisation is unblocked.
        {"set": {"has_job": False},
         "expect": {
             "relevant": {"start_year": False},
             "values": {"start_year": 1200},
             "valid": {"start_year": True},
             "formValid": True,
             "screens": {"canFinalize": True, "blocking": [],
                         "firstBlocking": None}}},
    ],
)

vector(
    "screens-006",
    "A soft constraint makes a field invalid without blocking finalisation; a "
    "hard one on the same form does block",
    "6.1",
    form("scr6", [
        q("weight_kg", "decimal",
          constraint=op("lte", ref("weight_kg"), lit(200)),
          constraintMessage={"en": "Weight over 200 kg — please confirm"},
          severity="warning"),
        q("height_m", "decimal",
          constraint=op("lte", ref("height_m"), lit(3)),
          constraintMessage={"en": "Height must be 3 m or less"}),
    ]),
    [
        # Invalid and finalisable: formValid and canFinalize are different
        # questions, and this is the case that separates them.
        {"set": {"weight_kg": 400.5},
         "expect": {
             "valid": {"weight_kg": False},
             "errors": {"weight_kg": ["constraint"]},
             "formValid": False,
             "screens": {"canFinalize": True, "blocking": [],
                         "firstBlocking": None}}},
        {"set": {"height_m": 9.5},
         "expect": {
             "formValid": False,
             "screens": {"canFinalize": False, "blocking": ["height_m"],
                         "firstBlocking": 1}}},
        {"set": {"height_m": 1.7},
         "expect": {"screens": {"canFinalize": True, "blocking": [],
                                "firstBlocking": None}}},
    ],
)

vector(
    "screens-007",
    "firstBlockingScreen names a screen, not a field: a field-list screen is "
    "one destination however many of its questions block",
    "6.2",
    form("scr7", [
        q("a", "text"),
        group("fl", [
            q("b", "text", required=True),
            q("c", "text", required=True),
        ], appearance="field-list"),
        q("d", "text", required=True),
    ]),
    [
        {"expect": {"screens": {
            "count": 3,
            "questions": {"1": ["b", "c"]},
            "canFinalize": False,
            "blocking": ["b", "c", "d"],
            "firstBlocking": 1,
        }}},
        {"set": {"b": "one"},
         "expect": {"screens": {"blocking": ["c", "d"], "firstBlocking": 1}}},
        {"set": {"c": "two"},
         "expect": {"screens": {"blocking": ["d"], "firstBlocking": 2}}},
        {"set": {"d": "three"},
         "expect": {"screens": {"canFinalize": True, "blocking": [],
                                "firstBlocking": None}}},
    ],
)

vector(
    "screens-008",
    "A blocking field inside a repeat has no screen to navigate to and still "
    "refuses finalisation",
    "6.2",
    form("scr8", [
        q("head", "text"),
        {"type": "repeat", "id": "kids", "label": {"en": "Kids"},
         "children": [q("kid_name", "text", required=True)]},
    ]),
    [
        # firstBlocking is None and canFinalize is False at the same time:
        # repeats are excluded from the screen plan (11.1), so a client must
        # test canFinalize rather than reading None as "nothing wrong".
        {"addInstance": "kids",
         "expect": {"screens": {
             "count": 1,
             "canFinalize": False,
             "blocking": ["kids[0].kid_name"],
             "firstBlocking": None,
         }}},
        {"set": {"kids[0].kid_name": "Sara"},
         "expect": {"screens": {"canFinalize": True, "blocking": [],
                                "firstBlocking": None}}},
    ],
)


# --------------------------------------------------------------------------
# Media references and geopoints (spec 2.1) — the value shapes an `image`,
# `signature` or `geopoint` question holds.
#
# The Python reference keeps values as plain Python, so it reads any object at
# all and always has; the Kotlin engine is statically typed and had no case for
# either shape, which meant a media answer could not be represented on a
# client. These vectors are what stops the two drifting again.
# --------------------------------------------------------------------------

PHOTO = {"id": "01MEDIAROOF", "filename": "roof.jpg",
         "hash": "a" * 64, "size": 148213}
OTHER_PHOTO = {"id": "01MEDIAWALL", "filename": "wall.jpg",
               "hash": "b" * 64, "size": 91002}

vector(
    "media-001",
    "A media reference survives a round trip through the engine unchanged",
    "2.1",
    form("media1", [
        q("roof_photo", "image"),
    ]),
    [
        {"expect": {"values": {"roof_photo": None}}},
        {"set": {"roof_photo": PHOTO}, "expect": {"values": {"roof_photo": PHOTO}}},
    ],
)

vector(
    "media-002",
    "Relevance can branch on whether a media question has been answered",
    "2.1, 4.4.3",
    form("media2", [
        q("has_roof_damage", "boolean"),
        q("roof_photo", "image", relevant=ref("has_roof_damage")),
        # The idiom a form author actually writes: ask for a description only
        # once a photograph exists.
        q("damage_note", "text", relevant=op("ne", ref("roof_photo"), lit(None))),
    ]),
    [
        # roof_photo is null -> `ne` yields null -> relevance coerces to true
        {"expect": {"relevant": {"damage_note": True}}},
        {"set": {"has_roof_damage": True, "roof_photo": PHOTO},
         "expect": {"relevant": {"roof_photo": True, "damage_note": True}}},
        {"set": {"has_roof_damage": False},
         "expect": {"relevant": {"roof_photo": False}}},
    ],
)

vector(
    "media-003",
    "Two media references are equal when they name the same file",
    "2.1, 4.4.3",
    form("media3", [
        q("before_photo", "image"),
        q("after_photo", "image"),
        q("same_file", "boolean",
          calculate=op("eq", ref("before_photo"), ref("after_photo"))),
    ]),
    [
        # Both null: comparison with a null operand yields null, not false.
        {"expect": {"values": {"same_file": None}}},
        {"set": {"before_photo": PHOTO, "after_photo": OTHER_PHOTO},
         "expect": {"values": {"same_file": False}}},
        {"set": {"after_photo": PHOTO}, "expect": {"values": {"same_file": True}}},
    ],
)

vector(
    "geopoint-001",
    "A geopoint keeps its altitude and accuracy",
    "2.1",
    form("geo1", [
        q("dwelling", "geopoint"),
    ]),
    [
        {"set": {"dwelling": {"lat": -1.286389, "lon": 36.817223,
                              "alt": 1795.0, "accuracy": 8.0}},
         "expect": {"values": {"dwelling": {"lat": -1.286389, "lon": 36.817223,
                                            "alt": 1795.0, "accuracy": 8.0}}}},
        # A point from a source that did not report accuracy is not a perfect
        # point; the members are simply absent, and stay absent.
        {"set": {"dwelling": {"lat": 0.0, "lon": 0.0}},
         "expect": {"values": {"dwelling": {"lat": 0.0, "lon": 0.0}}}},
    ],
)

vector(
    "geopoint-002",
    "Two geopoints are equal when they are the same point, accuracy included",
    "2.1, 4.4.3",
    form("geo2", [
        q("first_reading", "geopoint"),
        q("second_reading", "geopoint"),
        q("unmoved", "boolean",
          calculate=op("eq", ref("first_reading"), ref("second_reading"))),
    ]),
    [
        {"expect": {"values": {"unmoved": None}}},
        # Same coordinates, different accuracy: NOT the same reading. Two fixes
        # of the same doorway, one to 8 m and one to 400 m, are different facts
        # about where the enumerator was standing.
        {"set": {"first_reading": {"lat": -1.28, "lon": 36.81, "accuracy": 8.0},
                 "second_reading": {"lat": -1.28, "lon": 36.81, "accuracy": 400.0}},
         "expect": {"values": {"unmoved": False}}},
        {"set": {"second_reading": {"lat": -1.28, "lon": 36.81, "accuracy": 8.0}},
         "expect": {"values": {"unmoved": True}}},
    ],
)


# --------------------------------------------------------------------------
# Choice membership (spec 6.3)
#
# Before these existed, neither engine read `choices` at all: a select_one
# could hold "purple", a select_multiple could hold "unicorn", and both
# engines called the form valid and finalisable. Thirty-nine vectors never
# saw it because not one of them ever set a value outside its list — the gate
# was untested because nothing had ever knocked on it.
# --------------------------------------------------------------------------

_GENDER = {"kind": "inline", "items": [
    {"value": "male", "label": {"en": "Male"}},
    {"value": "female", "label": {"en": "Female"}}]}
_SYMPTOMS = {"kind": "inline", "items": [
    {"value": "fever", "label": {"en": "Fever"}},
    {"value": "cough", "label": {"en": "Cough"}},
    {"value": "rash", "label": {"en": "Rash"}}]}


def _membership_form(fid):
    return form(fid, [
        q("gender", "select_one", choices=_GENDER, required=True),
        q("symptoms", "select_multiple", choices=_SYMPTOMS),
    ])


vector(
    "choice-001",
    "A value that is in the list is valid — the control for the rest of the set",
    "6.3",
    _membership_form("choice1"),
    [
        {"set": {"gender": "male", "symptoms": ["fever", "rash"]},
         "expect": {"valid": {"gender": True, "symptoms": True},
                    "errors": {"gender": [], "symptoms": []},
                    "formValid": True}},
    ],
)

vector(
    "choice-002",
    "A select_one value outside its list is a `choice` error",
    "6.3",
    _membership_form("choice2"),
    [
        {"set": {"gender": "purple"},
         "expect": {"valid": {"gender": False},
                    "errors": {"gender": ["choice"]},
                    "formValid": False}},
    ],
)

vector(
    "choice-003",
    "Unanswered is not a membership failure: a required blank is `required`, never `choice`",
    "6.3",
    _membership_form("choice3"),
    [
        {"expect": {"valid": {"gender": False, "symptoms": True},
                    "errors": {"gender": ["required"], "symptoms": []},
                    "formValid": False}},
    ],
)

vector(
    "choice-004",
    "An empty select_multiple is unanswered, not a list in which nothing matched",
    "6.3",
    _membership_form("choice4"),
    [
        {"set": {"gender": "male", "symptoms": []},
         "expect": {"valid": {"symptoms": True},
                    "errors": {"symptoms": []},
                    "formValid": True}},
    ],
)

vector(
    "choice-005",
    "One bad value among three makes the field invalid exactly once, not once per value",
    "6.3",
    _membership_form("choice5"),
    [
        {"set": {"gender": "male", "symptoms": ["fever", "unicorn", "rash"]},
         "expect": {"valid": {"symptoms": False},
                    "errors": {"symptoms": ["choice"]},
                    "formValid": False}},
    ],
)

vector(
    "choice-006",
    "Matching is exact: 'Male' does not match the choice 'male'",
    "6.3",
    _membership_form("choice6"),
    [
        {"set": {"gender": "Male"},
         "expect": {"valid": {"gender": False},
                    "errors": {"gender": ["choice"]},
                    "formValid": False}},
    ],
)

vector(
    "choice-007",
    "Matching is exact: 'fever ' does not match the choice 'fever'",
    "6.3",
    _membership_form("choice7"),
    [
        {"set": {"gender": "male", "symptoms": ["fever "]},
         "expect": {"valid": {"symptoms": False},
                    "errors": {"symptoms": ["choice"]},
                    "formValid": False}},
    ],
)

# 008 and 009 are a pair and only mean anything together.
#
# A vector hands an engine one compiled form; an engine never chooses a
# version. So no vector can catch "it validated against the wrong version" —
# that binding lives above the engine, the same structural boundary as break
# 30. What the pair does is make the two versions DISAGREE about one value, so
# that a caller binding to the wrong one produces a visibly wrong result
# instead of the same result either way. Without it, wrong binding is
# undetectable anywhere.

_ROSTER_V1 = {"kind": "inline", "items": [
    {"value": "alice", "label": {"en": "Alice"}},
    {"value": "bob", "label": {"en": "Bob"}},
    {"value": "carol", "label": {"en": "Carol"}}]}
_ROSTER_V2 = {"kind": "inline", "items": [
    {"value": "alice", "label": {"en": "Alice"}},
    {"value": "bob", "label": {"en": "Bob"}}]}

vector(
    "choice-008",
    "Form v1 lists carol, so an answer of carol is valid under v1 (pairs with choice-009)",
    "6.3",
    form("roster", [q("member", "select_one", choices=_ROSTER_V1)], version=1),
    [
        {"set": {"member": "carol"},
         "expect": {"valid": {"member": True}, "errors": {"member": []},
                    "formValid": True}},
    ],
)

vector(
    "choice-009",
    "Form v2 dropped carol, so the same answer is invalid under v2 (pairs with choice-008)",
    "6.3",
    form("roster", [q("member", "select_one", choices=_ROSTER_V2)], version=2),
    [
        {"set": {"member": "carol"},
         "expect": {"valid": {"member": False}, "errors": {"member": ["choice"]},
                    "formValid": False}},
    ],
)



# --------------------------------------------------------------------------
# Dataset-backed choice lists (§3, §3.2)
#
# These compare three things and not one, which is the point of the set. The
# resolved list alone is not enough: an engine that scanned all 38,000 villages
# and one that looked up 12 by index produce the same list and are not
# interchangeable on a handset. So every vector also asserts
#
#   selector    the decomposition, evaluated — what a store is asked for
#   candidates  how many rows came back before the residual ran
#
# and a change that quietly stops narrowing fails on `candidates` while the
# answer stays right. That is the performance contract expressed as data.
# --------------------------------------------------------------------------

_DISTRICTS = [
    {"name": "D01", "label": "Arusha Mjini", "region_id": "TZ01", "urban": "yes"},
    {"name": "D02", "label": "Arusha Vijijini", "region_id": "TZ01", "urban": "no"},
    {"name": "D03", "label": "Moshi", "region_id": "TZ02", "urban": "yes"},
]
_VILLAGES = [
    {"name": "V1", "label": "Mtakuja", "district_id": "D01", "pop": "800"},
    {"name": "V2", "label": "Mbuyuni", "district_id": "D01", "pop": "40"},
    {"name": "V3", "label": "Kibaoni", "district_id": "D02", "pop": "500"},
    {"name": "V4", "label": "Mlimani", "district_id": "D03", "pop": "900"},
]

_REGION = q("region", "select_one", choices={
    "kind": "dataset", "dataset": "regions",
    "valueColumn": "name", "labelColumn": {"en": "label"},
})


def _district(**extra):
    node = {
        "kind": "dataset", "dataset": "districts",
        "valueColumn": "name", "labelColumn": {"en": "label"},
    }
    node.update(extra)
    return q("district", "select_one", choices=node)


_REGIONS = [
    {"name": "TZ01", "label": "Arusha"},
    {"name": "TZ02", "label": "Kilimanjaro"},
]

vector(
    "dataset-001",
    "An unfiltered dataset list resolves to every row, and says it is a full scan",
    "3.2",
    form("ds1", [_REGION]),
    [
        {"expect": {
            "choices": {"region": ["TZ01", "TZ02"]},
            "selector": {"region": {}},
            "candidates": {"region": 2},
            "scans": {"region": True},
        }},
        {"set": {"region": "TZ01"},
         "expect": {"valid": {"region": True}, "errors": {"region": []}}},
    ],
    datasets={"regions": _REGIONS},
)

vector(
    "dataset-002",
    "A value not in the dataset is a choice error, exactly as for an inline list",
    "6.3",
    form("ds2", [_REGION]),
    [
        {"set": {"region": "TZ99"},
         "expect": {"valid": {"region": False}, "errors": {"region": ["choice"]},
                    "formValid": False}},
    ],
    datasets={"regions": _REGIONS},
)

vector(
    "dataset-003",
    "An equality filter becomes a selector: the list narrows and only matching rows are asked for",
    "3.2",
    form("ds3", [_REGION, _district(
        filter=op("eq", ref("$row.region_id"), ref("region")))]),
    [
        # Nothing chosen yet. The selector is null, which matches no row —
        # narrowing to nothing rather than widening to everything (§4.4).
        {"expect": {
            "choices": {"district": []},
            "selector": {"district": {"region_id": None}},
            "candidates": {"district": 0},
            "scans": {"district": False},
        }},
        {"set": {"region": "TZ01"},
         "expect": {
             "choices": {"district": ["D01", "D02"]},
             "selector": {"district": {"region_id": "TZ01"}},
             # Two, not three: the third district was never handed to the
             # engine. This is the assertion the whole design is for.
             "candidates": {"district": 2},
         }},
        {"set": {"region": "TZ02"},
         "expect": {
             "choices": {"district": ["D03"]},
             "candidates": {"district": 1},
         }},
    ],
    datasets={"regions": _REGIONS, "districts": _DISTRICTS},
)

vector(
    "dataset-004",
    "Changing the parent invalidates a child answer that is no longer in its list",
    "3.2",
    form("ds4", [_REGION, _district(
        filter=op("eq", ref("$row.region_id"), ref("region")))]),
    [
        {"set": {"region": "TZ01", "district": "D01"},
         "expect": {"valid": {"district": True}, "formValid": True}},
        # The district is still answered, and its list no longer contains the
        # answer. Nothing re-asks the question, so recalculation has to notice:
        # the selector reads `region`, which is why the field depends on it.
        {"set": {"region": "TZ02"},
         "expect": {
             "values": {"district": "D01"},
             "valid": {"district": False},
             "errors": {"district": ["choice"]},
             "choices": {"district": ["D03"]},
             "formValid": False,
         }},
    ],
    datasets={"regions": _REGIONS, "districts": _DISTRICTS},
)

vector(
    "dataset-005",
    "A non-equality term stays a residual: the selector narrows, the residual filters what is left",
    "3.2",
    form("ds5", [_REGION, q("village", "select_one", choices={
        "kind": "dataset", "dataset": "villages",
        "valueColumn": "name", "labelColumn": {"en": "label"},
        "filter": op(
            "and",
            op("eq", ref("$row.district_id"), lit("D01")),
            op("gt", call("int", ref("$row.pop")), lit(100)),
        ),
    })]),
    [
        {"expect": {
            "selector": {"village": {"district_id": "D01"}},
            # Both D01 villages are candidates; the residual then drops V2.
            "candidates": {"village": 2},
            "choices": {"village": ["V1"]},
            "scans": {"village": False},
        }},
        {"set": {"village": "V2"},
         "expect": {"valid": {"village": False}, "errors": {"village": ["choice"]}}},
    ],
    datasets={"regions": _REGIONS, "villages": _VILLAGES},
)

vector(
    "dataset-006",
    "A filter with no equality term at all is a full scan, and the engine says so",
    "3.2",
    form("ds6", [q("village", "select_one", choices={
        "kind": "dataset", "dataset": "villages",
        "valueColumn": "name", "labelColumn": {"en": "label"},
        "filter": op("gt", call("int", ref("$row.pop")), lit(400)),
    })]),
    [
        {"expect": {
            "selector": {"village": {}},
            # Every row is a candidate. `scans` is what makes that a stated
            # limit rather than a surprise on a 38,000-row list.
            "candidates": {"village": 4},
            "scans": {"village": True},
            "choices": {"village": ["V1", "V3", "V4"]},
        }},
    ],
    datasets={"villages": _VILLAGES},
)

vector(
    "dataset-007",
    "An `or` is never decomposed: the whole filter is residual and nothing narrows",
    "3.2",
    form("ds7", [q("district", "select_one", choices={
        "kind": "dataset", "dataset": "districts",
        "valueColumn": "name", "labelColumn": {"en": "label"},
        "filter": op(
            "or",
            op("eq", ref("$row.region_id"), lit("TZ01")),
            op("eq", ref("$row.urban"), lit("yes")),
        ),
    })]),
    [
        {"expect": {
            "selector": {"district": {}},
            "scans": {"district": True},
            "candidates": {"district": 3},
            "choices": {"district": ["D01", "D02", "D03"]},
        }},
    ],
    datasets={"districts": _DISTRICTS},
)

vector(
    "dataset-008",
    "$row on both sides of an equality is residual, not a selector term",
    "3.2",
    form("ds8", [q("district", "select_one", choices={
        "kind": "dataset", "dataset": "districts",
        "valueColumn": "name", "labelColumn": {"en": "label"},
        "filter": op("eq", ref("$row.region_id"), ref("$row.urban")),
    })]),
    [
        {"expect": {
            "selector": {"district": {}},
            "scans": {"district": True},
            "candidates": {"district": 3},
            "choices": {"district": []},
        }},
    ],
    datasets={"districts": _DISTRICTS},
)

vector(
    "dataset-009",
    "A column bound twice keeps its first binding; the later one becomes residual",
    "3.2",
    form("ds9", [q("district", "select_one", choices={
        "kind": "dataset", "dataset": "districts",
        "valueColumn": "name", "labelColumn": {"en": "label"},
        "filter": op(
            "and",
            op("eq", ref("$row.region_id"), lit("TZ01")),
            op("eq", ref("$row.region_id"), lit("TZ02")),
        ),
    })]),
    [
        # Nothing is merged and nothing is declared contradictory: it selects
        # on TZ01 and the residual then finds none of those are TZ02, which is
        # the right answer arrived at the plain way.
        {"expect": {
            "selector": {"district": {"region_id": "TZ01"}},
            "candidates": {"district": 2},
            "choices": {"district": []},
        }},
    ],
    datasets={"districts": _DISTRICTS},
)

vector(
    "dataset-010",
    "Two selector terms narrow together, and the emitted order is by column name",
    "3.2",
    form("ds10", [_REGION, q("district", "select_one", choices={
        "kind": "dataset", "dataset": "districts",
        "valueColumn": "name", "labelColumn": {"en": "label"},
        # Written urban-first on purpose: the selector must come back sorted.
        "filter": op(
            "and",
            op("eq", ref("$row.urban"), lit("yes")),
            op("eq", ref("$row.region_id"), ref("region")),
        ),
    })]),
    [
        {"set": {"region": "TZ01"},
         "expect": {
             "selector": {"district": {"region_id": "TZ01", "urban": "yes"}},
             "selectorOrder": {"district": ["region_id", "urban"]},
             "candidates": {"district": 1},
             "choices": {"district": ["D01"]},
         }},
    ],
    datasets={"regions": _REGIONS, "districts": _DISTRICTS},
)

vector(
    "dataset-011",
    "A select_multiple checks every chosen value against the dataset separately",
    "6.3",
    form("ds11", [q("visited", "select_multiple", choices={
        "kind": "dataset", "dataset": "districts",
        "valueColumn": "name", "labelColumn": {"en": "label"},
    })]),
    [
        {"set": {"visited": ["D01", "D03"]},
         "expect": {"valid": {"visited": True}, "errors": {"visited": []}}},
        {"set": {"visited": ["D01", "D99"]},
         "expect": {"valid": {"visited": False}, "errors": {"visited": ["choice"]}}},
        # An empty sequence is an unanswered question, not a list in which
        # nothing matched — the same rule as an inline list (§6.3).
        {"set": {"visited": []},
         "expect": {"valid": {"visited": True}, "errors": {"visited": []}}},
    ],
    datasets={"districts": _DISTRICTS},
)

vector(
    "dataset-012",
    "A dataset the device does not hold is an empty list, not a crash",
    "3.2",
    form("ds12", [q("village", "select_one", choices={
        "kind": "dataset", "dataset": "not_synced_yet",
        "valueColumn": "name", "labelColumn": {"en": "label"},
    })]),
    [
        # The honest state for a device that has not synced its reference data:
        # a select with nothing to choose from, which is visible, rather than an
        # exception in the middle of recalculation, which is not.
        {"expect": {
            "choices": {"village": []},
            "candidates": {"village": 0},
        }},
        {"set": {"village": "V1"},
         "expect": {"valid": {"village": False}, "errors": {"village": ["choice"]}}},
    ],
    datasets={"districts": _DISTRICTS},
)

vector(
    "dataset-013",
    "Labels come from labelColumn, per language, in dataset row order",
    "3",
    form(
        "ds13",
        [q("district", "select_one", choices={
            "kind": "dataset", "dataset": "districts_sw",
            "valueColumn": "name",
            "labelColumn": {"en": "label::English (en)", "sw": "label::Swahili (sw)"},
        })],
        languages=["en", "sw"],
    ),
    [
        {"expect": {
            "choices": {"district": ["D01", "D03"]},
            "labels": {"district": [
                {"en": "Arusha Urban", "sw": "Arusha Mjini"},
                {"en": "Moshi", "sw": "Moshi"},
            ]},
        }},
    ],
    datasets={"districts_sw": [
        {"name": "D01", "label::English (en)": "Arusha Urban",
         "label::Swahili (sw)": "Arusha Mjini"},
        {"name": "D03", "label::English (en)": "Moshi",
         "label::Swahili (sw)": "Moshi"},
    ]},
)

vector(
    "dataset-014",
    "A relevance rule and a choice filter reading the same answer both follow it",
    "3.2",
    form("ds14", [
        _REGION,
        _district(filter=op("eq", ref("$row.region_id"), ref("region"))),
        q("note_urban", "text", relevant=op("eq", ref("district"), lit("D01"))),
    ]),
    [
        {"set": {"region": "TZ01", "district": "D01"},
         "expect": {"relevant": {"note_urban": True}, "valid": {"district": True}}},
        # One answer changing must move both, in one pass and in topological
        # order: the list, the membership of what was chosen, and the relevance
        # that reads it.
        {"set": {"region": "TZ02"},
         "expect": {
             "choices": {"district": ["D03"]},
             "valid": {"district": False},
             "relevant": {"note_urban": True},
         }},
    ],
    datasets={"regions": _REGIONS, "districts": _DISTRICTS},
)




# --------------------------------------------------------------------------
# Explicit casts (§4.3.1)
#
# These exist because the dataset vectors found the two engines disagreeing
# about `int("800")` — Kotlin returned null, silently emptying any filter over
# a dataset column, and the Python reference raised ValueError on `int("8a")`,
# which reached the API as a 500. Both had shipped. Neither had a vector,
# because until dataset columns existed nothing in the corpus ever passed text
# to a cast, and a CSV holds nothing but text. Break 44.
# --------------------------------------------------------------------------

_CASTS = [
    q("source", "text"),
    q("as_int", "integer", calculate=call("int", ref("source"))),
    q("as_dec", "decimal", calculate=call("dec", ref("source"))),
    q("as_str", "text", calculate=call("str", ref("source"))),
]

vector(
    "cast-001",
    "int and dec parse a text value — the case a dataset column is always in",
    "4.3.1",
    form("cast1", _CASTS),
    [
        {"set": {"source": "800"},
         "expect": {"values": {"as_int": 800, "as_dec": 800.0, "as_str": "800"}}},
        # Surrounding whitespace only. Nothing else about the text is
        # normalised — a thousands separator is unparseable, not stripped.
        {"set": {"source": "  800  "},
         "expect": {"values": {"as_int": 800, "as_dec": 800.0}}},
        {"set": {"source": "1,000"},
         "expect": {"values": {"as_int": None, "as_dec": None, "as_str": "1,000"}}},
    ],
)

vector(
    "cast-002",
    "int truncates toward zero, from text and from a decimal identically",
    "4.3.1",
    form("cast2", _CASTS),
    [
        # A cast whose result depended on where the value came from would be
        # worse than no cast at all.
        {"set": {"source": "800.7"}, "expect": {"values": {"as_int": 800, "as_dec": 800.7}}},
        {"set": {"source": "-800.7"}, "expect": {"values": {"as_int": -800, "as_dec": -800.7}}},
    ],
)

vector(
    "cast-003",
    "Unparseable text is null, never an error",
    "4.3.1",
    form("cast3", _CASTS),
    [
        # A cast is evaluated on every keystroke over whatever has been typed
        # so far: `int("8a")` on the way to `int("81")` must not stop the form.
        # The Python reference raised ValueError here and it reached the API
        # as a 500.
        {"set": {"source": "8a"},
         "expect": {"values": {"as_int": None, "as_dec": None, "as_str": "8a"},
                    "formValid": True}},
        {"set": {"source": ""},
         "expect": {"values": {"as_int": None, "as_dec": None}}},
    ],
)

vector(
    "cast-004",
    "A cast of null is null, and str of null is null rather than the text 'null'",
    "4.3.1",
    form("cast4", _CASTS),
    [
        {"expect": {"values": {"as_int": None, "as_dec": None, "as_str": None}}},
    ],
)

vector(
    "cast-005",
    "str renders an integer-valued decimal without a trailing .0",
    "4.3.1",
    form("cast5", [
        q("n", "decimal"),
        q("as_str", "text", calculate=call("str", ref("n"))),
        # The reason it matters: a dataset column holds text, so a number has
        # to render back to something that can match one.
        q("matches", "boolean",
          calculate=op("eq", call("str", ref("n")), lit("800"))),
    ]),
    [
        {"set": {"n": 800.0}, "expect": {"values": {"as_str": "800", "matches": True}}},
        {"set": {"n": 800.5}, "expect": {"values": {"as_str": "800.5", "matches": False}}},
    ],
)

vector(
    "cast-006",
    "A boolean is not a number: int and dec are null, str renders it",
    "4.3.1",
    form("cast6", [
        q("flag", "boolean"),
        q("as_int", "integer", calculate=call("int", ref("flag"))),
        q("as_str", "text", calculate=call("str", ref("flag"))),
    ]),
    [
        # §4.4 keeps booleans and numbers apart everywhere else. A dynamically
        # typed engine's int(true) == 1 is exactly the divergence a statically
        # typed one cannot have, and no vector had ever asked.
        {"set": {"flag": True},
         "expect": {"values": {"as_int": None, "as_str": "true"}}},
        {"set": {"flag": False},
         "expect": {"values": {"as_int": None, "as_str": "false"}}},
    ],
)

vector(
    "cast-007",
    "A cast inside a choice filter is what makes a text column comparable",
    "4.3.1",
    form("cast7", [q("village", "select_one", choices={
        "kind": "dataset", "dataset": "villages",
        "valueColumn": "name", "labelColumn": {"en": "label"},
        "filter": op("gte", call("int", ref("$row.pop")), lit(500)),
    })]),
    [
        # The vector that found break 44. With `int` returning null for text
        # the filter matched nothing and the list was silently empty — a
        # village select that shows no villages, on a device holding all of
        # them.
        {"expect": {"choices": {"village": ["V1", "V3", "V4"]}}},
    ],
    datasets={"villages": _VILLAGES},
)




# --------------------------------------------------------------------------
# Trigonometry and sqrt (§4.3), added because a real form needed them
# --------------------------------------------------------------------------

vector(
    "trig-001",
    "The UCL slope correction: a plot radius corrected for gradient",
    "4.3",
    form("slope", [
        q("slope", "integer"),
        # round(15 / sqrt(cos(atan(slope/100))), 2) — the field protocol's own
        # formula, verbatim from UCL_Biomass_Plot_Form.xlsx.
        q("radius", "decimal", calculate=call(
            "round",
            op("div", lit(15), call("sqrt", call("cos", call("atan",
                op("div", ref("slope"), lit(100)))))),
            lit(2),
        )),
    ]),
    [
        # Flat ground: atan(0) = 0, cos(0) = 1, sqrt(1) = 1, so the radius is
        # the uncorrected 15 m.
        {"set": {"slope": 0}, "expect": {"values": {"radius": 15.0}}},
        # A 100% gradient is 45 degrees; the correction is 15 / sqrt(cos(pi/4)).
        {"set": {"slope": 100}, "expect": {"values": {"radius": 17.84}}},
        # Checked against the closed form rather than against the engine:
        # cos(atan(x)) is 1/sqrt(1+x^2), so the whole expression is
        # 15*(1+x^2)^(1/4) — 15.860569 at x=0.5, which rounds to 15.86.
        {"set": {"slope": 50}, "expect": {"values": {"radius": 15.86}}},
        # Unanswered propagates, as everything else does (§4.4).
        {"set": {"slope": None}, "expect": {"values": {"radius": None}}},
    ],
)

vector(
    "trig-002",
    "sqrt of a negative is null, not NaN — a NaN would pass a constraint silently",
    "4.3",
    form("roots", [
        q("n", "decimal"),
        q("root", "decimal", calculate=call("sqrt", ref("n"))),
        # The reason it matters: a NaN compares false to everything including
        # itself, so a constraint over it would pass and nobody would know.
        q("checked", "decimal", constraint=op("gt", ref("root"), lit(0))),
    ]),
    [
        {"set": {"n": 9.0}, "expect": {"values": {"root": 3.0}}},
        {"set": {"n": 0.0}, "expect": {"values": {"root": 0.0}}},
        {"set": {"n": -1.0}, "expect": {"values": {"root": None}}},
    ],
)

vector(
    "trig-003",
    "sin, cos, tan and atan agree between the engines to the precision §4.3 promises",
    "4.3",
    form("angles", [
        q("radians", "decimal"),
        # Rounded to 9 places, deliberately, and §4.3 says why: a
        # transcendental function is permitted one unit in the last place by
        # both platforms' libraries, so bit-identity is not something either
        # engine can promise — `distance` was found differing in exactly that
        # way (break 50). Nine places is eleven orders of magnitude beyond any
        # survey use and comfortably inside the guarantee.
        q("s", "decimal", calculate=call("round", call("sin", ref("radians")), lit(9))),
        q("c", "decimal", calculate=call("round", call("cos", ref("radians")), lit(9))),
        q("t", "decimal", calculate=call("round", call("tan", ref("radians")), lit(9))),
        q("a", "decimal", calculate=call("round", call("atan", ref("radians")), lit(9))),
    ]),
    [
        {"set": {"radians": 0.0},
         "expect": {"values": {"s": 0.0, "c": 1.0, "t": 0.0, "a": 0.0}}},
        {"set": {"radians": 1.0},
         "expect": {"values": {
             "s": 0.841470985,
             "c": 0.540302306,
             "t": 1.557407725,
             "a": 0.785398163,
         }}},
        # Negative angles, because a slope can go downhill.
        {"set": {"radians": -1.0},
         "expect": {"values": {
             "s": -0.841470985,
             "c": 0.540302306,
             "t": -1.557407725,
             "a": -0.785398163,
         }}},
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
