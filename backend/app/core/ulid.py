"""Server-side ULID generation.

Client-created rows carry client-generated ULIDs (ERD §2); this is for rows
the SERVER creates — tombstones, outbox events. Crockford base32, 48-bit
millisecond timestamp + 80 random bits, lexically sortable by creation time.
"""

import os
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_ulid() -> str:
    value = (int(time.time() * 1000) << 80) | int.from_bytes(os.urandom(10), "big")
    return "".join(_ALPHABET[(value >> shift) & 31] for shift in range(125, -1, -5))
