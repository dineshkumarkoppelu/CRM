"""UI writes in data-source mode: Postgres first, then the same upsert the sync uses.

Each function writes through the source API (so the row exists in Postgres, the source of
truth) and then calls `apply_row`, which mirrors it into Neo4j straight away. The
`crm_changes` notification that follows is applied again, harmlessly (it is idempotent).
Return values match the Neo4j repositories these replace.
"""

from __future__ import annotations

import contextlib
from datetime import date
from enum import Enum
from typing import Any

from app.core.errors import AppError
from app.repositories import salespeople_repo
from app.repositories.recommendation_repo import OwnerConflict
from app.sync import source_client
from app.sync.service import apply_row, normalize


def _json(values: dict[str, Any]) -> dict[str, Any]:
    """JSON-ready body: dates as ISO strings, enums as their values."""
    out: dict[str, Any] = {}
    for key, value in values.items():
        if isinstance(value, Enum):
            value = value.value
        out[key] = value.isoformat() if isinstance(value, date) else value
    return out


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
    body = {
        "id": rep_id,
        "name": name,
        "email": email,
        "region": region,
        "joined_on": joined_on,
        "active": active,
        "capacity": capacity,
    }
    row = await source_client.create("sales_people", _json(body))
    await apply_row("sales_people", rep_id, "INSERT")
    return normalize("sales_people", row)


async def update_sales_person(rep_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
    try:
        row = await source_client.patch("sales_people", rep_id, _json(changes))
    except AppError as exc:
        if exc.status == 404:
            return None
        raise
    await apply_row("sales_people", rep_id, "UPDATE")
    return normalize("sales_people", row)


async def create_client_with_deal(
    *, client: dict[str, Any], deal: dict[str, Any], owner_id: str | None, today: date
) -> dict[str, Any]:
    """Two inserts (Postgres has no cross-table call): if the deal fails the client is removed."""
    await source_client.create("clients", _json({**client, "created_on": today}))
    try:
        await source_client.create(
            "deals",
            _json(
                {
                    **deal,
                    "status": "OPEN",
                    "stage": "LEAD",
                    "created_at": today,
                    "client_id": client["id"],
                    "owner_id": owner_id,
                }
            ),
        )
    except Exception:
        with contextlib.suppress(Exception):
            await source_client.delete("clients", client["id"])
        raise
    await apply_row("clients", client["id"], "INSERT")
    await apply_row("deals", deal["id"], "INSERT")
    return {"client_id": client["id"], "deal_id": deal["id"]}


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
    """False if the client is gone (the source answers 409, foreign key)."""
    body = {
        "id": deal_id,
        "title": title,
        "value": value,
        "status": "OPEN",
        "stage": "LEAD",
        "created_at": today,
        "expected_close_date": expected_close_date,
        "domain": domain,
        "client_id": client_id,
        "owner_id": owner_id,
    }
    try:
        await source_client.create("deals", _json(body))
    except AppError as exc:
        if exc.status == 409:
            return False
        raise
    await apply_row("deals", deal_id, "INSERT")
    return True


async def move_stage(
    deal_id: str, current_status: str, current_stage: str, changes: dict[str, Any]
) -> bool:
    """Apply a stage move. False if the deal changed in the meantime."""
    row = await source_client.get("deals", deal_id)
    if row is None or row["status"] != current_status or row["stage"] != current_stage:
        return False
    await source_client.patch("deals", deal_id, _json(changes))
    await apply_row("deals", deal_id, "UPDATE")
    return True


async def update_open_deal(deal_id: str, changes: dict[str, Any]) -> bool:
    row = await source_client.get("deals", deal_id)
    if row is None or row["status"] != "OPEN":
        return False
    await source_client.patch("deals", deal_id, _json(changes))
    await apply_row("deals", deal_id, "UPDATE")
    return True


async def set_owner(deal_id: str, rep_id: str, *, expect_unassigned: bool) -> None:
    """Write the deal's owner to the source. OwnerConflict if the deal is no longer OPEN (or,
    when `expect_unassigned`, already has an owner) - same contract as the Neo4j version."""
    row = await source_client.get("deals", deal_id)
    if row is None or row["status"] != "OPEN" or (expect_unassigned and row["owner_id"]):
        raise OwnerConflict(deal_id)
    await source_client.patch("deals", deal_id, {"owner_id": rep_id})
    await apply_row("deals", deal_id, "UPDATE")


async def create_activity(
    *,
    activity_id: str,
    deal_id: str,
    sales_person_id: str,
    activity_type: str,
    activity_date: date,
    outcome: str,
) -> dict[str, Any] | None:
    body = {
        "id": activity_id,
        "type": activity_type,
        "date": activity_date,
        "outcome": outcome,
        "deal_id": deal_id,
        "sales_person_id": sales_person_id,
    }
    try:
        await source_client.create("activities", _json(body))
    except AppError as exc:
        if exc.status == 409:
            return None
        raise
    if not (await apply_row("activities", activity_id, "INSERT")).startswith("upserted"):
        return None
    rep = await salespeople_repo.get_sales_person(sales_person_id)
    return {
        "id": activity_id,
        "type": activity_type,
        "date": activity_date,
        "outcome": outcome,
        "deal_id": deal_id,
        "sales_person_id": sales_person_id,
        "sales_person_name": rep["name"] if rep else sales_person_id,
    }
