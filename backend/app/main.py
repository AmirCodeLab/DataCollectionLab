from fastapi import FastAPI

import app.infrastructure.registry  # noqa: F401  (completes Base.metadata)
from app.api.v1.router import api_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title="Data Collection Platform API",
    version="0.1.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}
