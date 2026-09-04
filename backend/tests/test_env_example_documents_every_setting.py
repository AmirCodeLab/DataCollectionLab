"""Every setting in `Settings` appears in `.env.example`, and nothing else does.

This is a lint, written as a test because the failure it prevents is silent and
slow: somebody adds a field to `app/core/config.py`, ships it, and the only
record that the setting exists is the class itself — which is the exact
complaint finding 4 of `docs/public-readiness-audit.md` made about the whole
configuration surface. A documentation file with no check against the thing it
documents drifts, and a stale one is worse than none, because it reads as a
complete list.

That is not hypothetical here. `docs/public-readiness-audit.md` recorded
`.gitignore` as covering `.env` when it did not, and asserted an open security
blocker for an hour after it was fixed. Both were caught by a person looking,
which does not scale to fifteen environment variables.

It fails in both directions on purpose. A field with no line in the example is
an undocumented setting; a line in the example with no field is a setting that
was renamed or removed, which is worse — it tells a self-hoster to set
something the server will ignore.
"""

from __future__ import annotations

import pathlib
import re

from app.core.config import Settings

ENV_EXAMPLE = pathlib.Path(__file__).resolve().parents[1] / ".env.example"

# Lines are shipped commented out, so the file is a description of the defaults
# rather than an override of them: `#JWT_SECRET=change-me-in-production`.
DECLARATION = re.compile(r"^#?([A-Z][A-Z0-9_]*)=", re.MULTILINE)


def test_env_example_exists() -> None:
    assert ENV_EXAMPLE.is_file(), (
        f"{ENV_EXAMPLE} is missing. It is the only map of the configuration "
        "surface a self-hoster has; see audit finding 4."
    )


def test_env_example_lists_exactly_the_settings_fields() -> None:
    documented = set(DECLARATION.findall(ENV_EXAMPLE.read_text(encoding="utf-8")))
    declared = {name.upper() for name in Settings.model_fields}

    undocumented = declared - documented
    assert not undocumented, (
        f"settings with no line in .env.example: {sorted(undocumented)}. "
        "Add each one with its default and a comment saying what it does — a "
        "setting discoverable only by reading config.py is the finding this "
        "file closes."
    )

    stale = documented - declared
    assert not stale, (
        f".env.example documents settings that do not exist: {sorted(stale)}. "
        "They were renamed or removed; the file now tells a self-hoster to set "
        "something the server ignores."
    )
