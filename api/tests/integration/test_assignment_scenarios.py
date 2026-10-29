"""The planted assignment scenarios end to end (FRESH seed per test, AS_OF_DATE=2026-10-06)."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from app.core.db import run_read
from app.repositories import recommendation_repo
from app.seed.planted import CAPACITY_SCENARIO, PEER_SCENARIO
from tests.conftest import seed_test_db
from tests.integration.helpers import assert_error, assert_invariants_hold, owner_ids_of

REC_FIELDS = {"sales_person_id", "name", "rank", "score", "fit", "availability", "fit_type",
              "reason", "status"}  # fmt: skip


@pytest.fixture(autouse=True)
async def fresh(api_app: FastAPI) -> None:
    await seed_test_db(api_app)


def _new_client(domain: str, name: str) -> dict:
    return {
        "client": {"name": name, "industry": "Logistics", "size": "ENTERPRISE", "region": "South"},
        "deal": {"title": f"{domain} engagement", "value": 4_200_000, "domain": domain,
                 "expected_close_date": "2026-12-15"},
    }  # fmt: skip


async def _create(client: httpx.AsyncClient, domain: str, name: str = "Volt Labs") -> dict:
    response = await client.post("/api/clients", json=_new_client(domain, name))
    assert response.status_code == 201, response.text
    return response.json()


def _check_scenario(assignment: dict, scenario: dict) -> None:
    assert assignment["assignment_status"] == "ASSIGNED"
    assert assignment["assigned_to"]["id"] == scenario["expected_assignee"]
    top = assignment["candidates"][0]
    assert set(top) == REC_FIELDS
    assert (top["sales_person_id"], top["rank"], top["status"]) == (
        scenario["expected_assignee"], 1, "ASSIGNED",
    )  # fmt: skip
    assert top["fit_type"] == scenario["fit_type"]
    assert top["score"] == scenario["expected_score"]
    assert [c["sales_person_id"] for c in assignment["candidates"]] == scenario["expected_top5"]
    assert all(c["status"] == "CANDIDATE" for c in assignment["candidates"][1:])
    assert {u["id"]: u["reason"] for u in assignment["unavailable"]} == scenario[
        "expected_unavailable"
    ]


async def test_peer_scenario_iot_goes_to_bhavna(client: httpx.AsyncClient) -> None:
    body = await _create(client, "IoT")
    assignment = body["assignment"]
    _check_scenario(assignment, PEER_SCENARIO)
    reason = assignment["candidates"][0]["reason"]
    for fragment in ("Aarav Mehta", "AI, DevOps and Cloud Migration", "80%"):
        assert fragment in reason
    assert body["deal"]["owner_id"] == "SP-002"
    assert await owner_ids_of(body["deal"]["id"]) == ["SP-002"]

    stored = await run_read(
        "MATCH (:Deal {id: $id})-[r:RECOMMENDED_TO]->(s) RETURN s.id AS id, r.rank AS rank "
        "ORDER BY rank",
        {"id": body["deal"]["id"]},
    )
    assert [r["id"] for r in stored] == PEER_SCENARIO["expected_top5"]


async def test_capacity_scenario_cybersecurity_goes_to_divya(client: httpx.AsyncClient) -> None:
    assignment = (await _create(client, "Cybersecurity"))["assignment"]
    _check_scenario(assignment, CAPACITY_SCENARIO)
    chetan = next(u for u in assignment["unavailable"] if u["id"] == "SP-005")
    assert (chetan["reason"], chetan["open_count"], chetan["capacity"]) == ("AT_CAPACITY", 8, 8)
    assert assignment["candidates"][0]["reason"] == (
        "DIRECT fit: wins 70% of Cybersecurity deals (7/10); 4/8 open deals."
    )


async def test_demo_order_iot_then_cybersecurity(client: httpx.AsyncClient) -> None:
    """The demo creates the IoT deal first; that must not change the Cybersecurity outcome."""
    await _create(client, "IoT", "First Co")
    _check_scenario((await _create(client, "Cybersecurity", "Second Co"))["assignment"],
                    CAPACITY_SCENARIO)  # fmt: skip


async def test_no_capacity_leaves_the_deal_unassigned(client: httpx.AsyncClient) -> None:
    reps = (await client.get("/api/salespeople", params={"limit": 200})).json()["items"]
    for rep in reps:
        assert (
            await client.patch(f"/api/salespeople/{rep['id']}", json={"capacity": 1})
        ).status_code == 200
    body = await _create(client, "AI")
    assignment = body["assignment"]
    assert assignment["assignment_status"] == "UNASSIGNED"
    assert assignment["assigned_to"] is None and assignment["candidates"] == []
    assert assignment["message"] == "No available sales person (all inactive or at capacity)"
    assert len(assignment["unavailable"]) == 15
    assert await owner_ids_of(body["deal"]["id"]) == []

    # GET returns the stored state; /run on an unassigned deal still finds nobody.
    stored = (await client.get(f"/api/recommendations/{body['deal']['id']}")).json()
    assert stored["assignment_status"] == "UNASSIGNED"
    rerun = (await client.post(f"/api/recommendations/{body['deal']['id']}/run")).json()
    assert rerun["assignment_status"] == "UNASSIGNED"


async def test_preview_writes_nothing(client: httpx.AsyncClient) -> None:
    deal_id = (await _create(client, "IoT"))["deal"]["id"]
    before = await recommendation_repo.count_recommendations()
    response = await client.post(f"/api/recommendations/{deal_id}/preview")
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["message"].startswith("Preview only")
    assert preview["candidates"][0]["fit_type"] in {"DIRECT", "PEER", "COLD_START"}
    assert await recommendation_repo.count_recommendations() == before
    assert await owner_ids_of(deal_id) == ["SP-002"]  # unchanged


async def test_get_and_run_endpoints(client: httpx.AsyncClient) -> None:
    deal_id = (await _create(client, "IoT"))["deal"]["id"]
    stored = (await client.get(f"/api/recommendations/{deal_id}")).json()
    assert stored["assignment_status"] == "ASSIGNED"
    assert stored["assigned_to"]["id"] == "SP-002"
    assert [c["sales_person_id"] for c in stored["candidates"]] == PEER_SCENARIO["expected_top5"]

    assert_error(await client.post(f"/api/recommendations/{deal_id}/run"), 409, "ALREADY_ASSIGNED")
    assert_error(await client.get("/api/recommendations/DL-9999"), 404, "DEAL_NOT_FOUND")
    detail = (await client.get(f"/api/deals/{deal_id}")).json()
    assert len(detail["recommendations"]) == 5


async def test_graph_invariants_hold_after_assignment(client: httpx.AsyncClient) -> None:
    await _create(client, "IoT")
    await _create(client, "Cybersecurity", "Other Co")
    await assert_invariants_hold()
