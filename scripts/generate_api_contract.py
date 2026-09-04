#!/usr/bin/env python3
"""Regenerate the API contract from the app, and the console's types from it.

    python scripts/generate_api_contract.py            # write both files
    python scripts/generate_api_contract.py --check     # fail if either differs

Two outputs, one source:

    app.main:app  ──►  specs/openapi.json  ──►  web/src/api/types.ts

The FastAPI app is the contract. `specs/openapi.json` is a snapshot of what it
generates, committed so that a change to the API shows up as a change to a
reviewable file; CI runs `--check` and a diff there is a red build. Neither
output is ever edited by hand — an edit is overwritten by the next run, and
until then it is a lie about what the server does.

`web/src/api/types.ts` is generated the rest of the way rather than hand-copied
because that copy is what drifts. Before this existed, the console mirrored
`SUBMISSION_STATUSES` from the database CHECK constraint by hand and needed its
own test to notice when the two parted company.

Why a generator here rather than `openapi-typescript` from npm: the console
needs the closed sets at RUNTIME as well as at type-check time — a status
filter is a dropdown, and a dropdown needs an array. Type-only generators emit
`type SubmissionStatus = "draft" | ...` and nothing to iterate, so the array
would go back to being hand-written, which is the thing being removed. This
also keeps the whole contract chain on one toolchain: the CI job that installs
Python already has everything needed to check it.

The TypeScript emitter handles exactly the JSON Schema that FastAPI and
Pydantic produce, and raises `UnsupportedSchema` on anything else rather than
falling back to `unknown`. A silent `unknown` is how a generated client stops
being a contract: it type-checks, it runs, and it has quietly stopped
describing the API.
"""

from __future__ import annotations

import argparse
import difflib
import json
import pathlib
import platform
import re
import sys
from typing import Any

REPO = pathlib.Path(__file__).resolve().parents[1]
OPENAPI = REPO / "specs" / "openapi.json"
CONSOLE_TYPES = REPO / "web" / "src" / "api" / "types.ts"

REGENERATE = "python scripts/generate_api_contract.py"


class UnsupportedSchema(Exception):
    """A JSON Schema construct the emitter has no honest TypeScript for."""


# --------------------------------------------------------------------------
# The OpenAPI document


def build_openapi() -> dict[str, Any]:
    """The schema the running app serves at /openapi.json."""
    # Imported here, not at module scope: the package only becomes importable
    # after this line, and a script that fails on import cannot print the
    # `pip install -e ".[dev]"` that would fix it.
    sys.path.insert(0, str(REPO / "backend"))
    from app.main import app

    schema: dict[str, Any] = app.openapi()
    return schema


def render_openapi(schema: dict[str, Any]) -> str:
    # Key order as FastAPI produced it — the document reads in route order,
    # which is how a reviewer reads a diff of it. Two spaces, trailing newline,
    # so `git diff` on a contract change shows the field, not the whole file.
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


# --------------------------------------------------------------------------
# TypeScript


def ts_type(schema: dict[str, Any], *, where: str) -> str:
    """One JSON Schema node as a TypeScript type expression.

    `where` is a JSON-pointer-ish trail used only in error messages: a
    generator that fails has to say which field it failed on, or the next
    person is reading 5000 lines of JSON to find out.
    """
    if "$ref" in schema:
        return ref_name(schema["$ref"], where=where)

    # Pydantic wraps a $ref that has siblings (a description, a default) in a
    # single-element allOf. The wrapper carries no type information of its own.
    if "allOf" in schema and len(schema["allOf"]) == 1:
        return ts_type(schema["allOf"][0], where=where)

    if "anyOf" in schema:
        members = [ts_type(m, where=f"{where}/anyOf") for m in schema["anyOf"]]
        return " | ".join(dict.fromkeys(members))

    if "enum" in schema:
        return " | ".join(json.dumps(v) for v in schema["enum"])

    if "const" in schema:
        return json.dumps(schema["const"])

    # `{}` — Pydantic's rendering of `Any`. It genuinely means "any JSON", so
    # `unknown` is accurate here rather than a fallback: the caller is forced
    # to narrow it before use, which is what `Any` deserves.
    if not schema.keys() - {"title", "description", "default"}:
        return "unknown"

    kind = schema.get("type")

    if kind == "string":
        # format date-time included: it arrives as an ISO string and stays one.
        return "string"
    if kind in ("integer", "number"):
        return "number"
    if kind == "boolean":
        return "boolean"
    if kind == "null":
        return "null"

    if kind == "array":
        items = schema.get("items")
        if items is None:
            raise UnsupportedSchema(f"{where}: array with no `items`")
        inner = ts_type(items, where=f"{where}/items")
        # Parenthesise unions so `A | B[]` cannot be read as `A | (B[])`.
        return f"({inner})[]" if "|" in inner else f"{inner}[]"

    if kind == "object":
        additional = schema.get("additionalProperties")
        if schema.get("properties"):
            raise UnsupportedSchema(
                f"{where}: inline object with properties. Give it a Pydantic "
                "model so it becomes a named schema the console can import."
            )
        if additional is None or additional is True:
            return "Record<string, unknown>"
        if additional is False:
            raise UnsupportedSchema(f"{where}: object that permits no properties")
        return f"Record<string, {ts_type(additional, where=f'{where}/additionalProperties')}>"

    raise UnsupportedSchema(f"{where}: no TypeScript for {json.dumps(schema)[:200]}")


def ref_name(ref: str, *, where: str) -> str:
    prefix = "#/components/schemas/"
    if not ref.startswith(prefix):
        raise UnsupportedSchema(f"{where}: $ref outside components/schemas: {ref}")
    return ref[len(prefix) :]


def screaming_plural(name: str) -> str:
    """`SubmissionStatus` -> `SUBMISSION_STATUSES`, the name of its value array."""
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", name).upper()
    if snake.endswith(("S", "X", "Z")) or snake.endswith(("CH", "SH")):
        return snake + "ES"
    return snake + "S"


def doc_comment(text: str | None, indent: str = "") -> list[str]:
    if not text:
        return []
    lines = text.strip().splitlines()
    if len(lines) == 1:
        return [f"{indent}/** {lines[0]} */"]
    out = [f"{indent}/**"]
    out += [f"{indent} * {line}".rstrip() for line in lines]
    out.append(f"{indent} */")
    return out


LINE_WIDTH = 96


def emit_enum(name: str, values: list[Any], schema: dict[str, Any]) -> list[str]:
    """A closed set of strings, as both a runtime array and a type.

    The array is the point. The console renders a status filter and a key-role
    dropdown from these, and an array it can map over is the difference between
    generating the console's types and generating half of them.
    """
    out = doc_comment(schema.get("description"))
    array = screaming_plural(name)
    literals = [json.dumps(v) for v in values]

    one_line = f"export const {array} = [{', '.join(literals)}] as const;"
    if len(one_line) <= LINE_WIDTH:
        out.append(one_line)
    else:
        out.append(f"export const {array} = [")
        out += [f"  {literal}," for literal in literals]
        out.append("] as const;")

    out.append("")
    out.append(f"export type {name} = (typeof {array})[number];")
    return out


def emit_interface(name: str, schema: dict[str, Any]) -> list[str]:
    out = doc_comment(schema.get("description"))
    out.append(f"export interface {name} {{")
    required = set(schema.get("required", ()))
    for prop, sub in schema.get("properties", {}).items():
        out += doc_comment(sub.get("description"), indent="  ")
        rendered = ts_type(sub, where=f"{name}.{prop}")
        # Optional in the schema means the server may omit the key entirely —
        # `?` and not just `| undefined`, because that is what the reader has
        # to handle.
        out.append(f"  {prop}{'' if prop in required else '?'}: {rendered};")
    out.append("}")
    return out


HEADER = f"""/* GENERATED FILE — DO NOT EDIT.
 *
 * Generated from specs/openapi.json, which is itself generated from the
 * FastAPI app. To change anything here, change the Pydantic model it comes
 * from and run:
 *
 *     {REGENERATE}
 *
 * An edit made here survives exactly until the next run of that command, and
 * in the meantime it says something about the API that is not true.
 */
"""


def render_types(schema: dict[str, Any]) -> str:
    schemas: dict[str, Any] = schema["components"]["schemas"]
    blocks: list[str] = []

    # Alphabetical. Component order in the document follows whichever route
    # FastAPI walked first, so it reshuffles when a route moves and the diff
    # then shows a hundred moved lines instead of the one that changed.
    for name in sorted(schemas):
        node = schemas[name]
        if "enum" in node:
            blocks.append("\n".join(emit_enum(name, node["enum"], node)))
        elif "const" in node:
            # A `Literal` of one member. Pydantic emits `const` rather than a
            # one-element `enum`, but it is the same kind of thing and the
            # console should not have to know which: a closed set gets an
            # array whether it has one member or six.
            blocks.append("\n".join(emit_enum(name, [node["const"]], node)))
        elif node.get("type") == "object" or "properties" in node:
            blocks.append("\n".join(emit_interface(name, node)))
        else:
            # A named schema that is neither: an alias for a scalar or a union.
            body = ts_type(node, where=name)
            blocks.append("\n".join(doc_comment(node.get("description")) + [
                f"export type {name} = {body};"
            ]))

    return HEADER + "\n" + "\n\n".join(blocks) + "\n"


# --------------------------------------------------------------------------

DIFF_LINES = 120


PYTHON_VERSION_FILE = REPO / ".python-version"


def warn_on_a_different_interpreter() -> None:
    """Say so when this interpreter is not the one CI checks the file against.

    The document is byte-for-byte what the toolchain that wrote it emits, and
    the toolchain includes the interpreter: FastAPI fills a response
    description it was not given from `http.HTTPStatus(code).phrase`, which is
    the standard library's table, and CPython renamed 413 in 3.13. Generating
    on 3.14 and checking on 3.12 therefore produced a one-line difference in a
    5000-line file with nothing in the repository to explain it — twice, on
    main. This is a warning and not a refusal because after that break the
    known-varying descriptions are stated explicitly, so the output should now
    be the same on both; if it is not, this line is the first place to look.
    """
    if not PYTHON_VERSION_FILE.exists():
        return
    pinned = PYTHON_VERSION_FILE.read_text(encoding="utf-8").strip()
    running = ".".join(platform.python_version_tuple()[:2])
    if pinned and running != pinned:
        print(
            f"warning: generating on python {running}; CI checks this file on "
            f"{pinned} (.python-version). If the check fails there and passes "
            "here, that difference is the first thing to suspect.",
            file=sys.stderr,
        )


def toolchain() -> str:
    """The versions the document depends on, for a failure message to name.

    The check compares bytes, so anything that changes a byte is part of the
    answer to "why does this differ" — and the first two runs that failed here
    were read as an API drift when the API had not moved.
    """
    import fastapi
    import pydantic

    return (
        f"Generated by: python {platform.python_version()}, "
        f"fastapi {fastapi.__version__}, pydantic {pydantic.VERSION}"
    )


def print_diff(path: pathlib.Path, generated: str) -> None:
    """What actually differs, truncated — the file is 5000 lines.

    Without this the message named the file and stopped, so a CI failure said
    only that something in a generated document had moved. Reproducing it meant
    having the same toolchain to hand, which is exactly what you do not have
    when the difference is that CI's toolchain is not yours.
    """
    rel = path.relative_to(REPO)
    committed = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    diff = list(
        difflib.unified_diff(
            committed,
            generated.splitlines(),
            fromfile=f"{rel} (committed)",
            tofile=f"{rel} (generated by this run)",
            lineterm="",
        )
    )
    for line in diff[:DIFF_LINES]:
        print(line)
    if len(diff) > DIFF_LINES:
        print(f"... {len(diff) - DIFF_LINES} more diff lines")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; exit 1 if either file differs from what the app generates",
    )
    args = parser.parse_args()

    warn_on_a_different_interpreter()

    schema = build_openapi()
    outputs = {
        OPENAPI: render_openapi(schema),
        CONSOLE_TYPES: render_types(schema),
    }

    if not args.check:
        for path, content in outputs.items():
            path.write_text(content, encoding="utf-8")
            print(f"wrote {path.relative_to(REPO)}")
        return 0

    stale = [
        path
        for path, content in outputs.items()
        if not path.exists() or path.read_text(encoding="utf-8") != content
    ]
    if not stale:
        print("contract is in step with the app")
        return 0

    print("The committed API contract is not what the app generates:\n")
    for path in stale:
        print(f"  {path.relative_to(REPO)}")
    print()
    for path in stale:
        print_diff(path, outputs[path])
    print(
        f"Run `{REGENERATE}` and commit the result. An API change and its "
        "contract change belong in the same commit — that is the whole point "
        "of committing the contract.\n"
        "\nIf you did not touch the API, one of the versions below moved since "
        "the file was generated: the document is byte-for-byte what this "
        "toolchain emits, so a different interpreter or a different fastapi or "
        "pydantic is a different document. Regenerating is still the fix; the "
        "diff above shows whether it was boilerplate.\n"
    )
    print(toolchain())
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
