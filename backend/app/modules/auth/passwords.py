"""Password hashing: argon2id, and nothing configurable about it.

One function to store, one to check. `verify` takes the stored hash first so a
caller cannot swap the arguments and have every login succeed against a hash
of the hash — the shape `hmac.compare_digest` avoids for the same reason.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    """False for a wrong password, a person with no credentials yet
    (`invited`, hash NULL), or a hash this code cannot read."""
    if not stored_hash:
        return False
    try:
        return _hasher.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
