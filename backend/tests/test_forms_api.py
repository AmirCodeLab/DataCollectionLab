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
    assert set(body) == {"formId", "version", "fieldCount", "evaluationOrder", "warnings"}
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
