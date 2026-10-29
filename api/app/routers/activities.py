"""/api/activities"""

from __future__ import annotations

from fastapi import APIRouter

from app.models.activities import ActivityCreate, ActivityOut
from app.models.common import error_responses
from app.services import crud_service

router = APIRouter(prefix="/activities", tags=["activities"])


@router.post(
    "", response_model=ActivityOut, status_code=201, responses=error_responses(400, 404, 422)
)
async def create_activity(body: ActivityCreate) -> ActivityOut:
    """`date` defaults to today; must be on/after the deal's created_at and not after today
    (or after closed_at for closed deals)."""
    return await crud_service.create_activity(body)
