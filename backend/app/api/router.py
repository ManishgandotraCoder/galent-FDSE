"""Mounts every HTTP route. Add a new area by including its router here."""

from fastapi import APIRouter

from app.api.eval import router as eval_router
from app.api.files import router as files_router
from app.api.intake import router as intake_router
from app.api.runs import router as runs_router

api_router = APIRouter()
api_router.include_router(files_router)
api_router.include_router(runs_router)
api_router.include_router(intake_router)
api_router.include_router(eval_router)
