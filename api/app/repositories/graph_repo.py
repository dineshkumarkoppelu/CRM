"""Cypher for the graph explorer subgraph (Phase 8)."""

from __future__ import annotations

from typing import Any

from app.core.db import run_read

DEAL_CAP = 100

REP = """
MATCH (s:SalesPerson {id: $rep_id})
RETURN s.id AS id, s.name AS name, s.email AS email, s.region AS region,
       s.active AS active, s.capacity AS capacity,
       COUNT { (s)-[:OWNS]->(d:Deal) WHERE d.status = 'OPEN' } AS open_count
"""

# The rep's most recent deals (cap $limit), with their client and domain.
DEALS = """
MATCH (:SalesPerson {id: $rep_id})-[:OWNS]->(d:Deal)
WHERE $status IS NULL OR d.status = $status
WITH d ORDER BY d.created_at DESC, d.id DESC LIMIT $limit
MATCH (d)-[:FOR_CLIENT]->(c:Client)
MATCH (d)-[:IN_DOMAIN]->(dom:Domain)
RETURN d.id AS deal_id, d.title AS title, d.status AS status, d.stage AS stage,
       d.value AS value, d.created_at AS created_at, d.closed_at AS closed_at,
       d.expected_close_date AS expected_close_date,
       c.id AS client_id, c.name AS client_name, c.industry AS industry, c.size AS size,
       dom.name AS domain
ORDER BY created_at DESC, deal_id DESC
"""

EXPERTISE = """
MATCH (:SalesPerson {id: $rep_id})-[e:EXPERTISE_IN]->(dom:Domain)
RETURN dom.name AS domain, e.handled AS handled, e.won AS won, e.win_rate AS win_rate,
       e.qualifies AS qualifies
"""

PEERS = """
MATCH (s:SalesPerson {id: $rep_id})-[r:SIMILAR_TO]-(p:SalesPerson)
RETURN p.id AS id, p.name AS name, p.region AS region, p.active AS active,
       p.capacity AS capacity,
       startNode(r).id AS source, endNode(r).id AS target,
       r.score AS score, r.matched_domains AS matched_domains, r.match_count AS match_count
ORDER BY r.score DESC, p.id
"""


async def get_rep(rep_id: str) -> dict[str, Any] | None:
    rows = await run_read(REP, {"rep_id": rep_id})
    return rows[0] if rows else None


async def rep_deals(rep_id: str, status: str | None, limit: int = DEAL_CAP) -> list[dict[str, Any]]:
    return await run_read(DEALS, {"rep_id": rep_id, "status": status, "limit": limit})


async def rep_expertise(rep_id: str) -> list[dict[str, Any]]:
    return await run_read(EXPERTISE, {"rep_id": rep_id})


async def rep_peers(rep_id: str) -> list[dict[str, Any]]:
    return await run_read(PEERS, {"rep_id": rep_id})
