from fastapi import APIRouter

from app.api.v1 import forms, sync

api_router = APIRouter()
api_router.include_router(forms.router, prefix="/forms", tags=["forms"])
api_router.include_router(sync.router, prefix="/sync", tags=["sync"])
