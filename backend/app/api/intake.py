from fastapi import APIRouter

from app.services.intake import current_intake
from app.schemas.intake import IntakeStatus

router = APIRouter(tags=["intake"])


@router.get("/api/intake", response_model=IntakeStatus)
def get_intake() -> IntakeStatus:
    return current_intake()
