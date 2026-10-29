"""GET /api/health."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.errors import error_body
from app.models.health import HealthOut
from app.services import health_service

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthOut,
    responses={503: {"description": "Neo4j unreachable: health body plus the standard error"}},
)
async def get_health() -> HealthOut | JSONResponse:
    health = await health_service.get_health()
    if not health.neo4j.connected:
        # 503 keeps the full health shape (so scripts/UI can read it) and adds the
        # standard `error` object.
        content = health.model_dump(mode="json") | error_body(
            "NEO4J_UNAVAILABLE", "Neo4j is not reachable"
        )
        return JSONResponse(status_code=503, content=content)
    return health
