"""Cypher for sales people."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.core.db import run_read, run_write

_FIELDS = """
  s.id AS id, s.name AS name, s.email AS email, s.region AS region,
  s.joined_on AS joined_on, s.active AS active, s.capacity AS capacity
"""

LIST = (
    """
MATCH (s:SalesPerson)
WHERE $active IS NULL OR s.active = $active
RETURN"""
    + _FIELDS
    + """
ORDER BY s.id
SKIP $offset LIMIT $limit
"""
)

COUNT = """
MATCH (s:SalesPerson)
WHERE $active IS NULL OR s.active = $active
RETURN count(s) AS total
"""

GET_WITH_OPEN_COUNT = (
    """
MATCH (s:SalesPerson {id: $id})
RETURN"""
    + _FIELDS
    + """,
  COUNT { (s)-[:OWNS]->(d:Deal) WHERE d.status = 'OPEN' } AS open_count
"""
)

# Derived edges (written from Phase 6). Until then these simply return no rows.
LIST_EXPERTISE = """
MATCH (s:SalesPerson {id: $id})-[e:EXPERTISE_IN]->(dom:Domain)
RETURN dom.name AS domain, e.handled AS handled, e.won AS won, e.lost AS lost,
       e.win_rate AS win_rate, e.qualifies AS qualifies, e.last_won_at AS last_won_at
"""

LIST_SIMILAR_PEERS = """
MATCH (s:SalesPerson {id: $id})-[r:SIMILAR_TO]-(p:SalesPerson)
RETURN p.id AS id, p.name AS name, r.matched_domains AS matched_domains,
       r.match_count AS match_count, r.mean_abs_diff AS mean_abs_diff, r.score AS score
ORDER BY r.score DESC, p.id
"""

CREATE = (
    """
CREATE (s:SalesPerson {
  id: $id, name: $name, email: $email, region: $region,
  joined_on: $joined_on, active: $active, capacity: $capacity
})
RETURN"""
    + _FIELDS
)

UPDATE = (
    """
MATCH (s:SalesPerson {id: $id})
SET s += $changes
RETURN"""
    + _FIELDS
)


async def list_sales_people(active: bool | None, limit: int, offset: int) -> list[dict[str, Any]]:
    return await run_read(LIST, {"active": active, "limit": limit, "offset": offset})


async def count_sales_people(active: bool | None) -> int:
    return (await run_read(COUNT, {"active": active}))[0]["total"]


async def get_sales_person(rep_id: str) -> dict[str, Any] | None:
    """The rep plus `open_count`, or None if not found."""
    rows = await run_read(GET_WITH_OPEN_COUNT, {"id": rep_id})
    return rows[0] if rows else None


async def list_expertise(rep_id: str) -> list[dict[str, Any]]:
    return await run_read(LIST_EXPERTISE, {"id": rep_id})


async def list_similar_peers(rep_id: str) -> list[dict[str, Any]]:
    return await run_read(LIST_SIMILAR_PEERS, {"id": rep_id})


async def create_sales_person(
    *,
    rep_id: str,
    name: str,
    email: str,
    region: str,
    joined_on: date,
    active: bool,
    capacity: int,
) -> dict[str, Any]:
    params = {
        "id": rep_id,
        "name": name,
        "email": email,
        "region": region,
        "joined_on": joined_on,
        "active": active,
        "capacity": capacity,
    }
    return (await run_write(CREATE, params))[0]


async def update_sales_person(rep_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
    rows = await run_write(UPDATE, {"id": rep_id, "changes": changes})
    return rows[0] if rows else None
