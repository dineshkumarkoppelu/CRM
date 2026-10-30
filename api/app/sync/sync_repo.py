"""Cypher that projects the Postgres rows into Neo4j (idempotent upserts, diff-style edges).

Every upsert takes a list of rows and is safe to repeat: nodes are MERGEd by id, and an edge
is only deleted when it no longer matches the row (so re-applying an unchanged row writes
nothing). Callers pass rows whose parents (client, domain) are already checked.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from neo4j import AsyncManagedTransaction

from app.core.db import run_auto_commit, run_in_write_tx, run_read, run_write, tx_run

BATCH_SIZE = 500

TABLE_LABEL: dict[str, str] = {
    "sales_people": "SalesPerson",
    "clients": "Client",
    "deals": "Deal",
    "activities": "Activity",
}

UPSERT_SALES_PEOPLE = """
UNWIND $rows AS row
MERGE (s:SalesPerson {id: row.id})
SET s.name = row.name,
    s.email = row.email,
    s.region = row.region,
    s.joined_on = row.joined_on,
    s.active = row.active,
    s.capacity = row.capacity
"""

UPSERT_CLIENTS = """
UNWIND $rows AS row
MERGE (c:Client {id: row.id})
SET c.name = row.name,
    c.industry = row.industry,
    c.size = row.size,
    c.region = row.region,
    c.created_on = row.created_on
"""

# Drop only the edges that no longer match the row (client, domain or owner changed).
DROP_STALE_DEAL_EDGES = """
UNWIND $rows AS row
MATCH (d:Deal {id: row.id})
OPTIONAL MATCH (d)-[r1:FOR_CLIENT]->(c:Client) WHERE c.id <> row.client_id
DELETE r1
WITH d, row
OPTIONAL MATCH (d)-[r2:IN_DOMAIN]->(dom:Domain) WHERE dom.name <> row.domain
DELETE r2
WITH d, row
OPTIONAL MATCH (s:SalesPerson)-[r3:OWNS]->(d) WHERE row.owner_id IS NULL OR s.id <> row.owner_id
DELETE r3
"""

UPSERT_DEALS = """
UNWIND $rows AS row
MATCH (c:Client {id: row.client_id})
MATCH (dom:Domain {name: row.domain})
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
"""

# A deal without an owner (or with an owner that does not exist) simply gets no OWNS edge:
# the app already shows such a deal as "Unassigned".
UPSERT_OWNERS = """
UNWIND $rows AS row
MATCH (d:Deal {id: row.id})
MATCH (s:SalesPerson {id: row.owner_id})
MERGE (s)-[:OWNS]->(d)
"""

DROP_STALE_ACTIVITY_EDGES = """
UNWIND $rows AS row
MATCH (a:Activity {id: row.id})
OPTIONAL MATCH (a)-[r1:ON_DEAL]->(d:Deal) WHERE d.id <> row.deal_id
DELETE r1
WITH a, row
OPTIONAL MATCH (s:SalesPerson)-[r2:PERFORMED]->(a) WHERE s.id <> row.sales_person_id
DELETE r2
"""

UPSERT_ACTIVITIES = """
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

# A deleted deal takes its activities with it (the source keeps no foreign key on them).
DELETE_DEALS = """
MATCH (d:Deal) WHERE d.id IN $ids
OPTIONAL MATCH (a:Activity)-[:ON_DEAL]->(d)
DETACH DELETE a, d
"""

DELETE_BY_LABEL = {
    "SalesPerson": "MATCH (n:SalesPerson) WHERE n.id IN $ids DETACH DELETE n",
    "Client": "MATCH (n:Client) WHERE n.id IN $ids DETACH DELETE n",
    "Activity": "MATCH (n:Activity) WHERE n.id IN $ids DETACH DELETE n",
}

IDS_BY_LABEL = {
    "SalesPerson": "MATCH (n:SalesPerson) RETURN n.id AS id",
    "Client": "MATCH (n:Client) RETURN n.id AS id",
    "Deal": "MATCH (n:Deal) RETURN n.id AS id",
    "Activity": "MATCH (n:Activity) RETURN n.id AS id",
}

DOMAIN_NAMES = "MATCH (d:Domain) RETURN d.name AS name"

# CALL { ... } IN TRANSACTIONS must run in an auto-commit transaction.
WIPE_ENTITIES = """
MATCH (n) WHERE n:SalesPerson OR n:Client OR n:Deal OR n:Activity
CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 1000 ROWS
"""

GET_MARKER = "MATCH (m:SyncState {name: 'crm-source'}) RETURN m.adopted_at AS adopted_at"
SET_MARKER = "MERGE (m:SyncState {name: 'crm-source'}) SET m.adopted_at = $now"
ENTITY_COUNT = (
    "RETURN COUNT { (:SalesPerson) } + COUNT { (:Client) } + COUNT { (:Deal) }"
    " + COUNT { (:Activity) } AS n"
)


def _chunks(rows: Sequence[dict[str, Any]]) -> list[Sequence[dict[str, Any]]]:
    return [rows[i : i + BATCH_SIZE] for i in range(0, len(rows), BATCH_SIZE)]


async def existing_ids(label: str) -> set[str]:
    return {r["id"] for r in await run_read(IDS_BY_LABEL[label])}


async def domain_names() -> list[str]:
    return [r["name"] for r in await run_read(DOMAIN_NAMES)]


async def upsert_sales_people(rows: Sequence[dict[str, Any]]) -> None:
    for chunk in _chunks(rows):
        await run_write(UPSERT_SALES_PEOPLE, {"rows": chunk})


async def upsert_clients(rows: Sequence[dict[str, Any]]) -> None:
    for chunk in _chunks(rows):
        await run_write(UPSERT_CLIENTS, {"rows": chunk})


async def upsert_deals(rows: Sequence[dict[str, Any]]) -> None:
    """`rows` have `domain` already canonical and an existing client."""
    for chunk in _chunks(rows):
        owned = [r for r in chunk if r.get("owner_id")]

        async def work(tx: AsyncManagedTransaction, chunk=chunk, owned=owned) -> None:
            await tx_run(tx, DROP_STALE_DEAL_EDGES, {"rows": chunk})
            await tx_run(tx, UPSERT_DEALS, {"rows": chunk})
            if owned:
                await tx_run(tx, UPSERT_OWNERS, {"rows": owned})

        await run_in_write_tx(work)


async def upsert_activities(rows: Sequence[dict[str, Any]]) -> None:
    """`rows` have an existing deal and sales person."""
    for chunk in _chunks(rows):

        async def work(tx: AsyncManagedTransaction, chunk=chunk) -> None:
            await tx_run(tx, DROP_STALE_ACTIVITY_EDGES, {"rows": chunk})
            await tx_run(tx, UPSERT_ACTIVITIES, {"rows": chunk})

        await run_in_write_tx(work)


async def delete_ids(label: str, ids: Sequence[str]) -> None:
    for start in range(0, len(ids), BATCH_SIZE):
        batch = list(ids[start : start + BATCH_SIZE])
        query = DELETE_DEALS if label == "Deal" else DELETE_BY_LABEL[label]
        await run_write(query, {"ids": batch})


async def wipe_entities() -> None:
    """Delete every SalesPerson / Client / Deal / Activity (Domain nodes and schema stay)."""
    await run_auto_commit(WIPE_ENTITIES)


async def entity_count() -> int:
    return (await run_read(ENTITY_COUNT))[0]["n"]


async def get_marker() -> Any:
    rows = await run_read(GET_MARKER)
    return rows[0]["adopted_at"] if rows else None


async def set_marker(now: datetime) -> None:
    await run_write(SET_MARKER, {"now": now.isoformat()})


async def exists(label: str, node_id: str) -> bool:
    rows = await run_read(f"MATCH (n:{label} {{id: $id}}) RETURN count(n) AS n", {"id": node_id})
    return rows[0]["n"] > 0
