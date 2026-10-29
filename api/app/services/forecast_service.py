"""Per-client monthly conversion forecast and back-test (domain-rules.md sections 7-8).

Everything except the two endpoint functions at the bottom is pure and unit-tested.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from app.core import clock
from app.core.config import get_config
from app.models.forecast import (
    BacktestOut,
    BacktestRep,
    BacktestTeam,
    ForecastClient,
    ForecastDeal,
    ForecastOut,
    ForecastRep,
    ForecastTotals,
)
from app.repositories import forecast_repo
from app.services.analytics_service import month_label, round_half_up

STAGES: tuple[str, ...] = ("LEAD", "QUALIFIED", "PROPOSAL", "NEGOTIATION")
STAGE_DATE_FIELD: dict[str, str | None] = {
    "LEAD": None,  # every deal reached LEAD
    "QUALIFIED": "qualified_at",
    "PROPOSAL": "proposal_at",
    "NEGOTIATION": "negotiation_at",
}
REP_DOMAIN_STAGE = "REP_DOMAIN_STAGE"
TEAM_DOMAIN_STAGE = "TEAM_DOMAIN_STAGE"
TEAM_STAGE = "TEAM_STAGE"

BACKTEST_LIMITATIONS = [
    "Owner history is not tracked; current owner is used.",
    "Expected close date history is not tracked; final value is used.",
]

# P(C) is a product of floats; a value that is mathematically equal to a threshold may land a
# hair below it (e.g. 0.6999999999999999). Thresholds are compared with this tolerance.
THRESHOLD_EPSILON = 1e-9


# ---------------------------------------------------------------------------
# Probability table (R5.2)
# ---------------------------------------------------------------------------
def reached_stages(row: Mapping[str, Any]) -> list[str]:
    """Stages a deal reached: LEAD always, others when their stage date is set."""
    return [s for s, f in STAGE_DATE_FIELD.items() if f is None or row.get(f) is not None]


@dataclass
class ProbabilityTable:
    """Won/total counts of closed deals per (rep, domain, stage), (domain, stage) and stage."""

    min_sample: int
    rep_domain_stage: dict[tuple[str, str, str], list[int]] = field(default_factory=dict)
    domain_stage: dict[tuple[str, str], list[int]] = field(default_factory=dict)
    stage: dict[str, list[int]] = field(default_factory=dict)

    def lookup(self, rep_id: str, domain: str, stage: str) -> tuple[float, str]:
        """(p, source) using the fallback chain; TEAM_STAGE is the last resort even if small."""
        won, n = self.rep_domain_stage.get((rep_id, domain, stage), (0, 0))
        if n >= self.min_sample:
            return won / n, REP_DOMAIN_STAGE
        won, n = self.domain_stage.get((domain, stage), (0, 0))
        if n >= self.min_sample:
            return won / n, TEAM_DOMAIN_STAGE
        won, n = self.stage.get(stage, (0, 0))
        return (won / n if n else 0.0), TEAM_STAGE


def build_probability_table(
    closed_rows: Iterable[Mapping[str, Any]], min_sample: int
) -> ProbabilityTable:
    """Rows: owner_id (may be None), domain, status, qualified_at, proposal_at, negotiation_at
    (any non-null value = stage reached), and optionally `n` = how many identical deals the
    row stands for (default 1)."""
    table = ProbabilityTable(min_sample=min_sample)
    for row in closed_rows:
        n = int(row.get("n", 1))
        won = n if row["status"] == "WON" else 0
        for stage in reached_stages(row):
            keys: list[tuple[dict, Any]] = [
                (table.domain_stage, (row["domain"], stage)),
                (table.stage, stage),
            ]
            if row.get("owner_id") is not None:  # unowned deals only count at team level
                keys.append((table.rep_domain_stage, (row["owner_id"], row["domain"], stage)))
            for bucket, key in keys:
                counts = bucket.setdefault(key, [0, 0])
                counts[0] += won
                counts[1] += n
    return table


# ---------------------------------------------------------------------------
# Aggregation (R5.3) and back-test helpers (R5.4)
# ---------------------------------------------------------------------------
def client_probability(p_list: Iterable[float]) -> float:
    """P(C) = 1 - prod(1 - p): the chance at least one of the client's deals is won."""
    return 1.0 - math.prod(1.0 - p for p in p_list)


def at_least(value: float, threshold: float) -> bool:
    return value >= threshold - THRESHOLD_EPSILON


def stage_as_of(row: Mapping[str, Any], asof: date) -> str:
    """Latest stage whose date is <= asof (LEAD if none was set by then)."""
    current = "LEAD"
    for stage in STAGES[1:]:
        field_name = STAGE_DATE_FIELD[stage]
        stage_date = row.get(field_name) if field_name else None
        if stage_date is not None and stage_date <= asof:
            current = stage
    return current


@dataclass(frozen=True)
class ScoredDeal:
    deal_id: str
    owner_id: str
    client_id: str
    client_name: str
    stage: str
    value: int
    p: float
    source: str


def score_deals(deals: Iterable[Mapping[str, Any]], table: ProbabilityTable) -> list[ScoredDeal]:
    """Attach p_deal and its source. Each row needs: deal_id, owner_id, client_id, client_name,
    domain, stage, value."""
    scored = []
    for d in deals:
        p, source = table.lookup(d["owner_id"], d["domain"], d["stage"])
        scored.append(
            ScoredDeal(
                deal_id=d["deal_id"],
                owner_id=d["owner_id"],
                client_id=d["client_id"],
                client_name=d["client_name"],
                stage=d["stage"],
                value=d["value"],
                p=p,
                source=source,
            )
        )
    return scored


def group_by_client(deals: Iterable[ScoredDeal]) -> dict[str, list[ScoredDeal]]:
    grouped: dict[str, list[ScoredDeal]] = defaultdict(list)
    for d in deals:
        grouped[d.client_id].append(d)
    return dict(grouped)


@dataclass(frozen=True)
class Totals:
    expected_conversions: float  # unrounded
    commit: int
    best_case: int
    expected_revenue: float  # unrounded
    client_probabilities: dict[str, float]


def totals(deals: Sequence[ScoredDeal], commit_threshold: float, best_threshold: float) -> Totals:
    """Totals over a set of deals; P(C) is computed per client over the deals given."""
    probabilities = {
        client_id: client_probability(d.p for d in client_deals)
        for client_id, client_deals in group_by_client(deals).items()
    }
    return Totals(
        expected_conversions=sum(probabilities.values()),
        commit=sum(at_least(p, commit_threshold) for p in probabilities.values()),
        best_case=sum(at_least(p, best_threshold) for p in probabilities.values()),
        expected_revenue=sum(d.value * d.p for d in deals),
        client_probabilities=probabilities,
    )


def _rep_clients(
    deals: Sequence[ScoredDeal], probabilities: dict[str, float]
) -> list[ForecastClient]:
    clients = []
    for client_id, client_deals in group_by_client(deals).items():
        clients.append(
            ForecastClient(
                client_id=client_id,
                client_name=client_deals[0].client_name,
                probability=round_half_up(probabilities[client_id], 4),
                deals=[
                    ForecastDeal(
                        deal_id=d.deal_id,
                        stage=d.stage,
                        value=d.value,
                        p_deal=round_half_up(d.p, 4),
                        probability_source=d.source,
                    )
                    for d in sorted(client_deals, key=lambda d: (-d.p, d.deal_id))
                ],
            )
        )
    clients.sort(key=lambda c: (-c.probability, c.client_id))
    return clients


def build_forecast(
    *,
    month: str,
    scored: Sequence[ScoredDeal],
    reps: Sequence[Mapping[str, Any]],
    converted_by_rep: Mapping[str, int],
    converted_team: int,
    commit_threshold: float,
    best_threshold: float,
) -> ForecastOut:
    by_rep = []
    for rep in reps:
        mine = [d for d in scored if d.owner_id == rep["id"]]
        t = totals(mine, commit_threshold, best_threshold)
        by_rep.append(
            ForecastRep(
                sales_person_id=rep["id"],
                name=rep["name"],
                expected_conversions=round_half_up(t.expected_conversions, 2),
                commit=t.commit,
                best_case=t.best_case,
                expected_revenue=int(round_half_up(t.expected_revenue, 0)),
                converted_so_far=converted_by_rep.get(rep["id"], 0),
                clients=_rep_clients(mine, t.client_probabilities),
            )
        )
    by_rep.sort(key=lambda r: (-r.expected_conversions, r.sales_person_id))

    team = totals(scored, commit_threshold, best_threshold)  # P(C) across all owners
    return ForecastOut(
        month=month,
        team=ForecastTotals(
            expected_conversions=round_half_up(team.expected_conversions, 2),
            commit=team.commit,
            best_case=team.best_case,
            expected_revenue=int(round_half_up(team.expected_revenue, 0)),
            converted_so_far=converted_team,
        ),
        by_rep=by_rep,
    )


def build_backtest(
    *,
    month: str,
    asof: date,
    scored: Sequence[ScoredDeal],
    reps: Sequence[Mapping[str, Any]],
    actual_by_rep: Mapping[str, int],
    actual_team: int,
    commit_threshold: float,
    best_threshold: float,
) -> BacktestOut:
    rows = []
    for rep in reps:
        predicted = totals(
            [d for d in scored if d.owner_id == rep["id"]], commit_threshold, best_threshold
        ).expected_conversions
        actual = actual_by_rep.get(rep["id"], 0)
        rows.append(
            BacktestRep(
                sales_person_id=rep["id"],
                name=rep["name"],
                predicted_expected=round_half_up(predicted, 2),
                actual=actual,
                abs_error=round_half_up(abs(predicted - actual), 2),
            )
        )
    team_predicted = totals(scored, commit_threshold, best_threshold).expected_conversions
    mean_abs_error = sum(r.abs_error for r in rows) / len(rows) if rows else 0.0
    return BacktestOut(
        month=month,
        asof=asof,
        by_rep=rows,
        team=BacktestTeam(
            predicted_expected=round_half_up(team_predicted, 2),
            actual=actual_team,
            abs_error=round_half_up(abs(team_predicted - actual_team), 2),
        ),
        mean_abs_error=round_half_up(mean_abs_error, 2),
        limitations=list(BACKTEST_LIMITATIONS),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
async def get_forecast() -> ForecastOut:
    config = get_config()
    today = clock.today()
    month_first, month_last = clock.current_month_bounds()

    history = await forecast_repo.closed_history(
        window_start=clock.window_start(config.analytics.lookback_months),
        window_end_exclusive=today + timedelta(days=1),  # window ends at today, inclusive
    )
    table = build_probability_table(history, config.expertise.min_deals_per_domain)
    scored = score_deals(
        await forecast_repo.in_scope_open(month_first=month_first, month_last=month_last), table
    )
    converted_by_rep, converted_team = await forecast_repo.conversions(
        from_date=month_first, to_date=today
    )
    return build_forecast(
        month=month_label(today),
        scored=scored,
        reps=await forecast_repo.active_reps(),
        converted_by_rep=converted_by_rep,
        converted_team=converted_team,
        commit_threshold=config.forecast.forecast_commit_threshold,
        best_threshold=config.forecast.forecast_best_case_threshold,
    )


async def get_backtest() -> BacktestOut:
    config = get_config()
    month_first, month_last = clock.previous_month_bounds()
    asof = month_first

    history = await forecast_repo.closed_history(
        window_start=clock.subtract_months(asof, config.analytics.lookback_months),
        window_end_exclusive=asof,  # only deals closed strictly before asof
    )
    table = build_probability_table(history, config.expertise.min_deals_per_domain)
    pipeline = await forecast_repo.backtest_pipeline(
        asof=asof, month_first=month_first, month_last=month_last
    )
    scored = score_deals(({**row, "stage": stage_as_of(row, asof)} for row in pipeline), table)
    actual_by_rep, actual_team = await forecast_repo.conversions(
        from_date=month_first, to_date=month_last
    )
    return build_backtest(
        month=month_label(month_first),
        asof=asof,
        scored=scored,
        reps=await forecast_repo.active_reps(),
        actual_by_rep=actual_by_rep,
        actual_team=actual_team,
        commit_threshold=config.forecast.forecast_commit_threshold,
        best_threshold=config.forecast.forecast_best_case_threshold,
    )
