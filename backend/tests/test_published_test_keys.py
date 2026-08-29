"""The published development keypairs, and the refusal that contains them.

scripts/dev_project_key.py installs a fixed keypair whose private half is in
version control. That is fine — it is what makes a local encrypted round trip
reproducible — as long as it can never become a recipient for data that
matters. Two things have to hold for that:

1. the server recognises those exact public keys, so recognition cannot be
   defeated by editing a label;
2. it refuses them anywhere but a development environment, at both points where
   such a key becomes load-bearing — registering it, and handing it to a device.

The first is the one that rots silently: someone regenerates the fixtures, the
script's scalars change, and the server's list quietly stops matching anything.
So the list is derived here from the script itself rather than restated.
"""

from __future__ import annotations

import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from app.modules.crypto.published_test_keys import (
    PUBLISHED_TEST_PUBLIC_KEYS,
    claims_test_only,
    is_published_test_key,
    refusal_for_test_only_key,
)

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"


def _script_public_keys() -> set[str]:
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        from dev_project_key import TEST_ONLY_PRIVATE_KEYS
    finally:
        sys.path.remove(str(SCRIPTS_DIR))

    return {
        X25519PrivateKey.from_private_bytes(bytes.fromhex(scalar))
        .public_key()
        .public_bytes_raw()
        .hex()
        for scalar in TEST_ONLY_PRIVATE_KEYS.values()
    }


def test_the_server_knows_exactly_the_keys_the_script_installs() -> None:
    """Derived from the script's scalars, so the two cannot drift apart.

    If they do, the guard still passes every test that only checks its logic
    while silently recognising nothing — the worst possible failure for a
    check whose entire job is recognition.
    """
    assert _script_public_keys() == set(PUBLISHED_TEST_PUBLIC_KEYS)


def test_a_freshly_generated_key_is_not_mistaken_for_a_published_one() -> None:
    fresh = X25519PrivateKey.generate().public_key().public_bytes_raw()
    assert not is_published_test_key(fresh)
    assert all(is_published_test_key(bytes.fromhex(k)) for k in PUBLISHED_TEST_PUBLIC_KEYS)
    # Bytes or hex, upper or lower: the same 32 bytes are the same key.
    published = next(iter(PUBLISHED_TEST_PUBLIC_KEYS))
    assert is_published_test_key(published.upper())


def test_development_is_the_only_place_a_published_key_is_allowed() -> None:
    published = next(iter(PUBLISHED_TEST_PUBLIC_KEYS))

    assert refusal_for_test_only_key("development", published, "TEST ONLY — dev") is None
    for environment in ("production", "staging", "prod", ""):
        refusal = refusal_for_test_only_key(environment, published, "Programme lead")
        assert refusal is not None
        # The message has to name the environment and the file the key came
        # from: whoever hits this is one step from encrypting real data to a
        # key that is not a secret.
        assert environment in refusal or environment == ""
        assert "dev_project_key.py" in refusal


def test_a_key_announced_as_a_test_key_is_refused_too() -> None:
    """The label is weaker evidence than the bytes, and still worth acting on.

    A key generated elsewhere and labelled TEST ONLY is one whose holder has
    said out loud that nobody treats its private half as a secret.
    """
    fresh = X25519PrivateKey.generate().public_key().public_bytes_raw()
    assert (
        refusal_for_test_only_key("production", fresh, "TEST ONLY — staging rehearsal")
        is not None
    )
    assert refusal_for_test_only_key("production", fresh, "test only, i promise") is not None
    assert refusal_for_test_only_key("production", fresh, "Programme lead — Fatima") is None
    assert refusal_for_test_only_key("development", fresh, "TEST ONLY") is None

    assert claims_test_only("TEST ONLY — scripts/dev_project_key.py (primary)")
    assert not claims_test_only("Contest only judges hold this")
