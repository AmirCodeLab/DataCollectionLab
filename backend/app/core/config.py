from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.published_defaults import PUBLISHED_JWT_SECRET


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
    database_url: str = "postgresql+asyncpg://dcp_app:dcp_app@localhost:5432/dcp"
    database_admin_url: str = "postgresql+asyncpg://dcp:dcp@localhost:5432/dcp"
    # The deployment's one organisation, resolved before any user is read
    # (ERD §1). Single-tenant until provisioning delivers the resolution.
    organization_slug: str = "dev"
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

    # Published, and refused outside development at startup. See
    # app/core/published_defaults.py.
    jwt_secret: str = PUBLISHED_JWT_SECRET
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
