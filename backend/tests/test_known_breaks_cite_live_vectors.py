"""Every vector a break row names must still exist.

**Written because seven vectors were silently deleted.** `repeat-009`…`012` and
`screens-009`…`011` were hand-written straight to JSON, never added to
`conformance/generate_vectors.py`, and that script used to clear the directory
before writing. One run removed all seven and **every suite stayed green**: the
runners glob the directory, so a vector that no longer exists is not a failure,
it is simply not run. The only thing that moved was a count nobody was reading.

The generator no longer deletes what it did not write. This is the other half —
the guard that notices a vector going missing however it goes.

It works because `docs/known-breaks.md` already names the vector that catches
each break, so the citations are a list somebody maintains for their own reasons
rather than a list kept up to date for this test's sake. A break row naming a
vector that is not there is a false claim about what is defended, which is the
one thing that file exists to avoid.

It does not claim to cover every vector: plenty are cited nowhere (see
`docs/known-breaks.md`'s own "What is not on this list"). It covers exactly the
ones somebody has written down as load-bearing.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
BREAKS = REPO / "docs" / "known-breaks.md"
VECTOR_SETS = {
    "vectors": REPO / "conformance" / "vectors",
    "functions": REPO / "conformance" / "functions",
    "malformed": REPO / "conformance" / "malformed",
    "sensitivity": REPO / "conformance" / "sensitivity",
    "crypto": REPO / "conformance" / "crypto",
}

#: `screens-011`, or `conformance/vectors/repeat-009.json` — an id as a file is named.
CITATION = re.compile(r"\b([a-z][a-z_]*-\d{3})\b")


def _code_spans(text: str) -> list[str]:
    """The contents of every markdown code span, and nothing else.

    Backticks are what make a name a citation rather than a mention. Break 41's
    row quotes a guard's error message naming the **hypothetical** vector
    choice-999, which never existed and is not a claim about anything on disk.
    Splitting on backticks and keeping the odd segments is what tells the two
    apart — a regex spanning from one span's closing backtick to the next span's
    opening one reads the prose between them as code, which is how that
    hypothetical got picked up on the first attempt.
    """
    return [span for line in text.splitlines() for span in line.split("`")[1::2]]


#: Ids that exist in more than one set, so a bare citation of them is ambiguous
#: and this guard is weaker for exactly those. `media-001` is a media round-trip
#: in `vectors` and per-chunk media encryption in `crypto` — two different
#: claims wearing one name. Deleting either leaves the other on disk and this
#: test green, which is the honest limit of reading citations that carry no set.
#:
#: Listed rather than tolerated silently: a new collision fails the test below,
#: so the next one is a decision somebody makes rather than a hole that opens.
KNOWN_COLLISIONS = {"media-001"}


def _by_set() -> dict[str, set[str]]:
    return {
        name: {p.stem for p in directory.glob("*.json")}
        for name, directory in VECTOR_SETS.items()
        if directory.is_dir()
    }


def _on_disk() -> set[str]:
    found: set[str] = set()
    for ids in _by_set().values():
        found.update(ids)
    return found


def test_no_new_vector_id_is_ambiguous_across_sets() -> None:
    """A citation names an id and not a set, so a shared id weakens the guard.

    This is not a rule against collisions — `media-001` is one and is fine. It
    is a rule that a collision has to be noticed, because each one is an id the
    test above cannot really check.
    """
    by_set = _by_set()
    seen: dict[str, list[str]] = {}
    for name, ids in by_set.items():
        for vector_id in ids:
            seen.setdefault(vector_id, []).append(name)

    collisions = {k: sorted(v) for k, v in seen.items() if len(v) > 1}
    unexpected = {k: v for k, v in collisions.items() if k not in KNOWN_COLLISIONS}
    assert not unexpected, (
        f"vector id(s) in more than one set: {unexpected}. A break row citing one "
        "of these names both, so deleting either leaves this file's guard green. "
        "Rename one, or add it to KNOWN_COLLISIONS having decided that is fine."
    )
    # And the other way: a listed collision that stopped colliding is a stale
    # allowance, which would quietly re-strengthen nothing and mislead the next
    # reader.
    stale = KNOWN_COLLISIONS - set(collisions)
    assert not stale, f"KNOWN_COLLISIONS names ids that no longer collide: {sorted(stale)}"


def test_every_vector_named_in_known_breaks_still_exists() -> None:
    text = BREAKS.read_text()
    on_disk = _on_disk()
    assert on_disk, "no vectors found at all — the paths in this test are wrong"

    cited = {name for span in _code_spans(text) for name in CITATION.findall(span)}
    # Only ids that look like a vector set we know; the file also names things
    # like "break 74" and dates, which this pattern does not match anyway.
    cited = {name for name in cited if name.split("-")[0] in {
        "repeat", "screens", "calculate", "cast", "choice", "constraint",
        "dataset", "date", "determinism", "geopoint", "label", "media", "null",
        "relevance", "trig", "malformed", "sensitivity", "crypto", "fn",
    }}
    assert cited, "known-breaks.md cites no vectors at all — has the format changed?"

    missing = sorted(cited - on_disk)
    assert not missing, (
        f"{len(missing)} vector(s) named in docs/known-breaks.md are not on disk: "
        f"{missing}. Either the break row is stale, or a vector was deleted — the "
        "second is what this test exists for, and it has happened: "
        "conformance/generate_vectors.py used to clear the directory before "
        "writing and took every hand-written vector with it."
    )
