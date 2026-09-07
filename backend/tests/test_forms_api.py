"""The stateless form endpoints: /health, /forms/compile and /forms/evaluate.

None of these touches the database, so they are the routes whose bodies can be
checked directly rather than described. That matters more than it looks: the
OpenAPI contract says what each returns, and a contract nothing ever compares
against a real response is a document about intentions. `test_openapi_contract`
checks that the document names a schema; these check that the server sends what
the schema says.

/forms/evaluate is the case that needed it. It used to return `dict[str, Any]`,
which FastAPI documents as an object with no fields — so the console had no
type for it, and the engine's `FieldState.to_dict()` was the de facto contract:
whatever the engine happened to emit that week.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
from typing import Any

import httpx
import pytest

from app.main import app

VECTORS = pathlib.Path(__file__).resolve().parents[2] / "conformance" / "vectors"


def call(method: str, url: str, **kwargs: Any) -> httpx.Response:
    async def main() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, url, **kwargs)

    return asyncio.run(main())


@pytest.fixture(scope="module")
def form() -> dict[str, Any]:
    """A form from the conformance corpus, so the fixture cannot rot on its own."""
    return json.loads((VECTORS / "calculate-001.json").read_text())["form"]


def test_health_reports_status_and_environment() -> None:
    response = call("GET", "/health")
    assert response.status_code == 200
    # Exactly these two keys. The console reads both — `environment` decides
    # whether it is looking at production data — and a probe that grew a third
    # field without the contract growing one is the drift being prevented.
    assert response.json() == {"status": "ok", "environment": "development"}


def test_compile_reports_the_evaluation_order(form: dict[str, Any]) -> None:
    response = call("POST", "/api/v1/forms/compile", json={"form": form})
    assert response.status_code == 200, response.text

    body = response.json()
    # Asserted against the JSON rather than parsed back through the model:
    # the model would agree with itself either way, and what the console reads
    # is these key names.
    assert set(body) == {
        "formId",
        "version",
        "fieldCount",
        "evaluationOrder",
        "warnings",
        "neverShown",
        "screens",
        "instancePlans",
    }
    assert body["formId"] == "calc1"
    assert body["fieldCount"] == len(body["evaluationOrder"])

    order = body["evaluationOrder"]
    # Topological, ties broken by document order (Form IR §7). `a` feeds `b`
    # feeds `c`, and the document lists them backwards — so this ordering is
    # the dependency graph and not the file.
    assert order.index("a") < order.index("b") < order.index("c")


def test_compile_refuses_a_form_that_does_not_compile(form: dict[str, Any]) -> None:
    """A §10 error is a 422 carrying what is wrong, not a 200 with warnings."""
    broken = {
        **form,
        "children": [
            {
                "type": "question",
                "id": "a",
                "dataType": "integer",
                "label": {"en": "A"},
                "calculate": {"op": "ref", "path": "nope"},
            }
        ],
    }
    response = call("POST", "/api/v1/forms/compile", json={"form": broken})
    assert response.status_code == 422, response.text
    assert "nope" in response.text


def test_evaluate_returns_a_snapshot_per_field(form: dict[str, Any]) -> None:
    response = call(
        "POST", "/api/v1/forms/evaluate", json={"form": form, "answers": {"a": 1}}
    )
    assert response.status_code == 200, response.text

    body = response.json()
    assert set(body) == {"valid", "fields", "answers"}
    # b = a + 10, c = b * 2. Recalculation ran in dependency order, so both
    # derived fields are current in one pass rather than one pass behind.
    assert body["answers"]["b"] == 11
    assert body["answers"]["c"] == 22

    # Exactly the seven the contract names — `readOnly` camelCased on the wire
    # like every other response field here, which is why the console reads it
    # without a translation layer.
    assert set(body["fields"]["a"]) == {
        "path",
        "relevant",
        "required",
        "readOnly",
        "value",
        "valid",
        "errors",
    }
    assert body["fields"]["a"]["relevant"] is True


def test_evaluate_reports_every_field_including_the_derived_ones(
    form: dict[str, Any],
) -> None:
    """`fields` is every field; `answers` is the relevant ones (Form IR §4.4).

    A non-relevant field retains its value and is excluded from export, so the
    two are not the same set and a client needs both — which is why the
    response has two members and not one.
    """
    body = call("POST", "/api/v1/forms/evaluate", json={"form": form}).json()

    assert set(body["fields"]) == {"a", "b", "c"}
    assert set(body["answers"]) <= set(body["fields"])


# --- companion files over the wire ----------------------------------------
#
# The multipart half of the import endpoint. Worth testing at this level rather
# than only against `import_workbook`: an `UploadFile` list, a filename that
# survives the encoding, and a part with no filename at all are all things only
# the HTTP layer can get wrong, and the last one is a real browser behaviour.


def _workbook(rows: list[list[str | None]]) -> bytes:
    import io

    import openpyxl

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "survey"
    for row in rows:
        sheet.append(row)
    book.create_sheet("choices").append(["list_name", "name", "label"])
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


DATASET_FORM = [
    ["type", "name", "label"],
    ["select_one_from_file villages.csv", "village", "Village"],
]


def test_import_reads_a_companion_csv_sent_beside_the_workbook() -> None:
    response = call(
        "POST",
        "/api/v1/forms/import",
        files=[
            ("file", ("survey.xlsx", _workbook(DATASET_FORM), _XLSX)),
            ("datasets", ("villages.csv", b"name,label\nV01,Mtakuja\n", "text/csv")),
        ],
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert len(body["datasets"]) == 1
    dataset = body["datasets"][0]
    # camelCase on the wire, like everything else the console reads.
    assert dataset["fileName"] == "villages.csv"
    assert dataset["key"] == "villages"
    assert dataset["rowCount"] == 1
    assert dataset["valueColumn"] == "name"
    assert dataset["checksum"].startswith("sha256:")
    # The rows are deliberately NOT in the response: this endpoint answers
    # "what would this become?" and a village list would make it megabytes.
    assert "rows" not in dataset


def test_import_without_the_companion_files_names_each_missing_one() -> None:
    response = call(
        "POST",
        "/api/v1/forms/import",
        files=[("file", ("survey.xlsx", _workbook(DATASET_FORM), _XLSX))],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["publishable"] is False
    codes = {d["code"] for d in body["diagnostics"]}
    assert "companion_file_missing" in codes
    assert body["datasets"] == []


def test_a_companion_part_with_an_empty_filename_is_refused() -> None:
    """A browser can send `filename=""`, and there is no way to tell which
    `select_one_from_file` row it answers. Guessing would be worse.

    The body is assembled by hand because an HTTP client will not produce this:
    passing an empty name makes httpx send an ordinary form field instead, and
    the case being guarded is a real file part whose name is empty.
    """
    boundary = "----dcptest"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="survey.xlsx"\r\n'
        f"Content-Type: {_XLSX}\r\n\r\n"
    ).encode() + _workbook(DATASET_FORM) + (
        f"\r\n--{boundary}\r\n"
        'Content-Disposition: form-data; name="datasets"; filename=""\r\n'
        "Content-Type: text/csv\r\n\r\n"
        "name,label\r\nV01,Mtakuja\r\n"
        f"--{boundary}--\r\n"
    ).encode()

    response = call(
        "POST",
        "/api/v1/forms/import",
        content=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    assert response.status_code == 400, response.text
    assert "no filename" in response.json()["detail"]


def test_the_same_companion_uploaded_twice_is_refused() -> None:
    response = call(
        "POST",
        "/api/v1/forms/import",
        files=[
            ("file", ("survey.xlsx", _workbook(DATASET_FORM), _XLSX)),
            ("datasets", ("villages.csv", b"name,label\nV01,a\n", "text/csv")),
            ("datasets", ("villages.csv", b"name,label\nV01,b\n", "text/csv")),
        ],
    )
    assert response.status_code == 400
    assert "more than once" in response.json()["detail"]


_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_compile_returns_the_screen_plan_the_engine_built() -> None:
    """§11.1's partition, over the wire, including the parts that surprise people.

    The console must not derive this. A screen plan computed in TypeScript is a
    third implementation of §11.1 — after the two the vectors compare — and it
    would be the one deciding what an author believes their form does. So the
    contract carries it, and this asserts the three rules an author is most
    likely to be surprised by rather than only the happy shape.
    """
    form = {
        "irVersion": "0.1",
        "formId": "plan1",
        "version": 1,
        "defaultLanguage": "en",
        "languages": ["en"],
        "children": [
            {"type": "question", "id": "a", "dataType": "text", "label": {"en": "A"}},
            # A calculate produces no screen and appears on none.
            {
                "type": "question",
                "id": "total",
                "dataType": "integer",
                "label": {"en": "T"},
                "calculate": {"op": "lit", "value": 1},
            },
            # A field-list is one screen, and it flattens a nested plain group.
            {
                "type": "group",
                "id": "sec",
                "label": {"en": "Sec"},
                "appearance": "field-list",
                "children": [
                    {"type": "question", "id": "b", "dataType": "text", "label": {"en": "B"}},
                    {
                        "type": "group",
                        "id": "inner",
                        "label": {"en": "In"},
                        "children": [
                            {
                                "type": "question",
                                "id": "c",
                                "dataType": "text",
                                "label": {"en": "C"},
                            }
                        ],
                    },
                ],
            },
            # A repeat is exactly one screen, at any instance count, and its
            # children are partitioned separately into an instance plan.
            {
                "type": "repeat",
                "id": "members",
                "label": {"en": "M"},
                "minInstances": 3,
                "children": [
                    {"type": "question", "id": "name", "dataType": "text", "label": {"en": "N"}}
                ],
            },
        ],
    }
    response = call("POST", "/api/v1/forms/compile", json={"form": form})
    assert response.status_code == 200, response.text
    body = response.json()

    screens = body["screens"]
    assert [s["kind"] for s in screens] == ["questions", "questions", "repeat"]
    # `total` is a calculate: no screen of its own and on nobody else's.
    assert [s["questionIds"] for s in screens] == [["a"], ["b", "c"], []]
    # The field-list flattened `inner` into one screen and names the group.
    assert screens[1]["groupId"] == "sec"
    # One repeat screen whatever the instance count, and it names its repeat.
    assert screens[2]["repeatId"] == "members"

    # The instance plan is a separate axis, indexed within the instance.
    assert body["instancePlans"] == {
        "members": [
            {
                "index": 0,
                "kind": "questions",
                "questionIds": ["name"],
                "repeatId": None,
                "groupId": None,
                "sectionId": "members",
            }
        ]
    }


def test_palette_is_served_from_the_registry_not_a_list_in_the_code() -> None:
    """The palette equals the committed registry, read at request time.

    Asserted against the file rather than against an expected list, and that is
    the point: an expected list here would be the third hand-maintained copy of
    the thing `specs/collectable-types-v0.1.json` exists to keep singular. This
    fails if the registry gains a type and the API does not, which is the drift
    that matters — the day `time` ships, the palette must gain it with no
    console change and no change here either.
    """
    import json
    import pathlib

    registry = json.loads(
        (pathlib.Path(__file__).resolve().parents[2] / "specs" / "collectable-types-v0.1.json")
        .read_text()
    )

    response = call("GET", "/api/v1/forms/palette")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["version"] == str(registry["version"])

    collectable = sorted(t["dataType"] for t in body["types"] if t["status"] == "collectable")
    assert collectable == sorted(registry["collectable"])

    # Every §2.1 dataType appears, so a builder can show the ones it cannot
    # offer rather than silently omitting them — a type missing from a palette
    # is indistinguishable from one that does not exist.
    assert len(body["types"]) > len(collectable)

    # The registry's own sentence, verbatim. A console paraphrase would be a
    # second statement of when a type arrives and the copy nobody updates.
    notes = registry.get("notes", {})
    for entry in body["types"]:
        if entry["dataType"] in notes:
            assert entry["note"] == notes[entry["dataType"]]

    sources = {t["dataType"]: t["status"] for t in body["choiceSources"]}
    for kind in registry["choiceSources"]:
        assert sources[kind] == "collectable"



def test_expressions_parses_text_and_renders_it_back() -> None:
    """Both directions, and the canonical text is what the next load shows."""
    response = call(
        "POST",
        "/api/v1/forms/expressions",
        json={"text": "${age} >= 18 and is_null(${exit_reason})"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["error"] is None
    assert body["expression"]["op"] == "and"
    # `is_null` has no XLSForm spelling — the importer refuses it and this
    # surface accepts it, because six of §4.3's functions would otherwise have
    # no surface at all in the field that exists for what the visual editor
    # cannot express.
    assert body["expression"]["args"][1] == {
        "op": "call",
        "fn": "is_null",
        "args": [{"op": "ref", "path": "exit_reason"}],
    }
    assert body["text"] == "${age} >= 18 and is_null(${exit_reason})"


def test_a_half_written_expression_is_a_200_with_an_offset() -> None:
    """Not a 422. Most of what a code field sends is unfinished by definition.

    The field asks on every pause in typing, so an error status for "the author
    has not finished the sentence" would make the normal case look like a
    failure — and a console that learned to ignore 422 here would ignore the
    ones that matter.
    """
    response = call("POST", "/api/v1/forms/expressions", json={"text": "${age} >= "})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["expression"] is None
    assert body["error"] == "the expression ends sooner than expected"
    # The caret goes at the end of the expression, which is where the author
    # is. Counted in the string the caller sent, not in a trimmed copy of it.
    assert body["offset"] == len("${age} >=")


def test_an_ast_with_no_surface_says_so_rather_than_inventing_one() -> None:
    """`in` has no XLSForm spelling, so no author can have typed one."""
    response = call(
        "POST",
        "/api/v1/forms/expressions",
        json={
            "expression": {
                "op": "in",
                "args": [{"op": "ref", "path": "a"}, {"op": "lit", "value": "x"}],
            }
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["text"] is None
    assert "no surface syntax" in body["error"]


def test_compile_reports_which_questions_are_never_shown() -> None:
    """`neverShown` is the finding behind the §10.3 warning, structured.

    A builder's badge reads ids from it rather than parsing the warning's
    prose — the console renders diagnostics, it never composes or parses them.
    Reachability vector 004 is the same shape.
    """
    form = {
        "irVersion": "0.1",
        "formId": "staged",
        "version": 1,
        "title": {"en": "Staged"},
        "defaultLanguage": "en",
        "languages": ["en"],
        "children": [
            {
                "type": "question",
                "id": "later",
                "dataType": "text",
                "label": {"en": "Later"},
                "relevant": {"op": "lit", "value": False},
            },
            {"type": "question", "id": "now", "dataType": "text", "label": {"en": "Now"}},
        ],
    }
    response = call("POST", "/api/v1/forms/compile", json={"form": form})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["neverShown"] == ["later"]
    assert body["warnings"] == ["later: unreachable relevance (statically false)"]


def test_compile_refuses_a_container_that_never_appears() -> None:
    """The same gate publish runs, so the builder learns while editing.
    Reachability vector 003 is the shape."""
    form = {
        "irVersion": "0.1",
        "formId": "dead",
        "version": 1,
        "title": {"en": "Dead"},
        "defaultLanguage": "en",
        "languages": ["en"],
        "children": [
            {
                "type": "group",
                "id": "g",
                "label": {"en": "G"},
                "relevant": {"op": "lit", "value": False},
                "children": [
                    {"type": "question", "id": "a", "dataType": "text", "label": {"en": "A"}}
                ],
            },
            {"type": "question", "id": "q", "dataType": "text", "label": {"en": "Q"}},
        ],
    }
    response = call("POST", "/api/v1/forms/compile", json={"form": form})
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == [
        "'g' is never shown: its relevant is statically false, so 1 question(s) inside it "
        "would never be asked: 'a' (Form IR §10.3)."
    ]
