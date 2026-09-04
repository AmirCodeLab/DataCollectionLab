"""The published signing key must not start a non-development server.

The mistake this guards has no symptom: a deployment left on the default signs
and verifies its own tokens perfectly. Every test that exercises auth passes,
because they all use the same secret at both ends. So the thing worth asserting
is not that tokens work — it is that the process refuses to exist.

Mirrors `test_published_test_keys.py` one layer out, including the check that
the constant the guard recognises is the constant the application actually
falls back to. Two copies of that string is the whole failure mode.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.published_defaults import (
    DEVELOPMENT_ENVIRONMENT,
    PUBLISHED_JWT_SECRET,
    refusal_for_published_secret,
)

A_REAL_SECRET = "3f1c0c2f9b7d4e6a8c5f0b1d2e3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a"


def test_development_may_use_the_published_default() -> None:
    """The whole point of the default: clone, run, no configuration."""
    assert refusal_for_published_secret(DEVELOPMENT_ENVIRONMENT, PUBLISHED_JWT_SECRET) is None


@pytest.mark.parametrize("environment", ["production", "staging", "prod", ""])
def test_every_other_environment_refuses_the_published_default(environment: str) -> None:
    refusal = refusal_for_published_secret(environment, PUBLISHED_JWT_SECRET)
    assert refusal is not None
    # The refusal has to name the setting and the environment, or whoever reads
    # it in a container log cannot act on it.
    assert "JWT_SECRET" in refusal
    assert repr(environment) in refusal


@pytest.mark.parametrize("environment", ["production", "staging", DEVELOPMENT_ENVIRONMENT])
def test_a_real_secret_is_accepted_anywhere(environment: str) -> None:
    assert refusal_for_published_secret(environment, A_REAL_SECRET) is None


def test_the_guard_recognises_the_value_settings_actually_defaults_to() -> None:
    """The mirror check.

    If `Settings.jwt_secret` were ever given its own literal, this guard would
    go on recognising a string nothing uses and every deployment would pass it
    while running on a published key.
    """
    assert Settings(_env_file=None).jwt_secret == PUBLISHED_JWT_SECRET


def test_the_refusal_says_how_to_generate_a_replacement() -> None:
    """A refusal that does not say what to do next gets worked around."""
    refusal = refusal_for_published_secret("production", PUBLISHED_JWT_SECRET)
    assert refusal is not None
    assert "secrets" in refusal and "token_urlsafe" in refusal
