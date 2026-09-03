"""One cell: how a value is written, how it is read back, and what that costs.

Every rule here is a pair. `render` turns a Form IR value into something a
spreadsheet holds; `parse` turns it back. `canonical_value` is the third
function and the one that makes the pair honest: it says what a value becomes
after a round trip through a file that has no types, so
`parse(render(v)) == canonical_value(v)` is an equality anybody can check
rather than a claim.

The normalisations are few and each one is a limitation of tabular data, not a
decision this module made lightly:

  - **An empty `select_multiple` reads back as unanswered.** They are the same
    thing to the engine already (§6.3: "an empty list is an unanswered
    question"), so the file loses nothing the runtime distinguished.
  - **An empty string reads back as unanswered.** A CSV has one empty cell and
    no way to mean two things with it.
  - **A structured value comes back with every component present**, null where
    the original omitted one. `{lat, lon}` and `{lat, lon, alt: null}` are one
    value in a table with an `alt` column.
  - **`decimal` comes back as a float** even where it was written as an int.

`ENCRYPTED` is not one of these. It is a value the *server* substitutes for one
it cannot read, and the manifest names every column it can appear in — which is
what tells a reader that an `ENCRYPTED` in a text column is the token and not
somebody's answer.
"""

from __future__ import annotations

import json
import math
from typing import Any, Final

#: What an unreadable value exports as. Never blank, never `NA`, never `NULL`:
#: every statistical tool treats those three as missing and will compute a mean
#: over the rows that happen to be readable, without saying so. A token is a
#: value no analysis can mistake for an absence.
ENCRYPTED: Final = "ENCRYPTED"

#: A rendered cell. `None` is an empty cell — unanswered, or not asked.
type Cell = str | int | float | None

#: dataType -> the component columns it decomposes into. A structured value
#: goes into one column per component rather than one column of packed text,
#: because a `lat lon alt acc` string is something every analyst has to split
#: before they can do anything, and splitting it is where the mistakes are.
COMPONENTS: Final[dict[str, tuple[str, ...]]] = {
    "geopoint": ("lat", "lon", "alt", "accuracy"),
    "image": ("filename", "id", "hash", "size"),
    "audio": ("filename", "id", "hash", "size"),
    "video": ("filename", "id", "hash", "size"),
    "file": ("filename", "id", "hash", "size"),
    "signature": ("filename", "id", "hash", "size"),
    "drawing": ("filename", "id", "hash", "size"),
}

#: dataTypes carrying a choice value, which also export a resolved label (§3.2).
CHOICE_TYPES: Final = frozenset({"select_one", "select_multiple"})

#: `select_multiple` codes are space-joined, the XLSForm convention every tool
#: that reads this kind of file already expects. Labels cannot be: they contain
#: spaces, so they are joined by a separator a label will not hold.
MULTIPLE_SEPARATOR: Final = " "
LABEL_SEPARATOR: Final = " | "

_NUMERIC_COMPONENTS: Final = frozenset({"lat", "lon", "alt", "accuracy", "size"})


def render(value: Any, data_type: str, component: str | None = None) -> Cell:
    """One Form IR value as one cell."""
    if value is None:
        return None
    if component is not None:
        return _component(value, component)
    if data_type in COMPONENTS:  # asked for the whole of a decomposed type
        return None
    if data_type == "boolean":
        return 1 if value else 0
    if data_type == "integer":
        return int(value)
    if data_type == "decimal":
        return _finite(float(value))
    if data_type == "select_multiple":
        if not isinstance(value, list) or not value:
            return None
        return MULTIPLE_SEPARATOR.join(str(item) for item in value)
    if data_type in ("geotrace", "geoshape"):
        if not value:
            return None
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    text = str(value)
    return text or None


def parse(cell: Cell, data_type: str, component: str | None = None) -> Any:
    """The inverse of `render`, up to the normalisations named in the docstring.

    `ENCRYPTED` reads back as `ENCRYPTED`. It is not an answer and this
    function does not pretend it is one — a caller comparing a round trip has
    to know which columns carry it, which is what the manifest is for.
    """
    if cell is None or cell == "":
        return None
    if cell == ENCRYPTED:
        return ENCRYPTED
    if component is not None:
        if component in _NUMERIC_COMPONENTS:
            number = float(cell)
            return int(number) if component == "size" else number
        return str(cell)
    if data_type == "boolean":
        return str(cell) not in ("0", "False", "false")
    if data_type == "integer":
        return int(float(cell))
    if data_type == "decimal":
        return float(cell)
    if data_type == "select_multiple":
        return [item for item in str(cell).split(MULTIPLE_SEPARATOR) if item] or None
    if data_type in ("geotrace", "geoshape"):
        parsed = json.loads(str(cell))
        return parsed or None
    return str(cell)


def canonical_value(value: Any, data_type: str) -> Any:
    """What `value` becomes once it has been through a table.

    This is the right-hand side of the round-trip invariant. Writing it out
    separately is the point: a round trip that compared against a value the
    exporter had quietly adjusted would prove nothing, and one that compared
    against the raw value would fail on limitations of the file format rather
    than on defects.
    """
    if value is None:
        return None
    if data_type in COMPONENTS:
        if not isinstance(value, dict):
            return None
        return {
            name: parse(_component(value, name), data_type, name)
            for name in COMPONENTS[data_type]
        }
    return parse(render(value, data_type), data_type)


def _component(value: Any, component: str) -> Cell:
    if not isinstance(value, dict):
        return None
    found = value.get(component)
    if found is None:
        return None
    if component == "size":
        return int(found)
    if component in _NUMERIC_COMPONENTS:
        return _finite(float(found))
    return str(found) or None


def _finite(number: float) -> Cell:
    """NaN and infinity have no spelling a CSV reader agrees on."""
    return None if math.isnan(number) or math.isinf(number) else number
