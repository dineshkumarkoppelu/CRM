"""/api/deals"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.models.activities import ActivityOut
from app.models.common import (
    DEFAULT_LIMIT,
    DealStatus,
    Domain,
    LimitQuery,
    OffsetQuery,
    Page,
    Stage,
    error_responses,
)
from app.models.deals import (
    DealCreate,
    DealCreateResult,
    DealDetail,
    DealOut,
    DealUpdate,
    StageMove,
)
from app.services import crud_service

router = APIRouter(prefix="/deals", tags=["deals"])

ClosingMonth = Annotated[
    str | None,
    Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="expected_close_date month, YYYY-MM"),
]


@router.get("", response_model=Page[DealOut], responses=error_responses(422))
async def list_deals(
    status: DealStatus | None = None,
    stage: Stage | None = None,
    domain: Domain | None = None,
    owner_id: str | None = None,
    client_id: str | None = None,
    closing_month: ClosingMonth = None,
    limit: LimitQuery = DEFAULT_LIMIT,
    offset: OffsetQuery = 0,
) -> Page[DealOut]:
    return await crud_service.list_deals(
        status=status,
        stage=stage,
        domain=domain,
        owner_id=owner_id,
        client_id=client_id,
        closing_month=closing_month,
        limit=limit,
        offset=offset,
    )


@router.get("/{deal_id}", response_model=DealDetail, responses=error_responses(404))
async def get_deal(deal_id: str) -> DealDetail:
    return await crud_service.get_deal(deal_id)


@router.post(
    "", response_model=DealCreateResult, status_code=201, responses=error_responses(404, 409, 422)
)
async def create_deal(body: DealCreate) -> DealCreateResult:
    """A new deal for an existing client; assigned automatically unless owner_id is given."""
    return await crud_service.create_deal(body)


@router.post(
    "/{deal_id}/stage", response_model=DealOut, responses=error_responses(400, 404, 409, 422)
)
async def move_deal_stage(deal_id: str, body: StageMove) -> DealOut:
    """ADVANCE = next stage; WIN only from NEGOTIATION; LOSE from any open stage."""
    return await crud_service.move_deal_stage(deal_id, body.action)


@router.patch("/{deal_id}", response_model=DealOut, responses=error_responses(400, 404, 422))
async def update_deal(deal_id: str, body: DealUpdate) -> DealOut:
    """Edit title, value or expected_close_date of an OPEN deal."""
    return await crud_service.update_deal(deal_id, body)


@router.get(
    "/{deal_id}/activities", response_model=list[ActivityOut], responses=error_responses(404)
)
async def list_deal_activities(deal_id: str) -> list[ActivityOut]:
    """Activities on the deal, newest first."""
    return await crud_service.list_deal_activities(deal_id)
