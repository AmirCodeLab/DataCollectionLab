"""The Python half of the collectable-types mirror.

`specs/collectable-types-v0.1.json` is one language-neutral file with an
implementation on each side of it, like the conformance vectors: the Android
client presents these types, and the XLSForm importer tells an author whether
their question will work in the field. Two hand-maintained copies drift — this
repository has already paid for that once, when `SUBMISSION_STATUSES` was
mirrored by hand and needed a test of its own to catch the copy going stale.

The Kotlin half is `CollectableTypesTest` (`:clients:composeApp:jvmTest`),
which drives the real composable in both directions. This half checks the
things only the server can check:

  - the registry names real dataTypes, parsed out of the normative spec
  - the importer *derives* its sets from the files rather than repeating them
  - a missing registry refuses rather than defaults, in either direction

That last one is the interesting case. Both defaults are a lie an author would
act on, and they are lies in opposite directions.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from app.modules.forms.xlsform import datatypes

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
REGISTRY = REPO_ROOT / "specs" / datatypes.COLLECTABLE_TYPES_FILE
SPEC = REPO_ROOT / "specs" / datatypes.FORM_IR_SPEC_FILE


@pytest.fixture(autouse=True)
def _clear_caches():
    """The module memoises; every test here changes what it should read."""
    datatypes.collectable_types.cache_clear()
    datatypes.spec_data_types.cache_clear()
    datatypes.collectable_types_version.cache_clear()
    yield
    datatypes.collectable_types.cache_clear()
    datatypes.spec_data_types.cache_clear()
    datatypes.collectable_types_version.cache_clear()


def test_the_registry_and_the_spec_are_both_readable() -> None:
    # If this fails the rest prove nothing, so it is asserted first and alone.
    assert REGISTRY.is_file(), f"{REGISTRY} is missing"
    assert SPEC.is_file(), f"{SPEC} is missing"
    assert datatypes.spec_data_types(), "parsed no dataTypes out of the spec's §2.1 table"
    assert datatypes.collectable_types(), "the registry lists no collectable types"


def test_every_collectable_type_is_a_real_data_type() -> None:
    """A typo in the registry would promise a type that cannot exist."""
    unknown = datatypes.collectable_types() - datatypes.spec_data_types()
    assert not unknown, (
        f"the registry lists {sorted(unknown)}, which are not dataTypes in Form IR §2.1"
    )


def test_the_registry_is_a_strict_subset_so_the_distinction_is_real() -> None:
    """`in the IR` and `collectable` must not be the same set.

    If they ever became equal this whole module would be answering a question
    nobody needs asked, and `classify` could never return `in_spec_only` — the
    answer that exists to warn an author their question is unanswerable.
    """
    in_spec_only = datatypes.spec_data_types() - datatypes.collectable_types()
    assert in_spec_only, (
        "every spec dataType is collectable, so the report's most important "
        "distinction has nothing to say. Either a widget landed without the "
        "registry being updated, or this test needs deleting."
    )


def test_classify_answers_the_three_cases() -> None:
    assert datatypes.classify("text") == "collectable"
    assert datatypes.classify("select_multiple") == "collectable"
    # In §2.1 as a media reference; no capture built on any platform.
    assert datatypes.classify("audio") == "in_spec_only"
    # Not in the IR at all. XLSForm has both; the IR has neither.
    assert datatypes.classify("rank") == "unknown"
    assert datatypes.classify("range") == "unknown"


def test_the_importer_repeats_neither_list_in_python() -> None:
    """The sets are read from files, not written down here.

    A literal in this module would be a third copy of a list that already has
    two homes, and the one nobody would think to update.
    """
    source = pathlib.Path(datatypes.__file__).read_text()
    for data_type in ("select_multiple", "geopoint", "signature", "decimal"):
        assert f'"{data_type}"' not in source, (
            f"{data_type!r} is written into datatypes.py. The registry is the "
            "only place it belongs — see the SUBMISSION_STATUSES note above."
        )


def test_a_missing_registry_refuses_rather_than_defaulting(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Neither default is safe, so there is no default.

    Empty reports every question as unanswerable and sends an author
    redesigning a form that was fine. Full reports the opposite and puts an
    unanswerable question in front of an enumerator. The only honest answer
    when the deciding file is absent is to refuse the import.
    """
    monkeypatch.setenv("DCP_SPECS_DIR", str(tmp_path))
    with pytest.raises(datatypes.SpecsUnavailable) as refusal:
        datatypes.specs_dir()
    assert datatypes.COLLECTABLE_TYPES_FILE in str(refusal.value)


def test_an_empty_registry_refuses_too(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A file that parses and says nothing is the same failure with better
    # paperwork: it would classify every type as in_spec_only.
    (tmp_path / datatypes.COLLECTABLE_TYPES_FILE).write_text(
        json.dumps({"version": "0.1", "collectable": []})
    )
    monkeypatch.setenv("DCP_SPECS_DIR", str(tmp_path))
    with pytest.raises(datatypes.SpecsUnavailable):
        datatypes.collectable_types()


def test_the_registry_is_versioned() -> None:
    """It is a fact about an app version, not a permanent one.

    When `barcode` ships it belongs in v0.2, and a phone on the older build
    cannot collect it — which is what the collection screen's `else` branch
    exists to make visible.
    """
    version = json.loads(REGISTRY.read_text())["version"]
    assert version, "the registry has no version"
    assert datatypes.collectable_types_version() == str(version)
    assert datatypes.COLLECTABLE_TYPES_FILE.endswith(f"v{version}.json"), (
        f"the filename and the version disagree: {datatypes.COLLECTABLE_TYPES_FILE} vs {version}"
    )


def test_the_kotlin_half_of_this_mirror_still_exists() -> None:
    """Each half asserts the other is there.

    The suites guard answers "is this suite run by CI", and both halves live in
    suites it already tracks — so deleting a CI step is caught. Deleting the
    *test file* is not: the suite simply reports one fewer file and stays green,
    which is exactly the quiet way a mirror test stops running.

    So the two halves point at each other. Remove either and the other fails,
    naming what went missing. `CollectableTypesTest` has the matching check
    pointing back at this file.
    """
    kotlin = (
        REPO_ROOT
        / "clients/composeApp/src/jvmTest/kotlin/com/amr/data_collection_lab"
        / "collection/CollectableTypesTest.kt"
    )
    assert kotlin.is_file(), (
        f"{kotlin.relative_to(REPO_ROOT)} is gone. It is the half of this mirror that "
        "checks the collection screen actually implements what the registry promises; "
        "without it the registry is a claim nothing tests."
    )
    source = kotlin.read_text()
    assert datatypes.COLLECTABLE_TYPES_FILE in source, (
        f"{kotlin.name} no longer reads {datatypes.COLLECTABLE_TYPES_FILE}, so it is "
        "not mirroring this registry any more."
    )
