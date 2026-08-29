from fastapi import APIRouter

from app.api.v1 import devices, forms, submissions, sync

api_router = APIRouter()
api_router.include_router(devices.router, prefix="/devices", tags=["devices"])
api_router.include_router(forms.router, prefix="/forms", tags=["forms"])
api_router.include_router(submissions.router, prefix="/submissions", tags=["submissions"])
api_router.include_router(sync.router, prefix="/sync", tags=["sync"])
