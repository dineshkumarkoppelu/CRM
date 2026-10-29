"""Cypher for deals (reads always include domain, client and owner; owner may be null)."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.core.db import run_read, run_write

# Every deal read matches the same shape and returns the same columns.
_MATCH_DEAL_SHAPE = """
MATCH (d:Deal)-[:IN_DOMAIN]->(dom:Domain)
MATCH (d)-[:FOR_CLIENT]->(c:Client)
OPTIONAL MATCH (s:SalesPerson)-[:OWNS]->(d)
"""

_RETURN_DEAL = """
RETURN d.id AS id, d.title AS title, d.value AS value, d.status AS status, d.stage AS stage,
       dom.name AS domain, c.id AS client_id, c.name AS client_name,
       s.id AS owner_id, s.name AS owner_name,
       d.created_at AS created_at, d.qualified_at AS qualified_at,
       d.proposal_at AS proposal_at, d.negotiation_at AS negotiation_at,
       d.expected_close_date AS expected_close_date, d.closed_at AS closed_at
"""

# Fixed set of optional predicates; each is a constant guarded by `$param IS NULL OR ...`.
_FILTERS = """
WITH d, dom, c, s
WHERE ($status IS NULL OR d.status = $status)
  AND ($stage IS NULL OR d.stage = $stage)
  AND ($domain IS NULL OR dom.name = $domain)
  AND ($owner_id IS NULL OR s.id = $owner_id)
  AND ($client_id IS NULL OR c.id = $client_id)
  AND ($close_from IS NULL OR d.expected_close_date >= $close_from)
  AND ($close_to IS NULL OR d.expected_close_date <= $close_to)
"""

LIST = (
    _MATCH_DEAL_SHAPE
    + _FILTERS
    + _RETURN_DEAL
    + """
ORDER BY d.created_at DESC, d.id DESC
SKIP $offset LIMIT $limit
"""
)

COUNT = _MATCH_DEAL_SHAPE + _FILTERS + "RETURN count(d) AS total"

GET = (
    """
MATCH (d:Deal {id: $id})-[:IN_DOMAIN]->(dom:Domain)
MATCH (d)-[:FOR_CLIENT]->(c:Client)
OPTIONAL MATCH (s:SalesPerson)-[:OWNS]->(d)
"""
    + _RETURN_DEAL
)

LIST_FOR_CLIENT = (
    """
MATCH (d:Deal)-[:FOR_CLIENT]->(c:Client {id: $client_id})
MATCH (d)-[:IN_DOMAIN]->(dom:Domain)
OPTIONAL MATCH (s:SalesPerson)-[:OWNS]->(d)
"""
    + _RETURN_DEAL
    + "ORDER BY d.created_at DESC, d.id DESC"
)

CREATE_FOR_CLIENT = """
MATCH (c:Client {id: $client_id})
MATCH (dom:Domain {name: $domain})
CREATE (d:Deal {
  id: $id, title: $title, value: $value, status: 'OPEN', stage: 'LEAD',
  created_at: $today, expected_close_date: $expected_close_date
})
CREATE (d)-[:FOR_CLIENT]->(c)
CREATE (d)-[:IN_DOMAIN]->(dom)
WITH d
OPTIONAL MATCH (owner:SalesPerson {id: $owner_id})
FOREACH (_ IN CASE WHEN owner IS NULL THEN [] ELSE [1] END | CREATE (owner)-[:OWNS]->(d))
RETURN d.id AS id
"""

# Optimistic check: only applies if the deal is still in the state the move was computed from.
MOVE_STAGE = """
MATCH (d:Deal {id: $id})
WHERE d.status = $current_status AND d.stage = $current_stage
SET d += $changes
RETURN d.id AS id
"""

UPDATE_OPEN = """
MATCH (d:Deal {id: $id})
WHERE d.status = 'OPEN'
SET d += $changes
RETURN d.id AS id
"""

# RECOMMENDED_TO is written from Phase 6. Until then this returns no rows.
LIST_RECOMMENDATIONS = """
MATCH (d:Deal {id: $id})-[r:RECOMMENDED_TO]->(s:SalesPerson)
RETURN s.id AS sales_person_id, s.name AS name, r.rank AS rank, r.score AS score,
       r.fit AS fit, r.availability AS availability, r.fit_type AS fit_type,
       r.reason AS reason, r.status AS status
ORDER BY r.rank, s.id
"""


def _filter_params(
    status: str | None,
    stage: str | None,
    domain: str | None,
    owner_id: str | None,
    client_id: str | None,
    close_from: date | None,
    close_to: date | None,
) -> dict[str, Any]:
    return {
        "status": status,
        "stage": stage,
        "domain": domain,
        "owner_id": owner_id,
        "client_id": client_id,
        "close_from": close_from,
        "close_to": close_to,
    }


async def list_deals(
    *,
    status: str | None,
    stage: str | None,
    domain: str | None,
    owner_id: str | None,
    client_id: str | None,
    close_from: date | None,
    close_to: date | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    """(page of deals, total matching)."""
    params = _filter_params(status, stage, domain, owner_id, client_id, close_from, close_to)
    rows = await run_read(LIST, {**params, "limit": limit, "offset": offset})
    total = (await run_read(COUNT, params))[0]["total"]
    return rows, total


async def get_deal(deal_id: str) -> dict[str, Any] | None:
    rows = await run_read(GET, {"id": deal_id})
    return rows[0] if rows else None


async def list_deals_for_client(client_id: str) -> list[dict[str, Any]]:
    return await run_read(LIST_FOR_CLIENT, {"client_id": client_id})


async def create_deal_for_client(
    *,
    deal_id: str,
    client_id: str,
    title: str,
    value: int,
    domain: str,
    expected_close_date: date,
    owner_id: str | None,
    today: date,
) -> bool:
    """Create an OPEN/LEAD deal on an existing client (+ OWNS if owner_id). False if no client."""
    params = {
        "id": deal_id,
        "client_id": client_id,
        "title": title,
        "value": value,
        "domain": domain,
        "expected_close_date": expected_close_date,
        "owner_id": owner_id,
        "today": today,
    }
    return bool(await run_write(CREATE_FOR_CLIENT, params))


async def move_stage(
    deal_id: str, current_status: str, current_stage: str, changes: dict[str, Any]
) -> bool:
    """Apply a stage move. False if the deal changed in the meantime."""
    params = {
        "id": deal_id,
        "current_status": current_status,
        "current_stage": current_stage,
        "changes": changes,
    }
    return bool(await run_write(MOVE_STAGE, params))


async def update_open_deal(deal_id: str, changes: dict[str, Any]) -> bool:
    return bool(await run_write(UPDATE_OPEN, {"id": deal_id, "changes": changes}))


async def list_recommendations(deal_id: str) -> list[dict[str, Any]]:
    return await run_read(LIST_RECOMMENDATIONS, {"id": deal_id})
