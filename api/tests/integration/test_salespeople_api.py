"""Integration tests for /api/salespeople (fresh seed for this module)."""

from __future__ import annotations

import re

import httpx
import pytest

from app.seed.profiles import PROFILES
from tests.integration.helpers import assert_error, assert_invariants_hold

pytestmark = pytest.mark.usefixtures("seeded")

REP_FIELDS = {"id", "name", "email", "region", "joined_on", "active", "capacity"}
NEW_REP = {
    "name": "Zara Khan",
    "email": "zara.khan@democrm.local",
    "region": "West",
    "joined_on": "2026-01-15",
}


async def test_list_all(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/salespeople")).json()
    assert body["total"] == 15
    assert [r["id"] for r in body["items"]] == [p.id for p in PROFILES]
    assert set(body["items"][0]) == REP_FIELDS


async def test_pagination(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/salespeople", params={"limit": 5, "offset": 5})).json()
    assert body["total"] == 15
    assert [r["id"] for r in body["items"]] == ["SP-006", "SP-007", "SP-008", "SP-009", "SP-010"]
    last = (await client.get("/api/salespeople", params={"limit": 5, "offset": 15})).json()
    assert last == {"items": [], "total": 15}


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"offset": -1}])
async def test_pagination_limits_are_validated(client: httpx.AsyncClient, params: dict) -> None:
    assert_error(await client.get("/api/salespeople", params=params), 422, "VALIDATION_ERROR")


async def test_filter_active(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/salespeople?active=true")).json()["total"] == 15
    assert (await client.get("/api/salespeople?active=false")).json() == {"items": [], "total": 0}


async def test_detail_open_count_and_availability(client: httpx.AsyncClient) -> None:
    aarav = (await client.get("/api/salespeople/SP-001")).json()
    assert REP_FIELDS <= set(aarav)
    assert aarav["open_count"] == 8 and aarav["capacity"] == 8
    assert aarav["availability"] == 0.0
    # Phase 6: all 5 domains in the fixed order; Bhavna is Aarav's only similar peer.
    assert [e["domain"] for e in aarav["expertise"]] == [
        "AI", "Cybersecurity", "IoT", "DevOps", "Cloud Migration",
    ]  # fmt: skip
    iot = aarav["expertise"][2]
    assert (iot["handled"], iot["won"], iot["lost"], iot["win_rate"]) == (10, 8, 2, 0.8)
    assert iot["qualifies"] is True and iot["last_won_at"] is not None
    cyber = aarav["expertise"][1]
    assert (cyber["handled"], cyber["win_rate"], cyber["qualifies"]) == (0, None, False)
    assert [p["id"] for p in aarav["similar_peers"]] == ["SP-002"]
    peer = aarav["similar_peers"][0]
    assert peer["matched_domains"] == ["AI", "DevOps", "Cloud Migration"]
    assert (peer["match_count"], peer["score"]) == (3, 0.6)

    bhavna = (await client.get("/api/salespeople/SP-002")).json()
    assert bhavna["open_count"] == 2 and bhavna["availability"] == 0.75


async def test_detail_open_counts_match_profile_table(client: httpx.AsyncClient) -> None:
    for p in PROFILES:
        rep = (await client.get(f"/api/salespeople/{p.id}")).json()
        assert rep["open_count"] == p.open_deals, p.id


async def test_detail_not_found(client: httpx.AsyncClient) -> None:
    error = assert_error(await client.get("/api/salespeople/SP-999"), 404, "REP_NOT_FOUND")
    assert error["details"] == {"id": "SP-999"}


async def test_create_with_defaults(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/salespeople", json=NEW_REP)
    assert response.status_code == 201, response.text
    rep = response.json()
    assert re.fullmatch(r"SP-[0-9a-f]{8}", rep["id"])
    assert rep["capacity"] == 8 and rep["active"] is True  # capacity from config.yaml
    assert {k: rep[k] for k in NEW_REP} == NEW_REP
    assert (await client.get("/api/salespeople")).json()["total"] == 16


async def test_create_with_capacity_and_inactive(client: httpx.AsyncClient) -> None:
    body = {**NEW_REP, "email": "z2@democrm.local", "capacity": 3, "active": False}
    rep = (await client.post("/api/salespeople", json=body)).json()
    assert rep["capacity"] == 3 and rep["active"] is False


@pytest.mark.parametrize(
    "override",
    [
        {"email": "not-an-email"},
        {"email": "a@b"},
        {"capacity": 0},
        {"capacity": 51},
        {"region": "Mars"},
        {"name": "   "},
        {"joined_on": "yesterday"},
        {"unknown_field": 1},
    ],
)
async def test_create_validation(client: httpx.AsyncClient, override: dict) -> None:
    response = await client.post("/api/salespeople", json={**NEW_REP, **override})
    assert_error(response, 422, "VALIDATION_ERROR")


async def test_patch_partial(client: httpx.AsyncClient) -> None:
    rep = (await client.patch("/api/salespeople/SP-015", json={"region": "East"})).json()
    assert rep["region"] == "East" and rep["name"] == "Tarun Bose" and rep["capacity"] == 8


async def test_patch_capacity_below_open_count_is_allowed(client: httpx.AsyncClient) -> None:
    rep = (await client.patch("/api/salespeople/SP-003", json={"capacity": 2})).json()
    assert rep["capacity"] == 2
    detail = (await client.get("/api/salespeople/SP-003")).json()
    assert detail["open_count"] == 5 and detail["availability"] == 0.0  # clamped


async def test_patch_active_flag(client: httpx.AsyncClient) -> None:
    await client.patch("/api/salespeople/SP-014", json={"active": False})
    inactive = (await client.get("/api/salespeople?active=false")).json()
    assert "SP-014" in [r["id"] for r in inactive["items"]]
    await client.patch("/api/salespeople/SP-014", json={"active": True})


async def test_patch_empty_body_changes_nothing(client: httpx.AsyncClient) -> None:
    before = (await client.get("/api/salespeople/SP-010")).json()
    after = (await client.patch("/api/salespeople/SP-010", json={})).json()
    assert {k: before[k] for k in REP_FIELDS} == after


async def test_patch_errors(client: httpx.AsyncClient) -> None:
    assert_error(
        await client.patch("/api/salespeople/SP-999", json={"capacity": 5}), 404, "REP_NOT_FOUND"
    )
    for body in ({"capacity": None}, {"capacity": 99}, {"joined_on": "2020-01-01"}):
        response = await client.patch("/api/salespeople/SP-010", json=body)
        assert_error(response, 422, "VALIDATION_ERROR")


async def test_graph_invariants_still_hold() -> None:
    await assert_invariants_hold()
