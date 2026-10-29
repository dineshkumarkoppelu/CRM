"""Cypher for clients (including the atomic client + first deal creation)."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.core.db import run_read, run_write

_FIELDS = """
  c.id AS id, c.name AS name, c.industry AS industry, c.size AS size,
  c.region AS region, c.created_on AS created_on
"""

LIST = (
    """
MATCH (c:Client)
WHERE $q IS NULL OR toLower(c.name) CONTAINS toLower($q)
RETURN"""
    + _FIELDS
    + """
ORDER BY c.id
SKIP $offset LIMIT $limit
"""
)

COUNT = """
MATCH (c:Client)
WHERE $q IS NULL OR toLower(c.name) CONTAINS toLower($q)
RETURN count(c) AS total
"""

GET = "MATCH (c:Client {id: $id}) RETURN" + _FIELDS

# One statement = one transaction: the client and its first deal are created together or not
# at all. The Domain is matched FIRST so that nothing is created if it were missing.
CREATE_WITH_DEAL = """
MATCH (dom:Domain {name: $deal.domain})
CREATE (c:Client {
  id: $client.id, name: $client.name, industry: $client.industry,
  size: $client.size, region: $client.region, created_on: $today
})
CREATE (d:Deal {
  id: $deal.id, title: $deal.title, value: $deal.value, status: 'OPEN', stage: 'LEAD',
  created_at: $today, expected_close_date: $deal.expected_close_date
})
CREATE (d)-[:FOR_CLIENT]->(c)
CREATE (d)-[:IN_DOMAIN]->(dom)
WITH c, d
OPTIONAL MATCH (owner:SalesPerson {id: $owner_id})
FOREACH (_ IN CASE WHEN owner IS NULL THEN [] ELSE [1] END | CREATE (owner)-[:OWNS]->(d))
RETURN c.id AS client_id, d.id AS deal_id
"""


async def list_clients(q: str | None, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
    rows = await run_read(LIST, {"q": q, "limit": limit, "offset": offset})
    total = (await run_read(COUNT, {"q": q}))[0]["total"]
    return rows, total


async def get_client(client_id: str) -> dict[str, Any] | None:
    rows = await run_read(GET, {"id": client_id})
    return rows[0] if rows else None


async def create_client_with_deal(
    *,
    client: dict[str, Any],
    deal: dict[str, Any],
    owner_id: str | None,
    today: date,
) -> dict[str, Any]:
    """`client` = {id, name, industry, size, region}; `deal` = {id, title, value, domain,
    expected_close_date}. Returns {client_id, deal_id}."""
    params = {"client": client, "deal": deal, "owner_id": owner_id, "today": today}
    return (await run_write(CREATE_WITH_DEAL, params))[0]
