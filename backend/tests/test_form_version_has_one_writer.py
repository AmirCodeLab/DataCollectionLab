"""`form_version` has exactly one writer, and this is what says so.

Form IR §2.3: the builder gets no route of its own into `form_version`. It
produces IR and hands it to the same endpoint an import uses — the same
compile, the same sensitivity check, the same version freeze.

`form_draft` is what made this worth enforcing rather than asserting. A table
holding unpublished IR sits next to the table holding published IR, and the
shortcut is obvious: copy the row, set a version number, done. The schema
removes half of that — a draft has no version, checksum or published state to
carry across — and this removes the other half, because nothing stops somebody
constructing the ORM model directly.

What it costs when it goes wrong is in the repository already: the export work
found that a second route to the same artifact is how two callers end up
disagreeing about which version a submission belongs to (breaks 40, 42, 61). A
version published without `check_publishable` has been through no sensitivity
gate and no reachability check, and it is indistinguishable afterwards from one
that has.
"""

from __future__ import annotations

import ast
import pathlib

APP = pathlib.Path(__file__).resolve().parents[1] / "app"

#: The one function allowed to construct a published version.
THE_WRITER = ("app/modules/forms/service.py", "publish_version")


def _walk(
    node: ast.AST, model: str, where: str, function: str, found: list[tuple[str, str, int]]
) -> None:
    """Carry the enclosing function down, so a violation names it.

    "Somewhere in service.py" is not a finding anyone can act on.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            _walk(child, model, where, child.name, found)
            continue
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == model
        ):
            found.append((where, function, child.lineno))
        _walk(child, model, where, function, found)


def _construction_sites(model: str) -> list[tuple[str, str, int]]:
    """(file, enclosing function, line) for every `Model(...)` call in the app."""
    found: list[tuple[str, str, int]] = []
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        _walk(tree, model, str(path.relative_to(APP.parent)), "<module>", found)
    return found


def test_form_version_is_constructed_in_exactly_one_place() -> None:
    sites = _construction_sites("FormVersion")
    # The model definition itself is a ClassDef, not a call, so it is not here.
    assert len(sites) == 1, (
        "FormVersion is constructed in more than one place:\n"
        + "\n".join(f"  {f}:{line} in {fn}()" for f, fn, line in sites)
        + "\n\nA second writer is a second definition of 'published' — one that "
        "has been through no sensitivity gate and no reachability check, and "
        "that the conformance vectors cannot see because a vector compares "
        "engines and this is a caller (Form IR §2.3)."
    )
    (file, function, _line) = sites[0]
    assert (file, function) == THE_WRITER, (
        f"FormVersion is constructed in {file}:{function}(), not "
        f"{THE_WRITER[0]}:{THE_WRITER[1]}(). If publishing genuinely moved, "
        "update THE_WRITER — but read Form IR §2.3 first, because the thing "
        "this protects is that there is only ever one."
    )


def test_a_draft_carries_nothing_a_version_needs() -> None:
    """The schema half: promotion is not a column write.

    Read off the models rather than the SQL, because the models are what a
    caller in a hurry has in front of them.
    """
    from app.modules.forms.models import FormDraft, FormVersion

    draft = set(FormDraft.__table__.columns.keys())
    version = set(FormVersion.__table__.columns.keys())

    # Nothing that means "published" exists on a draft to be set.
    for column in ("version", "ir_checksum", "published_at", "published_by"):
        assert column in version, f"{column} should be on FormVersion"
        assert column not in draft, (
            f"form_draft has a {column!r} column. It should not: a draft with a "
            "version number is a version somebody can insert, and the point of "
            "this table is that promoting one means calling publish_version."
        )
