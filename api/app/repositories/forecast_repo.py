"""Cypher for the forecast and back-test (Phase 5). Flat rows only; all math is in the service.

All dates arrive as parameters. Closed-deal history uses closed_at in
($window_start, $window_end_exclusive): the service passes today + 1 day for the current
forecast (window ends at today, inclusive) and `asof` for the back-test (strictly before asof).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.core.db import run_read

# Grouped in the database (Phase 9: returning ~430 dated rows cost ~0.5 s of driver decoding).
# One row per (owner, domain, status, stages reached) with the number of deals `n`. A stage
# field is `true` when the stage was reached and null otherwise, which is all the probability
# table needs.
CLOSED_HISTORY = """
MATCH (d:Deal)-[:IN_DOMAIN]->(dom:Domain)
WHERE d.status IN ['WON', 'LOST']
  AND d.closed_at > $window_start AND d.closed_at < $window_end_exclusive
OPTIONAL MATCH (s:SalesPerson)-[:OWNS]->(d)
WITH s.id AS owner_id, dom.name AS domain, d.status AS status,
     CASE WHEN d.qualified_at IS NULL THEN null ELSE true END AS qualified_at,
     CASE WHEN d.proposal_at IS NULL THEN null ELSE true END AS proposal_at,
     CASE WHEN d.negotiation_at IS NULL THEN null ELSE true END AS negotiation_at
RETURN owner_id, domain, status, qualified_at, proposal_at, negotiation_at, count(*) AS n
"""

IN_SCOPE_OPEN = """
MATCH (s:SalesPerson)-[:OWNS]->(d:Deal)-[:IN_DOMAIN]->(dom:Domain)
WHERE d.status = 'OPEN'
  AND d.expected_close_date >= $month_first AND d.expected_close_date <= $month_last
MATCH (d)-[:FOR_CLIENT]->(c:Client)
RETURN d.id AS deal_id, s.id AS owner_id, s.name AS owner_name, c.id AS client_id,
       c.name AS client_name, dom.name AS domain, d.stage AS stage, d.value AS value,
       d.expected_close_date AS expected_close_date
ORDER BY deal_id
"""

# Pipeline as it stood on $asof (stage is derived in the service from the stage dates).
BACKTEST_PIPELINE = """
MATCH (s:SalesPerson)-[:OWNS]->(d:Deal)-[:IN_DOMAIN]->(dom:Domain)
WHERE d.created_at <= $asof
  AND (d.closed_at IS NULL OR d.closed_at >= $asof)
  AND d.expected_close_date >= $month_first AND d.expected_close_date <= $month_last
MATCH (d)-[:FOR_CLIENT]->(c:Client)
RETURN d.id AS deal_id, s.id AS owner_id, s.name AS owner_name, c.id AS client_id,
       c.name AS client_name, dom.name AS domain, d.value AS value,
       d.created_at AS created_at, d.qualified_at AS qualified_at,
       d.proposal_at AS proposal_at, d.negotiation_at AS negotiation_at
ORDER BY deal_id
"""

CONVERSIONS_BY_REP = """
MATCH (s:SalesPerson)-[:OWNS]->(d:Deal)-[:FOR_CLIENT]->(c:Client)
WHERE d.status = 'WON' AND d.closed_at >= $from_date AND d.closed_at <= $to_date
RETURN s.id AS sales_person_id, count(DISTINCT c) AS clients
"""

CONVERSIONS_TEAM = """
MATCH (d:Deal)-[:FOR_CLIENT]->(c:Client)
WHERE d.status = 'WON' AND d.closed_at >= $from_date AND d.closed_at <= $to_date
RETURN count(DISTINCT c) AS clients
"""

ACTIVE_REPS = """
MATCH (s:SalesPerson)
WHERE s.active = true
RETURN s.id AS id, s.name AS name
ORDER BY id
"""


async def closed_history(*, window_start: date, window_end_exclusive: date) -> list[dict[str, Any]]:
    params = {"window_start": window_start, "window_end_exclusive": window_end_exclusive}
    return await run_read(CLOSED_HISTORY, params)


async def in_scope_open(*, month_first: date, month_last: date) -> list[dict[str, Any]]:
    return await run_read(IN_SCOPE_OPEN, {"month_first": month_first, "month_last": month_last})


async def backtest_pipeline(
    *, asof: date, month_first: date, month_last: date
) -> list[dict[str, Any]]:
    params = {"asof": asof, "month_first": month_first, "month_last": month_last}
    return await run_read(BACKTEST_PIPELINE, params)


async def conversions(*, from_date: date, to_date: date) -> tuple[dict[str, int], int]:
    """({rep_id: distinct clients converted}, team distinct clients) for WON in the range."""
    params = {"from_date": from_date, "to_date": to_date}
    by_rep = {
        r["sales_person_id"]: r["clients"] for r in await run_read(CONVERSIONS_BY_REP, params)
    }
    team = (await run_read(CONVERSIONS_TEAM, params))[0]["clients"]
    return by_rep, team


async def active_reps() -> list[dict[str, Any]]:
    return await run_read(ACTIVE_REPS)
