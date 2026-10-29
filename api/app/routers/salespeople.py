"""/api/salespeople"""

from __future__ import annotations

from fastapi import APIRouter

from app.models.common import DEFAULT_LIMIT, LimitQuery, OffsetQuery, Page, error_responses
from app.models.salespeople import (
    SalesPersonCreate,
    SalesPersonDetail,
    SalesPersonOut,
    SalesPersonUpdate,
)
from app.services import crud_service

router = APIRouter(prefix="/salespeople", tags=["sales people"])


@router.get("", response_model=Page[SalesPersonOut], responses=error_responses(422))
async def list_sales_people(
    active: bool | None = None, limit: LimitQuery = DEFAULT_LIMIT, offset: OffsetQuery = 0
) -> Page[SalesPersonOut]:
    return await crud_service.list_sales_people(active, limit, offset)


@router.get("/{rep_id}", response_model=SalesPersonDetail, responses=error_responses(404))
async def get_sales_person(rep_id: str) -> SalesPersonDetail:
    return await crud_service.get_sales_person(rep_id)


@router.post(
    "", response_model=SalesPersonOut, status_code=201, responses=error_responses(409, 422)
)
async def create_sales_person(body: SalesPersonCreate) -> SalesPersonOut:
    return await crud_service.create_sales_person(body)


@router.patch("/{rep_id}", response_model=SalesPersonOut, responses=error_responses(404, 422))
async def update_sales_person(rep_id: str, body: SalesPersonUpdate) -> SalesPersonOut:
    return await crud_service.update_sales_person(rep_id, body)
