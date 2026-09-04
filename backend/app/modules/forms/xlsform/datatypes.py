"""Which Form IR dataTypes exist, and which a phone can actually collect.

These are two different questions and the XLSForm report has to keep them
apart. A dataType can be in the spec, carry a conformance vector, and be
evaluated identically by both engines — and still reach a device as a question
nobody can answer, because the collection screen has no widget for it. That was
defect 7, and `select_multiple` was in it.

So an author gets told which of three sets their question falls in:

  IN_SPEC      the IR defines a representation (form-ir-v0.1.md §2.1)
  COLLECTABLE  a client can present it (specs/collectable-types-v0.1.json)
  neither      not in the IR at all — `rank`, `range`

Only the second answers "will my question work in the field". A type in the
first but not the second is the dangerous one: it imports, publishes, deploys,
and arrives unanswerable.

**Both sets are read from files, never written down here.** A hand-copied list
is the SUBMISSION_STATUSES problem, which this repository has already paid for
once — a mirrored constant went stale and needed a test of its own to catch.
`test_collectable_types.py` holds this module to the files; `CollectableTypesTest`
holds the Android client to the same registry, in both directions.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
from functools import lru_cache

# Where the normative files are, in the order worth trying.
#
# `/specs` is the read-only mount docker-compose gives the container, matching
# what it already does for `/conformance`. The repo-root walk is what serves a
# developer running uvicorn directly and the test suite. The environment
# variable is the escape hatch for a deployment that puts them somewhere else.
_ENV_VAR = "DCP_SPECS_DIR"
_CONTAINER_DIR = pathlib.Path("/specs")

COLLECTABLE_TYPES_FILE = "collectable-types-v0.1.json"
FORM_IR_SPEC_FILE = "form-ir-v0.1.md"


class SpecsUnavailable(RuntimeError):
    """The normative files are not where this process can read them.

    Raised rather than defaulted, and that is the whole point of the class
    existing. Every fallback available here is a lie an author would act on: an
    empty collectable set reports every question as unanswerable and sends
    somebody redesigning a form that was fine, and a full one reports the
    opposite and puts an unanswerable question in the field. Refusing to import
    is the only honest option when the thing that decides is missing.
    """


def specs_dir() -> pathlib.Path:
    """The directory holding the normative spec files."""
    override = os.environ.get(_ENV_VAR)
    if override:
        candidate = pathlib.Path(override)
        if (candidate / COLLECTABLE_TYPES_FILE).is_file():
            return candidate
        raise SpecsUnavailable(
            f"{_ENV_VAR} is set to {override}, which has no {COLLECTABLE_TYPES_FILE}"
        )

    if (_CONTAINER_DIR / COLLECTABLE_TYPES_FILE).is_file():
        return _CONTAINER_DIR

    for parent in pathlib.Path(__file__).resolve().parents:
        candidate = parent / "specs"
        if (candidate / COLLECTABLE_TYPES_FILE).is_file():
            return candidate

    raise SpecsUnavailable(
        f"cannot find specs/{COLLECTABLE_TYPES_FILE}. In Docker it is the "
        f"./specs:/specs:ro mount; elsewhere set {_ENV_VAR}. The importer will "
        "not guess which question types a device can collect."
    )


@lru_cache(maxsize=1)
def collectable_types() -> frozenset[str]:
    """dataTypes a collection client can present, per the committed registry."""
    document = json.loads((specs_dir() / COLLECTABLE_TYPES_FILE).read_text())
    listed = document.get("collectable")
    if not listed:
        raise SpecsUnavailable(f"{COLLECTABLE_TYPES_FILE} lists no collectable types")
    return frozenset(listed)


@lru_cache(maxsize=1)
def collectable_choice_sources() -> frozenset[str]:
    """`choices.kind` values a collection client can actually present (§3).

    The second axis, and it needs to be asked separately from the first for the
    reason the registry spells out: `select_one` is a collectable dataType and a
    *dataset-backed* `select_one` is not a collectable question, because the
    collection screen reads `choices.items` and a dataset-backed list has none.
    A form using one would import, publish, deploy, and arrive as a label with
    empty space under it — defect 7 exactly, one axis over.
    """
    document = json.loads((specs_dir() / COLLECTABLE_TYPES_FILE).read_text())
    listed = document.get("choiceSources")
    if not listed:
        raise SpecsUnavailable(f"{COLLECTABLE_TYPES_FILE} lists no collectable choice sources")
    return frozenset(listed)


@lru_cache(maxsize=1)
def collectable_types_version() -> str:
    """The registry's version — a fact about an app version, not a permanent one."""
    return str(json.loads((specs_dir() / COLLECTABLE_TYPES_FILE).read_text())["version"])


@lru_cache(maxsize=1)
def spec_data_types() -> frozenset[str]:
    """Every dataType in the Form IR spec's §2.1 table, parsed from the spec.

    Parsed rather than transcribed for the same reason as everything else here:
    the spec is normative (docs/project-conventions.md rule 1), so it is the thing to read. A
    transcription would be a second copy of a list that changes.
    """
    text = (specs_dir() / FORM_IR_SPEC_FILE).read_text()
    try:
        table = text.split("**Data types**", 1)[1].split("### 2.2", 1)[0]
    except IndexError as exc:  # pragma: no cover - a spec without §2.1 is broken
        raise SpecsUnavailable(
            f"{FORM_IR_SPEC_FILE} has no '**Data types**' table to read §2.1 from"
        ) from exc

    found: set[str] = set()
    for line in table.splitlines():
        if not line.startswith("| `"):
            continue
        # The first column can hold several types on one row: `image` / `audio`.
        first_column = line.split("|")[1]
        found.update(re.findall(r"`([a-z_]+)`", first_column))
    if not found:
        raise SpecsUnavailable(f"parsed no dataTypes out of {FORM_IR_SPEC_FILE} §2.1")
    return frozenset(found)


def classify_choice_source(kind: str) -> str:
    """`collectable` or `in_spec_only` for a `choices.kind` (§3).

    There is no `unknown` third case here the way there is for dataTypes: §3
    defines exactly two kinds, and anything else never reaches this — the
    importer only ever produces one of the two.
    """
    return "collectable" if kind in collectable_choice_sources() else "in_spec_only"


def classify(data_type: str) -> str:
    """One of `collectable`, `in_spec_only`, `unknown`.

    `in_spec_only` is the answer that needs saying out loud in a report: the
    document is valid, both engines will evaluate it, and an enumerator still
    cannot answer the question.
    """
    if data_type in collectable_types():
        return "collectable"
    if data_type in spec_data_types():
        return "in_spec_only"
    return "unknown"
