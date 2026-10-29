"""Integration tests for /api/clients (fresh seed for this module)."""

from __future__ import annotations

import re
from collections import Counter

import httpx
import pytest

from app.seed.generator import SeedDataset
from app.services import crud_service
from tests.integration.helpers import (
    DEAL_FIELDS,
    TODAY_ISO,
    assert_error,
    assert_invariants_hold,
    new_client_body,
    owner_ids_of,
)

pytestmark = pytest.mark.usefixtures("seeded")

CLIENT_FIELDS = {"id", "name", "industry", "size", "region", "created_on"}


# ---------------------------------------------------------------- reads


async def test_list_and_paginate(client: httpx.AsyncClient, dataset: SeedDataset) -> None:
    body = (await client.get("/api/clients", params={"limit": 10})).json()
    assert body["total"] == len(dataset.clients)
    assert 320 <= body["total"] <= 400
    assert [c["id"] for c in body["items"]] == [f"CL-{i:04d}" for i in range(1, 11)]
    assert set(body["items"][0]) == CLIENT_FIELDS
    page2 = (await client.get("/api/clients", params={"limit": 10, "offset": 10})).json()
    assert page2["items"][0]["id"] == "CL-0011"


async def test_search_is_case_insensitive(client: httpx.AsyncClient, dataset: SeedDataset) -> None:
    name = dataset.clients[0]["name"]
    needle = name.split()[0][:4]
    expected = [c["id"] for c in dataset.clients if needle.lower() in c["name"].lower()]
    for q in (needle.lower(), needle.upper()):
        body = (await client.get("/api/clients", params={"q": q, "limit": 200})).json()
        assert body["total"] == len(expected)
        assert sorted(c["id"] for c in body["items"]) == sorted(expected)
    none = (await client.get("/api/clients", params={"q": "zzz-no-such-client"})).json()
    assert none == {"items": [], "total": 0}


async def test_detail_with_deals(client: httpx.AsyncClient, dataset: SeedDataset) -> None:
    per_client = Counter(d["client_id"] for d in dataset.deals)
    client_id, n_deals = per_client.most_common(1)[0]
    body = (await client.get(f"/api/clients/{client_id}")).json()
    assert CLIENT_FIELDS <= set(body)
    assert len(body["deals"]) == n_deals
    assert all(set(d) == DEAL_FIELDS and d["client_id"] == client_id for d in body["deals"])
    created = [d["created_at"] for d in body["deals"]]
    assert created == sorted(created, reverse=True)


async def test_detail_not_found(client: httpx.AsyncClient) -> None:
    assert_error(await client.get("/api/clients/CL-9999"), 404, "CLIENT_NOT_FOUND")


# ---------------------------------------------------------------- create


async def test_create_without_owner_runs_the_engine(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/clients", json=new_client_body())
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {"client", "deal", "assignment"}

    new_client, deal, assignment = body["client"], body["deal"], body["assignment"]
    assert re.fullmatch(r"CL-[0-9a-f]{8}", new_client["id"])
    assert new_client["created_on"] == TODAY_ISO and new_client["name"] == "Acme Robotics"
    assert re.fullmatch(r"DL-[0-9a-f]{8}", deal["id"])
    assert deal["status"] == "OPEN" and deal["stage"] == "LEAD"
    assert deal["created_at"] == TODAY_ISO and deal["client_id"] == new_client["id"]
    # Fresh seed + IoT = the planted PEER scenario: Bhavna (SP-002).
    assert assignment["deal_id"] == deal["id"] and assignment["domain"] == "IoT"
    assert assignment["assignment_status"] == "ASSIGNED"
    assert assignment["assigned_to"] == {"id": "SP-002", "name": "Bhavna Rao"}
    assert deal["owner_id"] == "SP-002" and deal["owner_name"] == "Bhavna Rao"
    assert await owner_ids_of(deal["id"]) == ["SP-002"]


async def test_create_with_owner_is_manual(client: httpx.AsyncClient) -> None:
    body = (await client.post("/api/clients", json=new_client_body(owner_id="SP-002"))).json()
    deal, assignment = body["deal"], body["assignment"]
    assert assignment["assignment_status"] == "MANUAL"
    assert assignment["assigned_to"] == {"id": "SP-002", "name": "Bhavna Rao"}
    assert deal["owner_id"] == "SP-002" and deal["owner_name"] == "Bhavna Rao"
    assert await owner_ids_of(deal["id"]) == ["SP-002"]


async def test_create_with_at_capacity_owner_warns(client: httpx.AsyncClient) -> None:
    body = (await client.post("/api/clients", json=new_client_body(owner_id="SP-005"))).json()
    assert body["assignment"]["assignment_status"] == "MANUAL"
    assert body["assignment"]["message"] == "Rep is at capacity (8/8)"
    assert await owner_ids_of(body["deal"]["id"]) == ["SP-005"]


async def test_create_with_unknown_owner_creates_nothing(client: httpx.AsyncClient) -> None:
    before = (await client.get("/api/clients")).json()["total"]
    response = await client.post("/api/clients", json=new_client_body(owner_id="SP-999"))
    assert_error(response, 404, "REP_NOT_FOUND")
    assert (await client.get("/api/clients")).json()["total"] == before


async def test_create_with_inactive_owner_is_rejected(client: httpx.AsyncClient) -> None:
    await client.patch("/api/salespeople/SP-013", json={"active": False})
    try:
        response = await client.post("/api/clients", json=new_client_body(owner_id="SP-013"))
        assert_error(response, 409, "REP_NOT_AVAILABLE")
    finally:
        await client.patch("/api/salespeople/SP-013", json={"active": True})


@pytest.mark.parametrize(
    "deal_override",
    [
        {"domain": "Blockchain"},
        {"value": 0},
        {"value": -10},
        {"expected_close_date": "2025-09-01"},  # > 365 days before 2026-10-06
        {"title": ""},
    ],
)
async def test_create_validation(client: httpx.AsyncClient, deal_override: dict) -> None:
    response = await client.post("/api/clients", json=new_client_body(**deal_override))
    assert_error(response, 422, "VALIDATION_ERROR")


async def test_expected_close_365_days_in_past_is_allowed(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/clients", json=new_client_body(expected_close_date="2025-10-06")
    )
    assert response.status_code == 201, response.text


async def test_client_validation(client: httpx.AsyncClient) -> None:
    body = new_client_body()
    body["client"]["size"] = "HUGE"
    assert_error(await client.post("/api/clients", json=body), 422, "VALIDATION_ERROR")


async def test_create_is_atomic(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the deal id to collide with an existing deal: the client must NOT be created."""
    real_new_id = crud_service.new_id
    monkeypatch.setattr(
        crud_service, "new_id", lambda prefix: "DL-0001" if prefix == "DL" else real_new_id(prefix)
    )
    body = new_client_body()
    body["client"]["name"] = "Orphan Check Pvt Ltd"
    assert_error(await client.post("/api/clients", json=body), 409, "ID_CONFLICT")

    search = (await client.get("/api/clients", params={"q": "Orphan Check"})).json()
    assert search == {"items": [], "total": 0}


async def test_graph_invariants_still_hold() -> None:
    await assert_invariants_hold()
