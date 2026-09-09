from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.published_defaults import PUBLISHED_APP_DB_PASSWORD


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    debug: bool = True

    # Log every endpoint hit: URL, headers, bodies, response. Defaults to on in
    # development only — request bodies carry respondent data, so this is a
    # privacy decision. `http_log_bodies=false` keeps the request line and drops
    # the payloads. Sensitive headers are redacted either way.
    http_log: bool | None = None
    http_log_bodies: bool = True

    @property
    def http_log_enabled(self) -> bool:
        return self.environment == "development" if self.http_log is None else self.http_log

    # Two roles, two URLs (ERD §1). The application connects as `dcp_app`,
    # which the policies bind; the owner runs migrations and provisioning and
    # nothing else, because a superuser is exempt from row-level security and
    # every screen would look correct while no policy applied. The factory
    # (app/infrastructure/database.py) refuses a superuser on the first URL.
    # The password is published (published_defaults.py) and refused outside
    # development at startup, the way the signing key used to be.
    database_url: str = (
        f"postgresql+asyncpg://dcp_app:{PUBLISHED_APP_DB_PASSWORD}@localhost:5432/dcp"
    )
    database_admin_url: str = "postgresql+asyncpg://dcp:dcp@localhost:5432/dcp"
    # SCAFFOLD — the organisation a request is for when nothing else says.
    # Today: the `dcp_org` cookie a login sets names it for every request
    # after the login, and the login itself takes an `organization` field; this
    # setting is the default when that field is absent, which on the pilot's
    # single-tenant deployment is always. It is NOT how a multi-tenant
    # deployment works: provisioning (Phase 3 §9, not in this phase) replaces
    # it with resolution from the hostname — per-customer hostnames, the
    # SurveyCTO shape — and removes this setting in the same change. Until
    # then nothing may read a user without an organisation resolved first
    # (ERD §1), and this is the one place that resolution can come from a
    # constant.
    organization_slug: str = "dev"

    # How long a session lives without use. The row's expiry slides on use
    # (auth/service.TOUCH_INTERVAL). Thirty days, because a handset may not
    # see the network for weeks.
    session_ttl_seconds: int = 60 * 60 * 24 * 30
    redis_url: str = "redis://localhost:6379/0"

    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "dcp-media"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"

    # Where uploaded media chunks are written until the S3 backend lands. See
    # app/infrastructure/media_storage.py — the seam is that module, not this
    # setting, so the switch is one file rather than a search for boto3 calls.
    media_storage_root: str = "./var/media"
    # How long an upload session stays resumable. Long enough to cross a night
    # in a village with no signal; short enough that abandoned half-uploads do
    # not accumulate forever.
    media_session_ttl_seconds: int = 60 * 60 * 24 * 7


@lru_cache
def get_settings() -> Settings:
    return Settings()
