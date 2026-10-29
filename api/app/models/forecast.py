"""Response models for the forecast and back-test (api-contracts.md, Phase 5)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel

from app.models.common import Stage

ProbabilitySource = Literal["REP_DOMAIN_STAGE", "TEAM_DOMAIN_STAGE", "TEAM_STAGE"]


class ForecastDeal(BaseModel):
    deal_id: str
    stage: Stage
    value: int
    p_deal: float  # 4 dp
    probability_source: ProbabilitySource


class ForecastClient(BaseModel):
    client_id: str
    client_name: str
    probability: float  # P(C), 4 dp
    deals: list[ForecastDeal]


class ForecastTotals(BaseModel):
    expected_conversions: float  # 2 dp
    commit: int
    best_case: int
    expected_revenue: int  # INR
    converted_so_far: int


class ForecastRep(ForecastTotals):
    sales_person_id: str
    name: str
    clients: list[ForecastClient]


class ForecastOut(BaseModel):
    month: str  # YYYY-MM
    team: ForecastTotals
    by_rep: list[ForecastRep]  # all active reps, expected_conversions desc


class BacktestRep(BaseModel):
    sales_person_id: str
    name: str
    predicted_expected: float  # 2 dp
    actual: int
    abs_error: float  # 2 dp


class BacktestTeam(BaseModel):
    predicted_expected: float
    actual: int
    abs_error: float


class BacktestOut(BaseModel):
    month: str  # YYYY-MM (the previous month)
    asof: date  # first day of that month
    by_rep: list[BacktestRep]
    team: BacktestTeam
    mean_abs_error: float  # mean of the per-rep abs_error, 2 dp
    limitations: list[str]
