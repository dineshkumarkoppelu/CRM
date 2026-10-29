"""Cypher for the descriptive analytics (Phase 4).

Rules: counts and sums are aggregated here; zero-filling, rounding and shaping happen in the
service. "Today", window and period bounds always arrive as parameters (never Cypher `date()`).
Lookback window = closed_at in ($window_start, $today].
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.core.db import run_read

# Three one-row aggregates chained with WITH (each aggregation without grouping keys yields
# exactly one row, even when nothing matches), so the plan has no CartesianProduct.
KPIS = """
MATCH (o:Deal) WHERE o.status = 'OPEN'
WITH count(o) AS open_deals, coalesce(sum(o.value), 0) AS open_value
OPTIONAL MATCH (w:Deal)-[:FOR_CLIENT]->(c:Client)
WHERE w.status = 'WON' AND w.closed_at >= $month_first AND w.closed_at <= $month_last
WITH open_deals, open_value,
     count(DISTINCT w) AS won_this_month, count(DISTINCT c) AS clients_converted_this_month
OPTIONAL MATCH (d:Deal)
WHERE d.status IN ['WON', 'LOST'] AND d.closed_at > $window_start AND d.closed_at <= $today
RETURN open_deals, open_value, won_this_month, clients_converted_this_month,
       count(d) AS handled,
       count(CASE WHEN d.status = 'WON' THEN 1 END) AS won,
       avg(CASE WHEN d.status = 'WON'
                THEN duration.inDays(d.created_at, d.closed_at).days END) AS avg_cycle_days,
       avg(CASE WHEN d.status = 'WON' THEN d.value END) AS avg_won_value
"""

PIPELINE_ACTIVE_REPS = """
MATCH (s:SalesPerson)
WHERE s.active = true
OPTIONAL MATCH (s)-[:OWNS]->(d:Deal)
WHERE d.status = 'OPEN'
WITH s, d.stage AS stage, count(d) AS n, sum(d.value) AS value
WITH s,
     collect(CASE WHEN stage IS NULL THEN null ELSE {stage: stage, n: n} END) AS by_stage,
     sum(n) AS open_count,
     sum(value) AS open_value
RETURN s.id AS sales_person_id, s.name AS name, s.capacity AS capacity,
       open_count, coalesce(open_value, 0) AS open_value, by_stage
"""

UNASSIGNED_OPEN = """
MATCH (d:Deal)
WHERE d.status = 'OPEN' AND NOT EXISTS { (:SalesPerson)-[:OWNS]->(d) }
RETURN count(d) AS n
"""

WIN_RATES_BY_REP = """
MATCH (s:SalesPerson)
OPTIONAL MATCH (s)-[:OWNS]->(d:Deal)
WHERE d.status IN ['WON', 'LOST'] AND d.closed_at > $window_start AND d.closed_at <= $today
RETURN s.id AS sales_person_id, s.name AS name, count(d) AS handled,
       count(CASE WHEN d.status = 'WON' THEN 1 END) AS won
ORDER BY sales_person_id
"""

WIN_RATES_BY_DOMAIN = """
MATCH (dom:Domain)
OPTIONAL MATCH (d:Deal)-[:IN_DOMAIN]->(dom)
WHERE d.status IN ['WON', 'LOST'] AND d.closed_at > $window_start AND d.closed_at <= $today
RETURN dom.name AS domain, count(d) AS handled,
       count(CASE WHEN d.status = 'WON' THEN 1 END) AS won
"""

ALL_REPS = """
MATCH (s:SalesPerson)
RETURN s.id AS id, s.name AS name
ORDER BY id
"""

# Computed live from Deal nodes - NOT from EXPERTISE_IN.
HEATMAP_CELLS = """
MATCH (s:SalesPerson)-[:OWNS]->(d:Deal)-[:IN_DOMAIN]->(dom:Domain)
WHERE d.status IN ['WON', 'LOST'] AND d.closed_at > $window_start AND d.closed_at <= $today
RETURN s.id AS sales_person_id, dom.name AS domain, count(d) AS handled,
       count(CASE WHEN d.status = 'WON' THEN 1 END) AS won
"""

CYCLE_BY_REP = """
MATCH (s:SalesPerson)
OPTIONAL MATCH (s)-[:OWNS]->(d:Deal)
WHERE d.status = 'WON' AND d.closed_at > $window_start AND d.closed_at <= $today
RETURN s.id AS sales_person_id, s.name AS name, count(d) AS won_count,
       avg(duration.inDays(d.created_at, d.closed_at).days) AS avg_cycle_days,
       avg(d.value) AS avg_won_value
ORDER BY sales_person_id
"""

CYCLE_BY_DOMAIN = """
MATCH (dom:Domain)
OPTIONAL MATCH (d:Deal)-[:IN_DOMAIN]->(dom)
WHERE d.status = 'WON' AND d.closed_at > $window_start AND d.closed_at <= $today
RETURN dom.name AS domain, count(d) AS won_count,
       avg(duration.inDays(d.created_at, d.closed_at).days) AS avg_cycle_days,
       avg(d.value) AS avg_won_value
"""

# OPEN deals whose latest activity (or created_at if none) is more than $stalled_days old.
STALLED = """
MATCH (d:Deal)
WHERE d.status = 'OPEN'
OPTIONAL MATCH (a:Activity)-[:ON_DEAL]->(d)
WITH d, max(a.date) AS last_activity_date
WITH d, last_activity_date,
     duration.inDays(coalesce(last_activity_date, d.created_at), $today).days AS days_since
WHERE days_since > $stalled_days
MATCH (d)-[:IN_DOMAIN]->(dom:Domain)
MATCH (d)-[:FOR_CLIENT]->(c:Client)
OPTIONAL MATCH (s:SalesPerson)-[:OWNS]->(d)
RETURN d.id AS deal_id, d.title AS title, s.id AS owner_id, s.name AS owner_name,
       c.name AS client_name, dom.name AS domain, d.stage AS stage,
       last_activity_date, days_since AS days_since_activity
ORDER BY days_since_activity DESC, deal_id
"""

# Population: deals CREATED in the window. A stage counts as reached when its date is set.
FUNNEL = """
MATCH (d:Deal)
WHERE d.created_at > $window_start AND d.created_at <= $today
RETURN count(d) AS lead,
       count(d.qualified_at) AS qualified,
       count(d.proposal_at) AS proposal,
       count(d.negotiation_at) AS negotiation,
       count(CASE WHEN d.status = 'WON' THEN 1 END) AS won,
       count(CASE WHEN d.status = 'LOST' THEN 1 END) AS lost
"""

LEADERBOARD = """
MATCH (s:SalesPerson)
OPTIONAL MATCH (s)-[:OWNS]->(d:Deal)-[:FOR_CLIENT]->(c:Client)
WHERE d.status = 'WON' AND d.closed_at >= $period_first AND d.closed_at <= $period_last
RETURN s.id AS sales_person_id, s.name AS name,
       count(DISTINCT c) AS clients_converted, coalesce(sum(d.value), 0) AS won_value
"""

DOMAIN_TREND = """
MATCH (d:Deal)-[:IN_DOMAIN]->(dom:Domain)
WHERE d.created_at >= $from_date AND d.created_at <= $to_date
RETURN dom.name AS domain, d.created_at.year AS year, d.created_at.month AS month,
       count(d) AS n
"""


def _window(window_start: date, today: date) -> dict[str, date]:
    return {"window_start": window_start, "today": today}


async def kpis(
    *, today: date, window_start: date, month_first: date, month_last: date
) -> dict[str, Any]:
    params = {**_window(window_start, today), "month_first": month_first, "month_last": month_last}
    return (await run_read(KPIS, params))[0]


async def pipeline_active_reps() -> list[dict[str, Any]]:
    return await run_read(PIPELINE_ACTIVE_REPS)


async def unassigned_open_count() -> int:
    return (await run_read(UNASSIGNED_OPEN))[0]["n"]


async def win_rates_by_rep(*, today: date, window_start: date) -> list[dict[str, Any]]:
    return await run_read(WIN_RATES_BY_REP, _window(window_start, today))


async def win_rates_by_domain(*, today: date, window_start: date) -> list[dict[str, Any]]:
    return await run_read(WIN_RATES_BY_DOMAIN, _window(window_start, today))


async def all_reps() -> list[dict[str, Any]]:
    return await run_read(ALL_REPS)


async def heatmap_cells(*, today: date, window_start: date) -> list[dict[str, Any]]:
    return await run_read(HEATMAP_CELLS, _window(window_start, today))


async def cycle_by_rep(*, today: date, window_start: date) -> list[dict[str, Any]]:
    return await run_read(CYCLE_BY_REP, _window(window_start, today))


async def cycle_by_domain(*, today: date, window_start: date) -> list[dict[str, Any]]:
    return await run_read(CYCLE_BY_DOMAIN, _window(window_start, today))


async def stalled(*, today: date, stalled_days: int) -> list[dict[str, Any]]:
    return await run_read(STALLED, {"today": today, "stalled_days": stalled_days})


async def funnel(*, today: date, window_start: date) -> dict[str, Any]:
    return (await run_read(FUNNEL, _window(window_start, today)))[0]


async def leaderboard(*, period_first: date, period_last: date) -> list[dict[str, Any]]:
    params = {"period_first": period_first, "period_last": period_last}
    return await run_read(LEADERBOARD, params)


async def domain_trend(*, from_date: date, to_date: date) -> list[dict[str, Any]]:
    return await run_read(DOMAIN_TREND, {"from_date": from_date, "to_date": to_date})
