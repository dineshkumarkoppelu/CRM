"""/api/analytics - chart-ready descriptive insights (Phase 4). Always uses clock.today()."""

from __future__ import annotations

from fastapi import APIRouter

from app.models.analytics import (
    CycleOut,
    DomainTrendOut,
    FunnelOut,
    HeatmapOut,
    KpisOut,
    LeaderboardOut,
    PipelineOut,
    SimilarityCompareRow,
    StalledDeal,
    WinRatesOut,
)
from app.models.common import error_responses
from app.models.forecast import BacktestOut, ForecastOut
from app.services import analytics_service, forecast_service, gds_service

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/kpis", response_model=KpisOut)
async def get_kpis() -> KpisOut:
    """Team KPIs: open pipeline, this month's wins/conversions, window win rate, cycle, stalled."""
    return await analytics_service.get_kpis()


@router.get("/pipeline", response_model=PipelineOut)
async def get_pipeline() -> PipelineOut:
    """Open deals per active rep by stage; unassigned open deals are counted separately."""
    return await analytics_service.get_pipeline()


@router.get("/win-rates", response_model=WinRatesOut)
async def get_win_rates() -> WinRatesOut:
    """Win rates in the lookback window, by rep and by domain (null when nothing closed)."""
    return await analytics_service.get_win_rates()


@router.get("/heatmap", response_model=HeatmapOut)
async def get_heatmap() -> HeatmapOut:
    """Rep x domain win-rate grid, computed live from deals (not from EXPERTISE_IN)."""
    return await analytics_service.get_heatmap()


@router.get("/cycle", response_model=CycleOut)
async def get_cycle() -> CycleOut:
    """Average sales cycle (days) and won value of WON deals in the window."""
    return await analytics_service.get_cycle()


@router.get("/stalled", response_model=list[StalledDeal])
async def get_stalled() -> list[StalledDeal]:
    """OPEN deals with no activity for more than `stalled_days`, most stale first."""
    return await analytics_service.get_stalled()


@router.get("/funnel", response_model=FunnelOut)
async def get_funnel() -> FunnelOut:
    """Stage reach and conversion for deals created in the window."""
    return await analytics_service.get_funnel()


@router.get("/leaderboard", response_model=LeaderboardOut)
async def get_leaderboard() -> LeaderboardOut:
    """Clients converted and won value per rep, this month and this quarter."""
    return await analytics_service.get_leaderboard()


@router.get("/forecast", response_model=ForecastOut)
async def get_forecast() -> ForecastOut:
    """Expected client conversions this month per rep (commit / best case / revenue)."""
    return await forecast_service.get_forecast()


@router.get("/forecast/backtest", response_model=BacktestOut)
async def get_forecast_backtest() -> BacktestOut:
    """Last month's forecast rebuilt as of its first day, compared with what actually happened."""
    return await forecast_service.get_backtest()


@router.get(
    "/similarity-compare",
    response_model=list[SimilarityCompareRow],
    responses=error_responses(503),
    description=(
        "Rule-based similarity (Phase 6) next to GDS weighted Node Similarity, for tuning only. "
        + gds_service.COMPARE_NOTE
        + " `persist=true` writes gds_score onto existing SIMILAR_TO edges (never creates any)."
    ),
)
async def get_similarity_compare(persist: bool = False) -> list[SimilarityCompareRow]:
    return await gds_service.compare(persist=persist)


@router.get("/domain-trend", response_model=DomainTrendOut)
async def get_domain_trend() -> DomainTrendOut:
    """Deals created per domain per month, last 12 months including the current one."""
    return await analytics_service.get_domain_trend()
