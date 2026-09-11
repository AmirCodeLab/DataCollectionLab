"""The builtin roles are defined once, and this is what says so.

Gate 1, A7. `app/modules/auth/builtin_roles.sql` is the only place the four
roles and their permissions are written for anything standing up an
organisation today. This test fails if a second writer appears.

**Why it is a test and not a convention.** The grants lived in four places —
`008_identity.sql`, `010_people.sql`, `016_review.sql` and `scripts/seed_dev.py`
— and were kept in step by hand, four times, correctly every time. Measured on
11 September before the refactor, the four copies agreed exactly. So this is
not a reconciliation and no list was wrong; what was missing was a mechanism.

What it costs when it goes wrong is a permission set that four people maintain
by remembering, and the failure is silent. A customer's Supervisor without
`submission.review` has a console where every screen works and the review
controls are simply absent, and it is found by a supervisor who cannot do their
job — not by a test, not by a reviewer, and not on the day it was introduced.

**The migrations are exempt, and that is the point of the exemption.** They are
an append-only record of what happened to databases that already exist.
008 really did write those grants; pretending otherwise to satisfy a lint would
be a lie about what ran. They are history. This file is what runs now.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: The one definition.
THE_DEFINITION = ROOT / "backend/app/modules/auth/builtin_roles.sql"

#: Where a second writer would appear. `backend/migrations/` is deliberately
#: absent — see the docstring.
SEARCHED = (
    ROOT / "backend/app",
    ROOT / "scripts",
    ROOT / "web/src",
    ROOT / "clients",
    ROOT / "shared",
)

#: An INSERT, UPDATE or DELETE naming either table. `SELECT` is not a writer:
#: reading a person's grants is what half the policies do.
WRITES = re.compile(
    r"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(role_permission|role)\b",
    re.IGNORECASE,
)

#: Files that legitimately write them for a reason other than defining the
#: builtin set. A custom role is a product feature, not a copy of the builtins.
ALLOWED = {
    # Item 1's people screens: an administrator edits a *custom* role's
    # permissions through the API. It never creates a builtin one, and
    # `010_people.sql` refuses a write to a builtin row whatever this says.
    "backend/app/modules/people/service.py",
}


def _sources() -> list[pathlib.Path]:
    found: list[pathlib.Path] = []
    for root in SEARCHED:
        if not root.exists():
            continue
        for suffix in ("*.py", "*.sql", "*.kt", "*.ts", "*.tsx"):
            found.extend(
                path
                for path in root.rglob(suffix)
                if "/build/" not in str(path) and "/node_modules/" not in str(path)
            )
    return sorted(found)


def test_nothing_else_writes_the_role_tables() -> None:
    offenders: list[str] = []
    for path in _sources():
        relative = str(path.relative_to(ROOT))
        if path == THE_DEFINITION or relative in ALLOWED:
            continue
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if line.lstrip().startswith(("--", "#", "//", "*")):
                continue
            if WRITES.search(line):
                offenders.append(f"{relative}:{number}: {line.strip()}")

    assert not offenders, (
        "The builtin roles have one definition, "
        f"{THE_DEFINITION.relative_to(ROOT)}, and something else writes the "
        "role tables:\n  "
        + "\n  ".join(offenders)
        + "\n\nIf this is a second copy of the builtin set, delete it and call "
        "`app.modules.auth.builtin_roles.install`. If it is a custom role — a "
        "product feature, not a copy of the builtins — add the file to "
        "ALLOWED with the reason, the way people/service.py is."
    )


def test_the_definition_is_where_this_test_thinks_it_is() -> None:
    """A lint pointed at a file that has moved passes and guards nothing."""
    assert THE_DEFINITION.is_file(), f"{THE_DEFINITION} is gone"
    assert WRITES.search(THE_DEFINITION.read_text()), (
        "the definition no longer writes the role tables, so either it has "
        "been gutted or this test is now watching the wrong file"
    )
