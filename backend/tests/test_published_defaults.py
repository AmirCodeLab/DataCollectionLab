"""The published application password must not start a non-development server.

The mistake this guards has no symptom: a deployment left on the default
connects to its database perfectly, as the role every policy binds. Every test
that touches the database passes, because they all use the same password at
both ends. So the thing worth asserting is not that connections work — it is
that the process refuses to exist.

Mirrors `test_published_test_keys.py` one layer out, including the check that
the constant the guard recognises is the constant the application actually
falls back to. Two copies of that string is the whole failure mode.

Before item 1 this guarded a JWT signing key. Sessions are a cookie and a row
now and there is no key to sign with, so the guard moved to the secret that
remains; break 71 in `docs/known-breaks.md` is the same break against it.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import pytest

from app.core.config import Settings
from app.core.published_defaults import (
    DEVELOPMENT_ENVIRONMENT,
    PUBLISHED_APP_DB_PASSWORD,
    refusal_for_published_secret,
)

PUBLISHED_URL = f"postgresql+asyncpg://dcp_app:{PUBLISHED_APP_DB_PASSWORD}@db:5432/dcp"
A_REAL_URL = "postgresql+asyncpg://dcp_app:3f1c0c2f9b7d4e6a8c5f0b1d2e3a4b5c@db:5432/dcp"


def test_development_may_use_the_published_default() -> None:
    """The whole point of the default: clone, run, no configuration."""
    assert refusal_for_published_secret(DEVELOPMENT_ENVIRONMENT, PUBLISHED_URL) is None


@pytest.mark.parametrize("environment", ["production", "staging", "prod", ""])
def test_every_other_environment_refuses_the_published_default(environment: str) -> None:
    refusal = refusal_for_published_secret(environment, PUBLISHED_URL)
    assert refusal is not None
    # The refusal has to name the setting and the environment, or whoever reads
    # it in a container log cannot act on it.
    assert "DATABASE_URL" in refusal
    assert repr(environment) in refusal


@pytest.mark.parametrize("environment", ["production", "staging", DEVELOPMENT_ENVIRONMENT])
def test_a_real_password_is_accepted_anywhere(environment: str) -> None:
    assert refusal_for_published_secret(environment, A_REAL_URL) is None


def test_the_guard_recognises_the_value_settings_actually_defaults_to() -> None:
    """The mirror check.

    If `Settings.database_url` were ever given its own literal, this guard
    would go on recognising a string nothing uses and every deployment would
    pass it while running on a published password.
    """
    default = Settings(_env_file=None).database_url
    assert urlsplit(default).password == PUBLISHED_APP_DB_PASSWORD
    assert urlsplit(default).username == "dcp_app"


def test_the_refusal_says_how_to_generate_a_replacement() -> None:
    """A refusal that does not say what to do next gets worked around."""
    refusal = refusal_for_published_secret("production", PUBLISHED_URL)
    assert refusal is not None
    assert "ALTER ROLE dcp_app" in refusal and "token_urlsafe" in refusal
