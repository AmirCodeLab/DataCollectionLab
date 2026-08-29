"""Keys whose private halves are published, and what to do about them.

`scripts/dev_project_key.py` installs a fixed keypair so a developer can drive
the encrypted path end to end without the console. Its private scalars are in
version control, which is exactly what makes a local round trip reproducible —
and exactly what makes the same key catastrophic anywhere else. Anything
wrapped to it is readable by anyone with a copy of this repository.

The script already refuses to run outside a development environment. That is
not enough on its own: a database seeded in development and then promoted, a
dump restored onto a staging box, or someone pasting the public key from a
commit into the console all arrive at the same place — a project whose
submissions are wrapped to a key the whole world holds, displayed in the
console as a recipient like any other.

So the refusal lives here, on the server, at both points where such a key could
become load-bearing: registering it as a recipient, and handing it to a device
to wrap to. Recognition is by public key, not by label — a label is prose and
can be edited; the 32 bytes are the thing that decides who can decrypt.
"""

from __future__ import annotations

import re

# Public halves of the fixed keypairs in scripts/dev_project_key.py. The private
# scalars stay in that script — the server has no use for one, and holding a
# private key beside the data it opens is the arrangement this whole spec
# exists to avoid. tests/test_published_test_keys.py derives these from the
# script's scalars and fails if the two ever drift apart.
PUBLISHED_TEST_PUBLIC_KEYS: frozenset[str] = frozenset(
    {
        # primary
        "40fd23ed9bf913bdaf563c3ad2fbe16f0a19103744fd2a90ecef2a5c51c90358",
        # backup
        "ba0962cda30119a751bd658556a1992519bee464a21cac30d4b29393b4997043",
        # recovery
        "d29c2a61edde8a6f47eba09a3bc688ad85ff2791e238d132709239dcbf6d1f07",
    }
)

# Every key the script writes is labelled with this. Checked in addition to the
# key bytes, so a key generated elsewhere and announced as a test key is refused
# too — someone who writes "TEST ONLY" on a recipient has told us what it is.
TEST_ONLY_LABEL_MARKER = "TEST ONLY"

DEVELOPMENT_ENVIRONMENT = "development"


def is_published_test_key(public_key: bytes | str) -> bool:
    """Whether these are 32 bytes whose private half is in the repository."""
    hexed = public_key.hex() if isinstance(public_key, bytes) else public_key.strip().lower()
    return hexed in PUBLISHED_TEST_PUBLIC_KEYS


# On word boundaries: "CONTEST ONLY judges hold this" contains the marker as a
# substring and says nothing about the key. A refusal that fires on a legitimate
# label teaches people to work around the refusal.
_TEST_ONLY_PATTERN = re.compile(r"\bTEST[\s_-]?ONLY\b")


def claims_test_only(label: str) -> bool:
    return _TEST_ONLY_PATTERN.search(label.upper()) is not None


def refusal_for_test_only_key(
    environment: str, public_key: bytes | str, label: str
) -> str | None:
    """Why this key must not be used here, or None when it may be.

    Returns prose meant to be shown verbatim: whoever hits this is one step from
    encrypting real data to a key that is not a secret, and needs to be told
    which of the two things they did was the problem.
    """
    if environment == DEVELOPMENT_ENVIRONMENT:
        return None
    if is_published_test_key(public_key):
        return (
            "That public key is one of the fixed TEST ONLY keypairs in "
            "scripts/dev_project_key.py. Its private half is published in this "
            f"repository, so every submission wrapped to it would be readable by "
            f"anyone holding a copy. Refused because the environment is "
            f"{environment!r}, not {DEVELOPMENT_ENVIRONMENT!r}. Generate a real "
            "keypair in the console instead."
        )
    if claims_test_only(label):
        return (
            f"That key is labelled {TEST_ONLY_LABEL_MARKER!r} and the environment "
            f"is {environment!r}, not {DEVELOPMENT_ENVIRONMENT!r}. A key whose "
            "holder has announced it as a test key must not become a recipient "
            "for real data — nobody will treat its private half as a secret."
        )
    return None
