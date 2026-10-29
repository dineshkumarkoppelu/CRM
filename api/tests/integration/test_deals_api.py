"""Integration tests for /api/deals (fresh seed for this module)."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from app.seed.generator import SeedDataset
from tests.integration.helpers import (
    DEAL_FIELDS,
    TODAY_ISO,
    assert_error,
    assert_invariants_hold,
    owner_ids_of,
)

pytestmark = pytest.mark.usefixtures("seeded")


async def _total(client: httpx.AsyncClient, **params: str) -> int:
    response = await client.get("/api/deals", params={**params, "limit": 1})
    assert response.status_code == 200, response.text
    return response.json()["total"]


async def _new_deal(client: httpx.AsyncClient, **overrides: object) -> dict:
    body = {
        "client_id": "CL-0001",
        "title": "Observability stack",
        "value": 900_000,
        "domain": "DevOps",
        "expected_close_date": "2026-12-15",
        **overrides,
    }
    response = await client.post("/api/deals", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def _move(client: httpx.AsyncClient, deal_id: str, action: str) -> httpx.Response:
    return await client.post(f"/api/deals/{deal_id}/stage", json={"action": action})


# ---------------------------------------------------------------- list + filters (run first)


async def test_list_shape_and_order(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/deals", params={"limit": 20})).json()
    assert body["total"] == 695
    assert len(body["items"]) == 20
    assert all(set(d) == DEAL_FIELDS for d in body["items"])
    created = [d["created_at"] for d in body["items"]]
    assert created == sorted(created, reverse=True)  # newest first


async def test_each_filter_matches_the_dataset(
    client: httpx.AsyncClient, dataset: SeedDataset
) -> None:
    deals = dataset.deals

    def expected(pred: Callable[[dict], bool]) -> int:
        return sum(1 for d in deals if pred(d))

    assert await _total(client, status="OPEN") == expected(lambda d: d["status"] == "OPEN") == 80
    assert await _total(client, status="WON") == expected(lambda d: d["status"] == "WON")
    assert await _total(client, stage="PROPOSAL") == expected(lambda d: d["stage"] == "PROPOSAL")
    assert await _total(client, domain="Cloud Migration") == expected(
        lambda d: d["domain"] == "Cloud Migration"
    )
    assert await _total(client, owner_id="SP-001") == expected(lambda d: d["owner_id"] == "SP-001")
    assert await _total(client, client_id="CL-0002") == expected(
        lambda d: d["client_id"] == "CL-0002"
    )
    october = expected(lambda d: d["expected_close_date"].strftime("%Y-%m") == "2026-10")
    assert await _total(client, closing_month="2026-10") == october


async def test_combined_filters(client: httpx.AsyncClient) -> None:
    # 55 open deals are planted to close in the current month (phase-02 R2.3).
    assert await _total(client, status="OPEN", closing_month="2026-10") == 55
    assert await _total(client, status="OPEN", closing_month="2026-11") == 25
    assert await _total(client, status="OPEN", owner_id="SP-001") == 8
    assert await _total(client, owner_id="SP-002", domain="IoT") == 0  # Bhavna: no IoT ever


async def test_pagination_pages_are_disjoint(client: httpx.AsyncClient) -> None:
    first = (await client.get("/api/deals", params={"limit": 50})).json()["items"]
    second = (await client.get("/api/deals", params={"limit": 50, "offset": 50})).json()["items"]
    assert len(first) == len(second) == 50
    assert not {d["id"] for d in first} & {d["id"] for d in second}


@pytest.mark.parametrize(
    "params",
    [
        {"closing_month": "2026-13"},
        {"closing_month": "2026-1"},
        {"status": "PENDING"},
        {"stage": "CLOSED"},
        {"domain": "Blockchain"},
        {"limit": 500},
    ],
)
async def test_invalid_filters(client: httpx.AsyncClient, params: dict) -> None:
    assert_error(await client.get("/api/deals", params=params), 422, "VALIDATION_ERROR")


# ---------------------------------------------------------------- detail


async def test_detail_includes_activities(client: httpx.AsyncClient, dataset: SeedDataset) -> None:
    body = (await client.get("/api/deals/DL-0001")).json()
    assert DEAL_FIELDS <= set(body)
    expected = [a for a in dataset.activities if a["deal_id"] == "DL-0001"]
    assert len(body["activities"]) == len(expected) >= 2
    dates = [a["date"] for a in body["activities"]]
    assert dates == sorted(dates, reverse=True)
    assert body["recommendations"] == []  # until Phase 6
    seeded = next(d for d in dataset.deals if d["id"] == "DL-0001")
    assert body["owner_id"] == seeded["owner_id"] and body["client_id"] == seeded["client_id"]


async def test_detail_not_found(client: httpx.AsyncClient) -> None:
    assert_error(await client.get("/api/deals/DL-9999"), 404, "DEAL_NOT_FOUND")


# ---------------------------------------------------------------- create


async def test_create_without_owner(client: httpx.AsyncClient) -> None:
    body = await _new_deal(client)
    deal = body["deal"]
    assert deal["status"] == "OPEN" and deal["stage"] == "LEAD" and deal["created_at"] == TODAY_ISO
    assert deal["client_id"] == "CL-0001"
    assert body["assignment"]["assignment_status"] == "ASSIGNED"  # engine picks the owner
    assert deal["owner_id"] == body["assignment"]["assigned_to"]["id"]
    assert await owner_ids_of(deal["id"]) == [deal["owner_id"]]


async def test_create_with_owner(client: httpx.AsyncClient) -> None:
    body = await _new_deal(client, owner_id="SP-006")
    assert body["assignment"]["assignment_status"] == "MANUAL"
    assert body["assignment"]["message"] == "Manually assigned to Divya Nair"
    assert await owner_ids_of(body["deal"]["id"]) == ["SP-006"]


async def test_create_errors(client: httpx.AsyncClient) -> None:
    base = {
        "client_id": "CL-0001",
        "title": "x",
        "value": 1,
        "domain": "AI",
        "expected_close_date": "2026-12-01",
    }
    assert_error(
        await client.post("/api/deals", json={**base, "client_id": "CL-9999"}),
        404,
        "CLIENT_NOT_FOUND",
    )
    assert_error(
        await client.post("/api/deals", json={**base, "owner_id": "SP-999"}), 404, "REP_NOT_FOUND"
    )
    assert_error(
        await client.post("/api/deals", json={**base, "value": 0}), 422, "VALIDATION_ERROR"
    )


# ---------------------------------------------------------------- stage moves


async def test_full_stage_walk_to_win(client: httpx.AsyncClient) -> None:
    deal_id = (await _new_deal(client, owner_id="SP-004"))["deal"]["id"]
    expected = [
        ("ADVANCE", "QUALIFIED", "qualified_at"),
        ("ADVANCE", "PROPOSAL", "proposal_at"),
        ("ADVANCE", "NEGOTIATION", "negotiation_at"),
    ]
    for action, stage, field in expected:
        response = await _move(client, deal_id, action)
        assert response.status_code == 200, response.text
        deal = response.json()
        assert deal["status"] == "OPEN" and deal["stage"] == stage and deal[field] == TODAY_ISO

    won = (await _move(client, deal_id, "WIN")).json()
    assert won["status"] == "WON" and won["stage"] == "NEGOTIATION"
    assert won["closed_at"] == TODAY_ISO
    assert all(won[f] == TODAY_ISO for f in ("qualified_at", "proposal_at", "negotiation_at"))

    for action in ("ADVANCE", "WIN", "LOSE"):  # closed deals cannot move
        assert_error(await _move(client, deal_id, action), 400, "DEAL_CLOSED")


async def test_lose_from_proposal_keeps_stage(client: httpx.AsyncClient) -> None:
    deal_id = (await _new_deal(client))["deal"]["id"]
    await _move(client, deal_id, "ADVANCE")
    await _move(client, deal_id, "ADVANCE")
    lost = (await _move(client, deal_id, "LOSE")).json()
    assert lost["status"] == "LOST" and lost["stage"] == "PROPOSAL"
    assert lost["closed_at"] == TODAY_ISO and lost["negotiation_at"] is None


async def test_illegal_moves(client: httpx.AsyncClient) -> None:
    deal_id = (await _new_deal(client))["deal"]["id"]
    assert_error(await _move(client, deal_id, "WIN"), 400, "ILLEGAL_STAGE_TRANSITION")
    for _ in range(3):
        await _move(client, deal_id, "ADVANCE")
    error = assert_error(await _move(client, deal_id, "ADVANCE"), 400, "ILLEGAL_STAGE_TRANSITION")
    assert error["details"] == {"stage": "NEGOTIATION", "action": "ADVANCE"}
    assert_error(await _move(client, deal_id, "JUMP"), 422, "VALIDATION_ERROR")
    assert_error(await _move(client, "DL-9999", "ADVANCE"), 404, "DEAL_NOT_FOUND")


async def test_seeded_closed_deal_cannot_move(
    client: httpx.AsyncClient, dataset: SeedDataset
) -> None:
    closed = next(d for d in dataset.deals if d["status"] == "LOST")
    assert_error(await _move(client, closed["id"], "ADVANCE"), 400, "DEAL_CLOSED")


# ---------------------------------------------------------------- patch


async def test_patch_open_deal(client: httpx.AsyncClient) -> None:
    deal_id = (await _new_deal(client))["deal"]["id"]
    changes = {"title": "Renamed deal", "value": 1_234_000, "expected_close_date": "2027-01-31"}
    deal = (await client.patch(f"/api/deals/{deal_id}", json=changes)).json()
    assert {k: deal[k] for k in changes} == changes
    assert deal["stage"] == "LEAD" and deal["status"] == "OPEN"


async def test_patch_errors(client: httpx.AsyncClient, dataset: SeedDataset) -> None:
    won = next(d for d in dataset.deals if d["status"] == "WON")
    assert_error(
        await client.patch(f"/api/deals/{won['id']}", json={"title": "x"}), 400, "DEAL_CLOSED"
    )
    assert_error(
        await client.patch("/api/deals/DL-9999", json={"title": "x"}), 404, "DEAL_NOT_FOUND"
    )
    open_id = next(d["id"] for d in dataset.deals if d["status"] == "OPEN")
    for body in ({"value": -5}, {"title": None}, {"status": "WON"}, {"domain": "AI"}):
        response = await client.patch(f"/api/deals/{open_id}", json=body)
        assert_error(response, 422, "VALIDATION_ERROR")


async def test_graph_invariants_still_hold() -> None:
    await assert_invariants_hold()
