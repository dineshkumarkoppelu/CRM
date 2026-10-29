"""Response models for /api/analytics (api-contracts.md, Phase 4)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from app.models.common import Domain, Stage


class KpisOut(BaseModel):
    open_deals: int
    open_value: int
    won_this_month: int
    clients_converted_this_month: int
    win_rate_window: float | None  # 4 dp; null when no closed deals in the window
    avg_cycle_days: float | None  # 1 dp; WON deals in the window
    avg_won_value: int | None  # INR; WON deals in the window
    stalled_count: int


class StageCounts(BaseModel):
    LEAD: int
    QUALIFIED: int
    PROPOSAL: int
    NEGOTIATION: int


class PipelineRep(BaseModel):
    sales_person_id: str
    name: str
    open_count: int
    capacity: int
    open_value: int
    by_stage: StageCounts


class PipelineOut(BaseModel):
    reps: list[PipelineRep]  # every ACTIVE rep, open_count desc then id
    unassigned_open_count: int  # OPEN deals without an owner (not in any rep row)


class RepWinRate(BaseModel):
    sales_person_id: str
    name: str
    handled: int
    won: int
    win_rate: float | None


class DomainWinRate(BaseModel):
    domain: Domain
    handled: int
    won: int
    win_rate: float | None


class WinRatesOut(BaseModel):
    by_rep: list[RepWinRate]
    by_domain: list[DomainWinRate]


class HeatmapRep(BaseModel):
    id: str
    name: str


class HeatmapCell(BaseModel):
    sales_person_id: str
    domain: Domain
    handled: int
    won: int
    win_rate: float | None
    qualifies: bool


class HeatmapOut(BaseModel):
    reps: list[HeatmapRep]
    domains: list[Domain]
    cells: list[HeatmapCell]  # reps x domains, always complete


class RepCycle(BaseModel):
    sales_person_id: str
    name: str
    avg_cycle_days: float | None
    avg_won_value: int | None
    won_count: int


class DomainCycle(BaseModel):
    domain: Domain
    avg_cycle_days: float | None
    avg_won_value: int | None
    won_count: int


class CycleOut(BaseModel):
    by_rep: list[RepCycle]
    by_domain: list[DomainCycle]


class StalledDeal(BaseModel):
    deal_id: str
    title: str
    owner_id: str | None
    owner_name: str | None
    client_name: str
    domain: Domain
    stage: Stage
    last_activity_date: date | None
    days_since_activity: int


class FunnelStage(BaseModel):
    stage: Stage
    reached: int
    conversion_from_previous: float | None  # null for LEAD


class FunnelOut(BaseModel):
    stages: list[FunnelStage]
    won: int
    lost: int


class LeaderboardRow(BaseModel):
    sales_person_id: str
    name: str
    clients_converted: int
    won_value: int


class LeaderboardOut(BaseModel):
    month: list[LeaderboardRow]
    quarter: list[LeaderboardRow]


class DomainSeries(BaseModel):
    domain: Domain
    counts: list[int]


class DomainTrendOut(BaseModel):
    months: list[str]  # "YYYY-MM", ascending, 12 months ending with the current month
    series: list[DomainSeries]


class SimilarityCompareRow(BaseModel):
    """Phase 7. rule_score = Phase 6 rule (used for assignment); gds_score = weighted Jaccard."""

    rep_a: str
    rep_b: str
    rule_score: float | None
    rule_matched_domains: list[str] | None
    gds_score: float | None
