"""Admin endpoints. No authentication in the POC (see product.md)."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.errors import AppError
from app.models.admin import SeedResult
from app.models.assignment import RecomputeResult, RecomputeStatus
from app.models.sync import SyncResult, SyncStatusOut
from app.services import expertise_service, scheduler, seed_service
from app.sync import service as sync_service
from app.sync import source_client

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/seed", response_model=SeedResult)
async def seed() -> SeedResult:
    """Standalone mode: WIPES the database, re-runs schema init, loads the synthetic dataset,
    then recomputes. With a data source configured (SOURCE_API_URL) nothing is generated: it
    re-syncs Neo4j from the source instead."""
    return await seed_service.seed_database()


@router.post("/resync", response_model=SyncResult)
async def resync(hard: bool = False) -> SyncResult:
    """Make Neo4j match the data source now. `hard=true` also replaces everything else Neo4j
    holds (people, clients, deals, activities) as on the very first sync."""
    if not source_client.enabled():
        raise AppError(
            "SOURCE_NOT_CONFIGURED", "No data source: set SOURCE_API_URL and SOURCE_API_KEY", 409
        )
    return await sync_service.full_sync(force_adopt=hard)


@router.get("/sync/status", response_model=SyncStatusOut)
async def sync_status() -> SyncStatusOut:
    """Sync mode, whether the live link is up, last sync result and rows that were skipped."""
    return sync_service.status()


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
