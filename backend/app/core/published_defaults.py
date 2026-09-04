"""Configuration defaults that are published, and what to do about them.

`Settings` ships working defaults so a developer can clone this repository and
run the stack with no configuration at all. That is deliberate and worth
keeping. One of them is not like the others: `jwt_secret` defaults to a fixed
string in version control, and a token signed with it can be forged by anyone
holding a copy of this repository.

It is the same hazard as `crypto/published_test_keys.py`, one layer out. There
the secret is a private key and the refusal fires when it would become a
recipient; here the secret is a signing key and the refusal fires at startup,
because that is the only moment before it is load-bearing.

The failure has no symptom, which is why a guard rather than a note in the
README. A deployment left on the default signs and verifies its own tokens
perfectly: every login works, every request authenticates, nothing is logged and
nothing looks wrong. It is indistinguishable from a correct deployment right up
until somebody else mints a token.

So the default is refused outside development, and the constant lives here
rather than in `Settings` so that the value the guard recognises and the value
the application actually falls back to cannot drift apart — the mirror problem
this repository already has one lint for.
"""

from __future__ import annotations

#: The published fallback. `Settings.jwt_secret` uses this as its default, so
#: there is one definition rather than a copy in each place that needs it.
PUBLISHED_JWT_SECRET = "change-me-in-production"

DEVELOPMENT_ENVIRONMENT = "development"


def refusal_for_published_secret(environment: str, jwt_secret: str) -> str | None:
    """Why this process must not start, or None when it may.

    Returns prose meant to be shown verbatim. Whoever hits this is one restart
    away from signing production sessions with a value printed in a public
    repository, and needs to be told exactly which setting to change.
    """
    if environment == DEVELOPMENT_ENVIRONMENT:
        return None
    if jwt_secret != PUBLISHED_JWT_SECRET:
        return None
    return (
        f"JWT_SECRET is still {PUBLISHED_JWT_SECRET!r}, the default published in "
        f"this repository, and the environment is {environment!r}, not "
        f"{DEVELOPMENT_ENVIRONMENT!r}. Anyone with a copy of this source could "
        "forge a session token for any user. Set JWT_SECRET to a long random "
        "value — `python -c \"import secrets; print(secrets.token_urlsafe(64))\"` "
        "— and restart. Refusing to start."
    )
