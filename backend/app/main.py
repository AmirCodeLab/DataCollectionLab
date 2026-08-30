from fastapi import FastAPI

from app.api.schemas import Health
from app.api.v1.router import api_router
from app.core.config import get_settings

# Aliased, not `import app.infrastructure.registry`: that binds the name `app`
# to the package and shadows the FastAPI instance below, leaving mypy unable to
# check a single call in this file.
from app.infrastructure import registry as _registry  # noqa: F401  (completes Base.metadata)
from app.infrastructure.http_logging import HttpLoggingMiddleware, configure_logging

settings = get_settings()

app = FastAPI(
    title="Data Collection Platform API",
    version="0.1.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
)

if settings.http_log_enabled:
    configure_logging()
    app.add_middleware(HttpLoggingMiddleware, log_bodies=settings.http_log_bodies)

app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["system"], response_model=Health)
async def health() -> Health:
    """Liveness, and which deployment this is."""
    return Health(status="ok", environment=settings.environment)
