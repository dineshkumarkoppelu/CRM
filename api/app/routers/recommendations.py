"""/api/recommendations - the assignment engine (Phase 6)."""

from __future__ import annotations

from fastapi import APIRouter

from app.models.assignment import AssignmentResult, OverrideRequest
from app.models.common import error_responses
from app.services import assignment_service

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("/{deal_id}", response_model=AssignmentResult, responses=error_responses(404))
async def get_recommendations(deal_id: str) -> AssignmentResult:
    """The stored ranking (RECOMMENDED_TO edges) for a deal. Does not recompute."""
    return await assignment_service.get_recommendations(deal_id)


@router.post(
    "/{deal_id}/run", response_model=AssignmentResult, responses=error_responses(400, 404, 409)
)
async def run_assignment(deal_id: str) -> AssignmentResult:
    """Rank and assign an OPEN deal that has no owner (409 ALREADY_ASSIGNED otherwise)."""
    return await assignment_service.assign_deal(deal_id)


@router.post(
    "/{deal_id}/preview", response_model=AssignmentResult, responses=error_responses(400, 404)
)
async def preview_assignment(deal_id: str) -> AssignmentResult:
    """The ranking computed live right now. Nothing is written."""
    return await assignment_service.preview_deal(deal_id)


@router.post(
    "/{deal_id}/override",
    response_model=AssignmentResult,
    responses=error_responses(400, 404, 409, 422),
)
async def override_assignment(deal_id: str, body: OverrideRequest) -> AssignmentResult:
    """Manager override: give the deal to an available sales person."""
    return await assignment_service.override(deal_id, body.sales_person_id)
