"""Whether every question in a form can actually be put in front of somebody.

This is the publish-time half of what `specs/collectable-types-v0.1.json`
exists for, and it is here because for the life of the registry there was only
the import-time half. The XLSForm importer refused a `time` question by name —
"a valid Form IR type, but no client can present it yet" — and
`POST /forms/versions` accepted the identical document, published it and
deployed it. `docs/known-defects.md` 28; found on the Sindh-scale run, where a
2,128-question form went to two environments carrying two `time` questions and
a `geoshape`.

**It is the same shape as the reachability gap, one axis over**, and it gets the
same fix: `check_reachability` used to live only in the importer as
`questions_cannot_be_asked`, so a form built in the console — which never runs
the importer — reached the gate with nothing to check it (item 0 step 2). A
guard that only one route in consults is not a guard on the platform, it is a
guard on that route.

## Why this is not in `form_engine`, and not a §10 rule

Form IR §10 is a statement about a *document*: these errors are true of it
wherever it is read, which is why both engines implement them and why
`conformance/reachability` can compare the two. Collectability is a statement
about an **app version** — `barcode` is refused today and will not be in v0.2 —
and the registry is versioned for exactly that reason. Putting it in the engine
would make one implementation's build date part of the spec.

So it sits beside the publish gate rather than inside it, it has **no Kotlin
twin and needs none** (the Kotlin engine has no publish gate; what holds the
Android client to the registry is `CollectableTypesTest`), and no conformance
vector can express it. What watches it is `test_collectability_gate.py`.

## The version this refuses against, and the case it does not cover

The refusal is against **this deployment's** registry, and the message says
which version. That is right for a deployment whose server and clients ship
together, which is every deployment today. It is not right for a self-hosted
install running an older APK than its server: the form would publish here and
still arrive unanswerable there. Nothing can close that from this side — a
device would have to report its build's registry version at registration, which
sync §4 is the place for and which the registry file's own comment already
names as the shape left open. Stated rather than silently assumed.
"""

from __future__ import annotations

from typing import Any

from app.modules.forms.xlsform import datatypes


def _questions(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every question node in document order, containers walked through.

    A `calculate` is included here and filtered by the caller, not dropped
    silently, so the reason for excluding it is written where it is applied.
    """
    found: list[dict[str, Any]] = []
    for node in nodes:
        if node.get("type") == "question":
            found.append(node)
        children = node.get("children")
        if children:
            found.extend(_questions(children))
    return found


def uncollectable_type_message(node_id: str, data_type: str, version: str) -> str:
    """The one sentence both the importer and the publish gate say.

    One definition because two were how the platform ended up refusing a
    document on one route and publishing it on another: the messages agreeing
    is the visible half of the gates agreeing.
    """
    return (
        f"`{node_id}` is a `{data_type}` question. That is a valid Form IR type, "
        "but no client can present it yet, so an enumerator would see a question "
        f"they cannot answer (collectable types v{version})."
    )


def uncollectable_choices_message(node_id: str, kind: str, version: str) -> str:
    return (
        f"`{node_id}` chooses from a {kind} list (Form IR §3), which nothing "
        "resolves yet — not the form engines and not a device — so the question "
        "would reach an enumerator with no options under it at all "
        f"(collectable types v{version})."
    )


def check_collectability(ir: dict[str, Any]) -> list[str]:
    """Violations that block publish, in document order. Empty when none.

    Two axes, because a type and where its options come from are different
    questions and the registry answers them separately: `select_one` is a
    collectable dataType and a dataset-backed `select_one` was not a collectable
    *question* until something resolved the list. Conflating them is what defect
    7 was.
    """
    version = datatypes.collectable_types_version()
    violations: list[str] = []

    for node in _questions(ir.get("children", [])):
        # A `calculate` is computed and never drawn (§11.1) — `build_screen_plan`
        # gives it no screen and `reachability._answerable` does not count it.
        # Its dataType is never presented to anybody, so refusing a form over one
        # would be refusing it for a question nobody was ever going to see.
        if node.get("calculate") is not None:
            continue

        data_type = node.get("dataType")
        if isinstance(data_type, str) and datatypes.classify(data_type) == "in_spec_only":
            violations.append(uncollectable_type_message(node["id"], data_type, version))

        choices = node.get("choices")
        if isinstance(choices, dict):
            kind = choices.get("kind")
            if isinstance(kind, str) and datatypes.classify_choice_source(kind) != "collectable":
                violations.append(uncollectable_choices_message(node["id"], kind, version))

    return violations
