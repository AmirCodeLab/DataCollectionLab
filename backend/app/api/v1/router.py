from fastapi import APIRouter

from app.api.v1 import (
    auth,
    cases,
    datasets,
    devices,
    exports,
    forms,
    media,
    people,
    projects,
    roles,
    submissions,
    sync,
    teams,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(cases.router, prefix="/cases", tags=["cases"])
api_router.include_router(datasets.router, prefix="/datasets", tags=["datasets"])
api_router.include_router(devices.router, prefix="/devices", tags=["devices"])
api_router.include_router(exports.router, prefix="/exports", tags=["exports"])
api_router.include_router(forms.router, prefix="/forms", tags=["forms"])
api_router.include_router(media.router, prefix="/media", tags=["media"])
api_router.include_router(people.router, prefix="/people", tags=["people"])
api_router.include_router(roles.router, prefix="/roles", tags=["roles"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(submissions.router, prefix="/submissions", tags=["submissions"])
api_router.include_router(sync.router, prefix="/sync", tags=["sync"])
api_router.include_router(teams.router, prefix="/teams", tags=["teams"])
