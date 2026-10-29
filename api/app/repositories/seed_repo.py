"""Cypher for wiping the database and bulk-loading the synthetic dataset."""

from __future__ import annotations

from typing import Any

from app.core.db import run_auto_commit, run_read, run_write

BATCH_SIZE = 500

# CALL { ... } IN TRANSACTIONS must run in an auto-commit transaction (tech.md).
WIPE_ALL = """
MATCH (n)
CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 1000 ROWS
"""

LOAD_SALES_PEOPLE = """
UNWIND $rows AS row
MERGE (s:SalesPerson {id: row.id})
SET s.name = row.name,
    s.email = row.email,
    s.region = row.region,
    s.joined_on = row.joined_on,
    s.active = row.active,
    s.capacity = row.capacity
"""

LOAD_CLIENTS = """
UNWIND $rows AS row
MERGE (c:Client {id: row.id})
SET c.name = row.name,
    c.industry = row.industry,
    c.size = row.size,
    c.region = row.region,
    c.created_on = row.created_on
"""

LOAD_DEALS = """
UNWIND $rows AS row
MATCH (c:Client {id: row.client_id})
MATCH (dom:Domain {name: row.domain})
MATCH (s:SalesPerson {id: row.owner_id})
MERGE (d:Deal {id: row.id})
SET d.title = row.title,
    d.value = row.value,
    d.status = row.status,
    d.stage = row.stage,
    d.created_at = row.created_at,
    d.qualified_at = row.qualified_at,
    d.proposal_at = row.proposal_at,
    d.negotiation_at = row.negotiation_at,
    d.expected_close_date = row.expected_close_date,
    d.closed_at = row.closed_at
MERGE (d)-[:FOR_CLIENT]->(c)
MERGE (d)-[:IN_DOMAIN]->(dom)
MERGE (s)-[:OWNS]->(d)
"""

LOAD_ACTIVITIES = """
UNWIND $rows AS row
MATCH (d:Deal {id: row.deal_id})
MATCH (s:SalesPerson {id: row.sales_person_id})
MERGE (a:Activity {id: row.id})
SET a.type = row.type,
    a.date = row.date,
    a.outcome = row.outcome
MERGE (s)-[:PERFORMED]->(a)
MERGE (a)-[:ON_DEAL]->(d)
"""

COUNTS = """
RETURN
  COUNT { (:SalesPerson) } AS SalesPerson,
  COUNT { (:Client) } AS Client,
  COUNT { (:Deal) } AS Deal,
  COUNT { (:Activity) } AS Activity,
  COUNT { (:Domain) } AS Domain,
  COUNT { ()-[:OWNS]->() } AS OWNS,
  COUNT { ()-[:FOR_CLIENT]->() } AS FOR_CLIENT,
  COUNT { ()-[:IN_DOMAIN]->() } AS IN_DOMAIN,
  COUNT { ()-[:PERFORMED]->() } AS PERFORMED,
  COUNT { ()-[:ON_DEAL]->() } AS ON_DEAL
"""


async def wipe_all() -> None:
    """Delete every node and relationship (constraints and indexes are kept)."""
    await run_auto_commit(WIPE_ALL)


async def _load_in_batches(query: str, rows: list[dict[str, Any]]) -> None:
    for start in range(0, len(rows), BATCH_SIZE):
        await run_write(query, {"rows": rows[start : start + BATCH_SIZE]})


async def load_sales_people(rows: list[dict[str, Any]]) -> None:
    await _load_in_batches(LOAD_SALES_PEOPLE, rows)


async def load_clients(rows: list[dict[str, Any]]) -> None:
    await _load_in_batches(LOAD_CLIENTS, rows)


async def load_deals(rows: list[dict[str, Any]]) -> None:
    await _load_in_batches(LOAD_DEALS, rows)


async def load_activities(rows: list[dict[str, Any]]) -> None:
    await _load_in_batches(LOAD_ACTIVITIES, rows)


async def counts() -> dict[str, int]:
    rows = await run_read(COUNTS)
    return rows[0]
