"""Override of an assignment (FRESH seed per test, AS_OF_DATE=2026-10-06)."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from app.core.db import run_read
from app.seed.generator import SeedDataset
from tests.conftest import seed_test_db
from tests.integration.helpers import (
    assert_error,
    assert_invariants_hold,
    new_client_body,
    owner_ids_of,
)


@pytest.fixture(autouse=True)
async def fresh(api_app: FastAPI) -> None:
    await seed_test_db(api_app)


async def _peer_deal(client: httpx.AsyncClient) -> str:
    """The PEER-scenario deal (IoT, assigned to SP-002)."""
    body = (await client.post("/api/clients", json=new_client_body())).json()
    assert body["assignment"]["assigned_to"]["id"] == "SP-002"
    return body["deal"]["id"]


async def _override(client: httpx.AsyncClient, deal_id: str, rep_id: str) -> httpx.Response:
    return await client.post(
        f"/api/recommendations/{deal_id}/override", json={"sales_person_id": rep_id}
    )


async def _statuses(deal_id: str) -> dict[str, str]:
    rows = await run_read(
        "MATCH (:Deal {id: $id})-[r:RECOMMENDED_TO]->(s) RETURN s.id AS id, r.status AS status",
        {"id": deal_id},
    )
    return {r["id"]: r["status"] for r in rows}


async def test_override_to_existing_candidate(client: httpx.AsyncClient) -> None:
    deal_id = await _peer_deal(client)
    response = await _override(client, deal_id, "SP-014")  # rank 2 in the PEER scenario
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["assignment_status"] == "ASSIGNED"
    assert result["assigned_to"] == {"id": "SP-014", "name": "Sana Sheikh"}
    assert await owner_ids_of(deal_id) == ["SP-014"]
    statuses = await _statuses(deal_id)
    assert statuses["SP-002"] == "OVERRIDDEN" and statuses["SP-014"] == "ASSIGNED"
    assert list(statuses.values()).count("ASSIGNED") == 1
    assert len(statuses) == 5  # no new edge: SP-014 already had one


async def test_override_to_a_rep_without_a_recommendation(client: httpx.AsyncClient) -> None:
    deal_id = await _peer_deal(client)
    result = (await _override(client, deal_id, "SP-004")).json()  # not in the top 5
    assert await owner_ids_of(deal_id) == ["SP-004"]
    added = next(c for c in result["candidates"] if c["sales_person_id"] == "SP-004")
    assert added["rank"] == 0 and added["status"] == "ASSIGNED"
    assert added["reason"].startswith("Manual override: ")
    assert added["fit_type"] in {"DIRECT", "PEER", "RELATED", "COLD_START"}
    assert len(result["candidates"]) == 6


async def test_override_to_at_capacity_rep_is_rejected(client: httpx.AsyncClient) -> None:
    deal_id = await _peer_deal(client)
    error = assert_error(await _override(client, deal_id, "SP-001"), 409, "REP_NOT_AVAILABLE")
    assert error["details"]["reason"] == "AT_CAPACITY"
    assert await owner_ids_of(deal_id) == ["SP-002"]  # unchanged


async def test_override_to_inactive_rep_is_rejected(client: httpx.AsyncClient) -> None:
    deal_id = await _peer_deal(client)
    await client.patch("/api/salespeople/SP-014", json={"active": False})
    assert_error(await _override(client, deal_id, "SP-014"), 409, "REP_NOT_AVAILABLE")


async def test_override_closed_deal_is_rejected(
    client: httpx.AsyncClient, dataset: SeedDataset
) -> None:
    won = next(d for d in dataset.deals if d["status"] == "WON")
    assert_error(await _override(client, won["id"], "SP-014"), 400, "DEAL_CLOSED")


async def test_override_errors(client: httpx.AsyncClient) -> None:
    deal_id = await _peer_deal(client)
    assert_error(await _override(client, deal_id, "SP-999"), 404, "REP_NOT_FOUND")
    assert_error(await _override(client, "DL-9999", "SP-014"), 404, "DEAL_NOT_FOUND")
    response = await client.post(f"/api/recommendations/{deal_id}/override", json={})
    assert_error(response, 422, "VALIDATION_ERROR")


async def test_override_to_current_owner_is_a_no_op(client: httpx.AsyncClient) -> None:
    deal_id = await _peer_deal(client)
    before = await _statuses(deal_id)
    result = (await _override(client, deal_id, "SP-002")).json()
    assert result["message"] == "Already assigned to Bhavna Rao"
    assert await _statuses(deal_id) == before


async def test_override_back_and_forth_and_invariants(client: httpx.AsyncClient) -> None:
    deal_id = await _peer_deal(client)
    await _override(client, deal_id, "SP-014")
    await _override(client, deal_id, "SP-002")
    statuses = await _statuses(deal_id)
    assert statuses["SP-002"] == "ASSIGNED" and statuses["SP-014"] == "OVERRIDDEN"
    assert await owner_ids_of(deal_id) == ["SP-002"]
    await assert_invariants_hold()
