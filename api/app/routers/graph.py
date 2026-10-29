"""/api/graph - data for the graph explorer (Phase 8)."""

from __future__ import annotations

from fastapi import APIRouter

from app.models.common import DealStatus, error_responses
from app.models.graph import SubgraphOut
from app.services import graph_service

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/subgraph", response_model=SubgraphOut, responses=error_responses(404, 422))
async def get_subgraph(
    sales_person_id: str, include_peers: bool = True, deal_status: DealStatus | None = None
) -> SubgraphOut:
    """The rep, their most recent deals (max 100) with clients and domains, the rep's
    EXPERTISE_IN edges and, if `include_peers`, the SIMILAR_TO peers (not their deals)."""
    return await graph_service.get_subgraph(
        sales_person_id, include_peers, deal_status.value if deal_status else None
    )
