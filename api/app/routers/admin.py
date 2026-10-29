"""Admin endpoints. No authentication in the POC (see product.md)."""

from __future__ import annotations

from fastapi import APIRouter

from app.models.admin import SeedResult
from app.models.assignment import RecomputeResult, RecomputeStatus
from app.services import expertise_service, scheduler, seed_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/seed", response_model=SeedResult)
async def seed() -> SeedResult:
    """WIPES the database, re-runs schema init, loads the synthetic dataset, then recomputes."""
    return await seed_service.seed_database()


@router.post("/recompute", response_model=RecomputeResult)
async def recompute() -> RecomputeResult:
    """Rebuild EXPERTISE_IN and SIMILAR_TO now. 409 BUSY while a seed or recompute runs."""
    return await expertise_service.recompute_exclusive()


@router.get("/recompute/status", response_model=RecomputeStatus)
async def recompute_status() -> RecomputeStatus:
    """Last recompute in this process and the next scheduled run (null if disabled)."""
    last_run_at, last_result = expertise_service.last_run()
    return RecomputeStatus(
        last_run_at=last_run_at, last_result=last_result, next_run_at=scheduler.next_run_at()
    )
