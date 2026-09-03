from fastapi import APIRouter

from app.api.v1 import (
    datasets,
    devices,
    exports,
    forms,
    media,
    projects,
    submissions,
    sync,
)

api_router = APIRouter()
api_router.include_router(datasets.router, prefix="/datasets", tags=["datasets"])
api_router.include_router(devices.router, prefix="/devices", tags=["devices"])
api_router.include_router(exports.router, prefix="/exports", tags=["exports"])
api_router.include_router(forms.router, prefix="/forms", tags=["forms"])
api_router.include_router(media.router, prefix="/media", tags=["media"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(submissions.router, prefix="/submissions", tags=["submissions"])
api_router.include_router(sync.router, prefix="/sync", tags=["sync"])
