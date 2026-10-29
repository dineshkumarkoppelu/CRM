"""Cypher for the EXPERTISE_IN and SIMILAR_TO recompute (full rebuilds)."""

from __future__ import annotations

from datetime import date
from typing import Any

from neo4j import AsyncManagedTransaction

from app.core.db import run_in_write_tx, run_read, tx_run

DELETE_EXPERTISE = "MATCH ()-[e:EXPERTISE_IN]->() DELETE e"

# Closed deals in ($window_start, $today], aggregated per (rep, domain).
CREATE_EXPERTISE = """
MATCH (s:SalesPerson)-[:OWNS]->(d:Deal)-[:IN_DOMAIN]->(dom:Domain)
WHERE d.status IN ['WON', 'LOST'] AND d.closed_at > $window_start AND d.closed_at <= $today
WITH s, dom, count(d) AS handled,
     count(CASE WHEN d.status = 'WON' THEN 1 END) AS won,
     max(CASE WHEN d.status = 'WON' THEN d.closed_at END) AS last_won_at
CREATE (s)-[:EXPERTISE_IN {
  handled: handled, won: won, lost: handled - won,
  win_rate: round(toFloat(won) / handled, 4, 'HALF_UP'),
  qualifies: handled >= $min_deals, last_won_at: last_won_at, computed_at: $today
}]->(dom)
RETURN count(*) AS edges
"""

QUALIFYING_EXPERTISE = """
MATCH (s:SalesPerson)-[e:EXPERTISE_IN]->(dom:Domain)
WHERE e.qualifies = true
RETURN s.id AS rep_id, dom.name AS domain, e.win_rate AS win_rate
ORDER BY rep_id, domain
"""

DELETE_SIMILAR = "MATCH ()-[r:SIMILAR_TO]->() DELETE r"

# One edge per unordered pair, from the lower id to the higher id.
CREATE_SIMILAR = """
UNWIND $pairs AS p
MATCH (a:SalesPerson {id: p.rep_a})
MATCH (b:SalesPerson {id: p.rep_b})
CREATE (a)-[:SIMILAR_TO {
  matched_domains: p.matched_domains, match_count: p.match_count,
  mean_abs_diff: p.mean_abs_diff, score: p.score, computed_at: $today
}]->(b)
RETURN count(*) AS pairs
"""

COUNTS = """
RETURN COUNT { (:Deal) } AS deals,
       COUNT { ()-[:EXPERTISE_IN]->() } AS expertise_edges,
       COUNT { ()-[:SIMILAR_TO]->() } AS similar_pairs
"""


async def rebuild_expertise(*, window_start: date, today: date, min_deals: int) -> int:
    """Delete all EXPERTISE_IN and recreate them in ONE transaction. Returns the edge count."""
    params = {"window_start": window_start, "today": today, "min_deals": min_deals}

    async def work(tx: AsyncManagedTransaction) -> int:
        await tx_run(tx, DELETE_EXPERTISE)
        return (await tx_run(tx, CREATE_EXPERTISE, params))[0]["edges"]

    return await run_in_write_tx(work)


async def qualifying_expertise() -> list[dict[str, Any]]:
    return await run_read(QUALIFYING_EXPERTISE)


async def rebuild_similarity(pairs: list[dict[str, Any]], today: date) -> int:
    """Delete all SIMILAR_TO and create the given pairs in ONE transaction."""

    async def work(tx: AsyncManagedTransaction) -> int:
        await tx_run(tx, DELETE_SIMILAR)
        if not pairs:
            return 0
        return (await tx_run(tx, CREATE_SIMILAR, {"pairs": pairs, "today": today}))[0]["pairs"]

    return await run_in_write_tx(work)


async def counts() -> dict[str, int]:
    return (await run_read(COUNTS))[0]
