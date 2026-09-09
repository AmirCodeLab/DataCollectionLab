"""Configuration defaults that are published, and what to do about them.

`Settings` ships working defaults so a developer can clone this repository and
run the stack with no configuration at all. That is deliberate and worth
keeping. One of them is not like the others: `DATABASE_URL` defaults to the
application role with a password printed in this repository
(`scripts/db_app_role.sql`), and a deployment that keeps it has a database
anyone holding a copy of the source can open — as `dcp_app`, the role every
policy binds, which is to say as any tenant at once.

It is the same hazard as `crypto/published_test_keys.py`, one layer out. There
the secret is a private key and the refusal fires when it would become a
recipient; here the secret is a login and the refusal fires at startup, because
that is the only moment before it is load-bearing.

The failure has no symptom, which is why a guard rather than a note in the
README. A deployment left on the default connects perfectly: every request
works, nothing is logged and nothing looks wrong. It is indistinguishable from
a correct deployment right up until somebody else connects.

So the default is refused outside development, and the constant lives here
rather than in `Settings` so that the value the guard recognises and the value
the application actually falls back to cannot drift apart — the mirror problem
this repository already has one lint for.

Before sessions were a cookie and a row (item 1), the published default this
guarded was a JWT signing key. Sessions are opaque tokens now — there is no
signing key to leak — and the guard moved to the secret that remains.
"""

from __future__ import annotations

from urllib.parse import urlsplit

#: The published application password. `Settings.database_url` carries it, so
#: there is one definition rather than a copy in each place that needs it.
PUBLISHED_APP_DB_PASSWORD = "dcp_app"

DEVELOPMENT_ENVIRONMENT = "development"


def refusal_for_published_secret(environment: str, database_url: str) -> str | None:
    """Why this process must not start, or None when it may.

    Returns prose meant to be shown verbatim. Whoever hits this is one restart
    away from serving production on a database password printed in a public
    repository, and needs to be told exactly which setting to change.
    """
    if environment == DEVELOPMENT_ENVIRONMENT:
        return None
    if urlsplit(database_url).password != PUBLISHED_APP_DB_PASSWORD:
        return None
    return (
        f"DATABASE_URL still carries the password {PUBLISHED_APP_DB_PASSWORD!r}, the "
        f"default published in this repository, and the environment is {environment!r}, "
        f"not {DEVELOPMENT_ENVIRONMENT!r}. Anyone with a copy of this source could open "
        "the database as the application role — as every tenant at once. Give dcp_app a "
        "real password (ALTER ROLE dcp_app PASSWORD '...', from e.g. "
        "python -c \"import secrets; print(secrets.token_urlsafe(32))\") and set "
        "DATABASE_URL to it."
    )
