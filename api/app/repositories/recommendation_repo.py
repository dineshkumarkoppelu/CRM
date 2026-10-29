"""Cypher for the assignment engine: ranking inputs and RECOMMENDED_TO / OWNS writes."""

from __future__ import annotations

from datetime import date
from typing import Any

from neo4j import AsyncManagedTransaction

from app.core.db import run_in_write_tx, run_read, tx_run

REPS_STATE = """
MATCH (s:SalesPerson)
RETURN s.id AS id, s.name AS name, s.active AS active, s.capacity AS capacity,
       COUNT { (s)-[:OWNS]->(d:Deal) WHERE d.status = 'OPEN' } AS open_count
ORDER BY id
"""

ALL_EXPERTISE = """
MATCH (s:SalesPerson)-[e:EXPERTISE_IN]->(dom:Domain)
RETURN s.id AS rep_id, dom.name AS domain, e.handled AS handled, e.won AS won,
       e.win_rate AS win_rate, e.qualifies AS qualifies
"""

# Stored lower id -> higher id; returned as such (the service treats it as undirected).
ALL_SIMILAR = """
MATCH (a:SalesPerson)-[r:SIMILAR_TO]->(b:SalesPerson)
RETURN a.id AS rep_a, b.id AS rep_b, r.score AS score, r.matched_domains AS matched_domains
"""

DELETE_RECOMMENDATIONS = """
MATCH (:Deal {id: $deal_id})-[r:RECOMMENDED_TO]->(:SalesPerson)
DELETE r
"""

CREATE_RECOMMENDATIONS = """
MATCH (d:Deal {id: $deal_id})
UNWIND $recs AS c
MATCH (s:SalesPerson {id: c.sales_person_id})
CREATE (d)-[:RECOMMENDED_TO {
  rank: c.rank, score: c.score, fit: c.fit, availability: c.availability,
  fit_type: c.fit_type, reason: c.reason, status: c.status, created_at: $today
}]->(s)
RETURN count(*) AS n
"""

# Guarded: only an OPEN deal that still has no owner gets one.
ASSIGN_OWNER = """
MATCH (d:Deal {id: $deal_id})
WHERE d.status = 'OPEN' AND NOT EXISTS { (:SalesPerson)-[:OWNS]->(d) }
MATCH (s:SalesPerson {id: $rep_id})
CREATE (s)-[:OWNS]->(d)
RETURN count(*) AS n
"""

REMOVE_OWNER = """
MATCH (:SalesPerson)-[o:OWNS]->(:Deal {id: $deal_id})
DELETE o
"""

SET_OWNER_IF_OPEN = """
MATCH (d:Deal {id: $deal_id})
WHERE d.status = 'OPEN'
MATCH (s:SalesPerson {id: $rep_id})
CREATE (s)-[:OWNS]->(d)
RETURN count(*) AS n
"""

MARK_OVERRIDDEN = """
MATCH (:Deal {id: $deal_id})-[r:RECOMMENDED_TO]->(s:SalesPerson)
WHERE r.status = 'ASSIGNED' AND s.id <> $rep_id
SET r.status = 'OVERRIDDEN'
"""

SET_EXISTING_ASSIGNED = """
MATCH (:Deal {id: $deal_id})-[r:RECOMMENDED_TO]->(:SalesPerson {id: $rep_id})
SET r.status = 'ASSIGNED'
RETURN count(r) AS n
"""

COUNT_RECOMMENDATIONS = "RETURN COUNT { ()-[:RECOMMENDED_TO]->() } AS n"


class OwnerConflict(Exception):
    """The deal got an owner (or was closed) between ranking and writing."""


async def reps_state() -> list[dict[str, Any]]:
    return await run_read(REPS_STATE)


async def all_expertise() -> list[dict[str, Any]]:
    return await run_read(ALL_EXPERTISE)


async def all_similar_pairs() -> list[dict[str, Any]]:
    return await run_read(ALL_SIMILAR)


async def replace_recommendations(
    deal_id: str, recs: list[dict[str, Any]], owner_id: str | None, today: date
) -> None:
    """ONE transaction: clear the deal's RECOMMENDED_TO, write `recs`, and (if `owner_id`)
    create OWNS. Raises OwnerConflict (rolling everything back) if the deal is no longer an
    OPEN deal without an owner."""

    async def work(tx: AsyncManagedTransaction) -> None:
        await tx_run(tx, DELETE_RECOMMENDATIONS, {"deal_id": deal_id})
        if recs:
            await tx_run(
                tx, CREATE_RECOMMENDATIONS, {"deal_id": deal_id, "recs": recs, "today": today}
            )
        if owner_id is not None:
            rows = await tx_run(tx, ASSIGN_OWNER, {"deal_id": deal_id, "rep_id": owner_id})
            if rows[0]["n"] != 1:
                raise OwnerConflict(deal_id)

    await run_in_write_tx(work)


async def override_owner(deal_id: str, rep_id: str, new_rec: dict[str, Any], today: date) -> None:
    """ONE transaction: move OWNS to `rep_id`, mark the old ASSIGNED recommendation OVERRIDDEN,
    set the target's recommendation to ASSIGNED or create `new_rec` (rank 0) if it has none."""
    params = {"deal_id": deal_id, "rep_id": rep_id}

    async def work(tx: AsyncManagedTransaction) -> None:
        await tx_run(tx, REMOVE_OWNER, params)
        if (await tx_run(tx, SET_OWNER_IF_OPEN, params))[0]["n"] != 1:
            raise OwnerConflict(deal_id)
        await tx_run(tx, MARK_OVERRIDDEN, params)
        if (await tx_run(tx, SET_EXISTING_ASSIGNED, params))[0]["n"] == 0:
            await tx_run(
                tx, CREATE_RECOMMENDATIONS, {"deal_id": deal_id, "recs": [new_rec], "today": today}
            )

    await run_in_write_tx(work)


async def count_recommendations() -> int:
    return (await run_read(COUNT_RECOMMENDATIONS))[0]["n"]
