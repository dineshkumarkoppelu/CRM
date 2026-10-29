"""/api/clients"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.models.clients import ClientCreateResult, ClientDetail, ClientOut, ClientWithDealCreate
from app.models.common import DEFAULT_LIMIT, LimitQuery, OffsetQuery, Page, error_responses
from app.services import crud_service

router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("", response_model=Page[ClientOut], responses=error_responses(422))
async def list_clients(
    q: Annotated[str | None, Query(max_length=200, description="Name contains (any case)")] = None,
    limit: LimitQuery = DEFAULT_LIMIT,
    offset: OffsetQuery = 0,
) -> Page[ClientOut]:
    return await crud_service.list_clients(q, limit, offset)


@router.get("/{client_id}", response_model=ClientDetail, responses=error_responses(404))
async def get_client(client_id: str) -> ClientDetail:
    return await crud_service.get_client(client_id)


@router.post(
    "",
    response_model=ClientCreateResult,
    status_code=201,
    responses=error_responses(404, 409, 422),
)
async def create_client_with_deal(body: ClientWithDealCreate) -> ClientCreateResult:
    """Creates the client and its first deal atomically, then assigns the deal."""
    return await crud_service.create_client_with_deal(body)
