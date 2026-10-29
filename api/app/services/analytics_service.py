"""Descriptive analytics (Phase 4). Definitions: domain-rules.md sections 1-2.

Repositories return raw counts/sums; this module zero-fills, rounds and shapes the responses.
The small pure helpers at the top are unit-tested without a database.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any

from app.core import clock
from app.core.config import get_config
from app.core.numbers import round_half_up
from app.models.analytics import (
    CycleOut,
    DomainCycle,
    DomainSeries,
    DomainTrendOut,
    DomainWinRate,
    FunnelOut,
    FunnelStage,
    HeatmapCell,
    HeatmapOut,
    HeatmapRep,
    KpisOut,
    LeaderboardOut,
    LeaderboardRow,
    PipelineOut,
    PipelineRep,
    RepCycle,
    RepWinRate,
    StageCounts,
    StalledDeal,
    WinRatesOut,
)
from app.repositories import analytics_repo
from app.services.domain_service import domain_names

__all__ = ["round_half_up"]  # re-exported: other services import it from here

STAGES: tuple[str, ...] = ("LEAD", "QUALIFIED", "PROPOSAL", "NEGOTIATION")
TREND_MONTHS = 12


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def round_int(value: float | None) -> int | None:
    """Half-up to a whole number; None stays None."""
    return None if value is None else int(round_half_up(value, 0))


def round_opt(value: float | None, ndigits: int) -> float | None:
    return None if value is None else round_half_up(value, ndigits)


def rate(numerator: int, denominator: int, ndigits: int = 4) -> float | None:
    """numerator / denominator rounded half-up; None (never 0) when the denominator is 0."""
    if denominator == 0:
        return None
    return round_half_up(numerator / denominator, ndigits)


def month_label(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def month_labels(end: date, n: int = TREND_MONTHS) -> list[str]:
    """`n` consecutive "YYYY-MM" labels, ascending, ending with the month containing `end`."""
    first_of_end = date(end.year, end.month, 1)
    return [month_label(clock.subtract_months(first_of_end, k)) for k in range(n - 1, -1, -1)]


def quarter_bounds(d: date) -> tuple[date, date]:
    """(first day, last day) of the calendar quarter containing `d`."""
    first_month = 3 * ((d.month - 1) // 3) + 1
    first = date(d.year, first_month, 1)
    _, last = clock.month_bounds(date(d.year, first_month + 2, 1))
    return first, last


def zero_fill(keys: Iterable[str], counts: Mapping[str, int]) -> dict[str, int]:
    """Every key present, in the given order; missing keys get 0."""
    return {key: int(counts.get(key, 0)) for key in keys}


def _by_domain(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["domain"]: row for row in rows}


# ---------------------------------------------------------------------------
# Context ("today" and derived bounds come only from core/clock.py)
# ---------------------------------------------------------------------------
def _today_and_window() -> tuple[date, date]:
    return clock.today(), clock.window_start(get_config().analytics.lookback_months)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
async def get_kpis() -> KpisOut:
    today, window_start = _today_and_window()
    month_first, month_last = clock.current_month_bounds()
    row = await analytics_repo.kpis(
        today=today, window_start=window_start, month_first=month_first, month_last=month_last
    )
    stalled = await get_stalled()
    return KpisOut(
        open_deals=row["open_deals"],
        open_value=row["open_value"],
        won_this_month=row["won_this_month"],
        clients_converted_this_month=row["clients_converted_this_month"],
        win_rate_window=rate(row["won"], row["handled"]),
        avg_cycle_days=round_opt(row["avg_cycle_days"], 1),
        avg_won_value=round_int(row["avg_won_value"]),
        stalled_count=len(stalled),
    )


async def get_pipeline() -> PipelineOut:
    reps = []
    for row in await analytics_repo.pipeline_active_reps():
        stage_counts = {item["stage"]: item["n"] for item in row["by_stage"]}
        reps.append(
            PipelineRep(
                sales_person_id=row["sales_person_id"],
                name=row["name"],
                open_count=row["open_count"],
                capacity=row["capacity"],
                open_value=row["open_value"],
                by_stage=StageCounts(**zero_fill(STAGES, stage_counts)),
            )
        )
    reps.sort(key=lambda r: (-r.open_count, r.sales_person_id))
    return PipelineOut(
        reps=reps, unassigned_open_count=await analytics_repo.unassigned_open_count()
    )


async def get_win_rates() -> WinRatesOut:
    today, window_start = _today_and_window()
    by_rep = [
        RepWinRate(**row, win_rate=rate(row["won"], row["handled"]))
        for row in await analytics_repo.win_rates_by_rep(today=today, window_start=window_start)
    ]
    domains = _by_domain(
        await analytics_repo.win_rates_by_domain(today=today, window_start=window_start)
    )
    by_domain = []
    for domain in await domain_names():
        row = domains.get(domain, {"handled": 0, "won": 0})
        by_domain.append(
            DomainWinRate(
                domain=domain,
                handled=row["handled"],
                won=row["won"],
                win_rate=rate(row["won"], row["handled"]),
            )
        )
    return WinRatesOut(by_rep=by_rep, by_domain=by_domain)


async def get_heatmap() -> HeatmapOut:
    today, window_start = _today_and_window()
    min_deals = get_config().expertise.min_deals_per_domain
    reps = await analytics_repo.all_reps()
    found = {
        (row["sales_person_id"], row["domain"]): row
        for row in await analytics_repo.heatmap_cells(today=today, window_start=window_start)
    }
    all_domains = await domain_names()
    cells = []
    for rep in reps:
        for domain in all_domains:
            row = found.get((rep["id"], domain), {"handled": 0, "won": 0})
            cells.append(
                HeatmapCell(
                    sales_person_id=rep["id"],
                    domain=domain,
                    handled=row["handled"],
                    won=row["won"],
                    win_rate=rate(row["won"], row["handled"]),
                    qualifies=row["handled"] >= min_deals,
                )
            )
    return HeatmapOut(reps=[HeatmapRep(**rep) for rep in reps], domains=all_domains, cells=cells)


async def get_cycle() -> CycleOut:
    today, window_start = _today_and_window()
    by_rep = [
        RepCycle(
            sales_person_id=row["sales_person_id"],
            name=row["name"],
            won_count=row["won_count"],
            avg_cycle_days=round_opt(row["avg_cycle_days"], 1),
            avg_won_value=round_int(row["avg_won_value"]),
        )
        for row in await analytics_repo.cycle_by_rep(today=today, window_start=window_start)
    ]
    domains = _by_domain(
        await analytics_repo.cycle_by_domain(today=today, window_start=window_start)
    )
    by_domain = []
    for domain in await domain_names():
        row = domains.get(domain, {"won_count": 0, "avg_cycle_days": None, "avg_won_value": None})
        by_domain.append(
            DomainCycle(
                domain=domain,
                won_count=row["won_count"],
                avg_cycle_days=round_opt(row["avg_cycle_days"], 1),
                avg_won_value=round_int(row["avg_won_value"]),
            )
        )
    return CycleOut(by_rep=by_rep, by_domain=by_domain)


async def get_stalled() -> list[StalledDeal]:
    rows = await analytics_repo.stalled(
        today=clock.today(), stalled_days=get_config().analytics.stalled_days
    )
    return [StalledDeal(**row) for row in rows]


async def get_funnel() -> FunnelOut:
    today, window_start = _today_and_window()
    row = await analytics_repo.funnel(today=today, window_start=window_start)
    reached = [row["lead"], row["qualified"], row["proposal"], row["negotiation"]]
    stages = [
        FunnelStage(
            stage=stage,
            reached=reached[i],
            conversion_from_previous=None if i == 0 else rate(reached[i], reached[i - 1]),
        )
        for i, stage in enumerate(STAGES)
    ]
    return FunnelOut(stages=stages, won=row["won"], lost=row["lost"])


def _leaderboard_rows(rows: list[dict[str, Any]]) -> list[LeaderboardRow]:
    board = [LeaderboardRow(**row) for row in rows]
    board.sort(key=lambda r: (-r.clients_converted, -r.won_value, r.sales_person_id))
    return board


async def get_leaderboard() -> LeaderboardOut:
    month_first, month_last = clock.current_month_bounds()
    quarter_first, quarter_last = quarter_bounds(clock.today())
    month = await analytics_repo.leaderboard(period_first=month_first, period_last=month_last)
    quarter = await analytics_repo.leaderboard(period_first=quarter_first, period_last=quarter_last)
    return LeaderboardOut(month=_leaderboard_rows(month), quarter=_leaderboard_rows(quarter))


async def get_domain_trend() -> DomainTrendOut:
    today = clock.today()
    labels = month_labels(today)
    from_date = date(int(labels[0][:4]), int(labels[0][5:]), 1)
    _, to_date = clock.current_month_bounds()
    all_domains = await domain_names()
    counts: dict[str, dict[str, int]] = {domain: {} for domain in all_domains}
    for row in await analytics_repo.domain_trend(from_date=from_date, to_date=to_date):
        label = f"{row['year']:04d}-{row['month']:02d}"
        counts.setdefault(row["domain"], {})[label] = row["n"]
    series = [
        DomainSeries(domain=domain, counts=list(zero_fill(labels, counts[domain]).values()))
        for domain in all_domains
    ]
    return DomainTrendOut(months=labels, series=series)
