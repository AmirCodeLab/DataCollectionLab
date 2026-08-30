"""Document-shape validation — Form IR §10.1, run before anything else.

This answers "is this a Form IR document at all", which is a different question
from "is this form publishable". Nothing in §10.2 applies to a document that
fails here: there are no fields to resolve references between and no graph to
look for cycles in.

Why this file exists at all. The Kotlin engine gets this gate free — `FormIr` is
a `@Serializable` data class, so a document missing `formId` is refused by the
deserialiser before `CompiledForm` ever sees it. Python has no parse step: a raw
`dict[str, Any]` went straight into the compiler, which read `ir["formId"]` and
raised `KeyError`. That is not a stricter engine and a looser one, it is one
engine that refuses and one that crashes — nine document shapes reached the API
as 500s, including a `version` spelling itself `"one"`.

The vectors in `conformance/malformed` are the cross-engine contract for this,
and they exist as a separate set because `conformance/vectors` cannot express a
refusal: every step there assumes a form that compiled.
"""

from __future__ import annotations

from typing import Any

from .expression import CompileError

# The IR version this engine implements. Spec §9: accept the same major version
# and any equal or lower minor version.
SUPPORTED_IR_VERSION = (0, 1)

NODE_TYPES = ("question", "group", "repeat")


class DocumentError(CompileError):
    """A §10.1 document error: this is not a Form IR document.

    A `CompileError` subclass on purpose. Every caller that already refuses a
    form on `CompileError` — the API routes, `check_publishable`,
    `scripts/seed_dev.py` — refuses this too without being changed, which is
    what stops the gate having holes on the day it lands. `reason` and `where`
    are for callers that want to say more than "invalid".
    """

    def __init__(self, reason: str, where: str, message: str) -> None:
        super().__init__(f"{where}: {message}" if where else message)
        self.reason = reason
        self.where = where
        self.detail = message


def _require(node: Any, key: str, kind: type | tuple[type, ...], where: str, label: str) -> Any:
    """One required field of an object: present, and of the right JSON type."""
    if key not in node:
        raise DocumentError("missing_field", f"{where}{key}", f"{label} is required")
    value = node[key]
    # bool is a subclass of int in Python and is not an integer in JSON. Left
    # unguarded, `"version": true` would compile to version 1.
    if kind is int and isinstance(value, bool):
        raise DocumentError("wrong_type", f"{where}{key}", f"{label} must be an integer")
    if not isinstance(value, kind):
        raise DocumentError("wrong_type", f"{where}{key}", f"{label} must be {_name(kind)}")
    return value


def _name(kind: type | tuple[type, ...]) -> str:
    names = {str: "a string", int: "an integer", list: "an array", dict: "an object"}
    if isinstance(kind, tuple):
        return " or ".join(names.get(k, k.__name__) for k in kind)
    return names.get(kind, kind.__name__)


def check_ir_version(raw: str) -> None:
    """Spec §9. Refuse a version this engine does not implement.

    Not advisory, and not only about the major number: v0.2 may define an
    expression node or a node kind that this engine would silently ignore,
    producing a form that looks correct and evaluates by the wrong rules. The
    enumerator whose device is a version behind has to be told to update, and a
    form that opens and quietly misbehaves tells them nothing.
    """
    parts = raw.split(".")
    try:
        major, minor = int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        raise DocumentError(
            "unknown_ir_version",
            "irVersion",
            f"{raw!r} is not a version number. This engine implements "
            f"{SUPPORTED_IR_VERSION[0]}.{SUPPORTED_IR_VERSION[1]}.",
        ) from None

    supported_major, supported_minor = SUPPORTED_IR_VERSION
    if major != supported_major or minor > supported_minor:
        raise DocumentError(
            "unknown_ir_version",
            "irVersion",
            f"this engine implements Form IR {supported_major}.{supported_minor} and "
            f"cannot read {raw}. Reading what it recognises would produce a form "
            "that evaluates by the wrong rules.",
        )


def check_document(ir: Any) -> None:
    """Raise DocumentError unless `ir` is structurally a Form IR document.

    Checks shape only. Everything semantic — duplicate ids, unresolvable
    references, cycles — belongs to §10.2 and stays in the compiler, which can
    assume from here that the keys it reads exist and hold what they say.
    """
    if not isinstance(ir, dict):
        raise DocumentError("not_an_object", "", "a form must be a JSON object")

    check_ir_version(_require(ir, "irVersion", str, "", "irVersion"))
    _require(ir, "formId", str, "", "formId")
    _require(ir, "version", int, "", "version")

    # Absent `children` is a form with no nodes, which compiles. That is not
    # the same as `children` present holding something that is not an array.
    if "children" in ir:
        _check_children(ir["children"], "children")


def _check_children(children: Any, where: str) -> None:
    if not isinstance(children, list):
        raise DocumentError("wrong_type", where, "children must be an array")

    for index, node in enumerate(children):
        at = f"{where}[{index}]"
        if not isinstance(node, dict):
            raise DocumentError("not_an_object", at, "a node must be a JSON object")

        node_type = _require(node, "type", str, f"{at}.", "type")
        if node_type not in NODE_TYPES:
            raise DocumentError(
                "unknown_node_type",
                f"{at}.type",
                f"{node_type!r} is not a node type. Expected one of "
                f"{', '.join(NODE_TYPES)}.",
            )

        _require(node, "id", str, f"{at}.", "id")

        if node_type == "question":
            # A question with no dataType has no value representation (§2.1),
            # so there is nothing for the runtime to store or validate.
            _require(node, "dataType", str, f"{at}.", "dataType")
        else:
            if "children" in node:
                _check_children(node["children"], f"{at}.children")
