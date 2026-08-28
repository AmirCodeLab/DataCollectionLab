from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    debug: bool = True

    database_url: str = "postgresql+asyncpg://dcp:dcp@localhost:5432/dcp"
    redis_url: str = "redis://localhost:6379/0"

    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "dcp-media"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"

    jwt_secret: str = "change-me-in-production"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
