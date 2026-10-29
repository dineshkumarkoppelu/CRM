"""Cypher for activities."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.core.db import run_read, run_write

_RETURN_ACTIVITY = """
RETURN a.id AS id, a.type AS type, a.date AS date, a.outcome AS outcome,
       d.id AS deal_id, s.id AS sales_person_id, s.name AS sales_person_name
"""

CREATE = (
    """
MATCH (d:Deal {id: $deal_id})
MATCH (s:SalesPerson {id: $sales_person_id})
CREATE (a:Activity {id: $id, type: $type, date: $date, outcome: $outcome})
CREATE (s)-[:PERFORMED]->(a)
CREATE (a)-[:ON_DEAL]->(d)
"""
    + _RETURN_ACTIVITY
)

LIST_FOR_DEAL = (
    """
MATCH (a:Activity)-[:ON_DEAL]->(d:Deal {id: $deal_id})
MATCH (s:SalesPerson)-[:PERFORMED]->(a)
"""
    + _RETURN_ACTIVITY
    + "ORDER BY a.date DESC, a.id DESC"
)


async def create_activity(
    *,
    activity_id: str,
    deal_id: str,
    sales_person_id: str,
    activity_type: str,
    activity_date: date,
    outcome: str,
) -> dict[str, Any] | None:
    params = {
        "id": activity_id,
        "deal_id": deal_id,
        "sales_person_id": sales_person_id,
        "type": activity_type,
        "date": activity_date,
        "outcome": outcome,
    }
    rows = await run_write(CREATE, params)
    return rows[0] if rows else None


async def list_for_deal(deal_id: str) -> list[dict[str, Any]]:
    """Newest first."""
    return await run_read(LIST_FOR_DEAL, {"deal_id": deal_id})
