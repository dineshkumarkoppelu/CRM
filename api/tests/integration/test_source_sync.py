"""The Postgres data source -> Neo4j sync, against the TEST Neo4j and an in-memory fake of the
Postgres CRUD API (so no Postgres is needed). Covers the first adoption, real-time row
changes, the safety-net full sync and the UI write path (Postgres first, then the graph)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.db import run_write
from app.core.settings import get_settings
from app.seed.generator import SeedDataset
from app.services import expertise_service
from app.sync import events, source_client
from app.sync import service as sync
from tests.conftest import _http_client
from tests.integration.fake_source import FakeSource


@pytest.fixture(scope="module")
async def source(api_app: FastAPI, dataset: SeedDataset) -> AsyncIterator[FakeSource]:
    """The app in data-source mode, already synced once from a fake with the seed dataset."""
    fake = FakeSource(dataset)
    mp = pytest.MonkeyPatch()
    mp.setattr(source_client, "enabled", lambda: True)
    for name in ("list_all", "get", "create", "patch", "delete"):
        mp.setattr(source_client, name, getattr(fake, name))
    sync.reset_for_tests()
    await run_write("MATCH (m:SyncState) DELETE m")  # a database that has never seen the source
    fake.first_sync = await sync.full_sync()  # type: ignore[attr-defined]
    await expertise_service.recompute()
    try:
        yield fake
    finally:
        mp.undo()
        sync.reset_for_tests()
        get_settings.cache_clear()


@pytest.fixture
async def http(api_app: FastAPI, source: FakeSource) -> AsyncIterator[httpx.AsyncClient]:
    async with _http_client(api_app) as client:
        yield client


@pytest.fixture
def published(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(events, "publish", seen.append)
    return seen


def _deal(**over: Any) -> dict[str, Any]:
    return {
        "id": "DL-X001", "title": "External deal", "value": 500_000, "status": "OPEN",
        "stage": "LEAD", "created_at": "2026-10-05", "qualified_at": None,
        "proposal_at": None, "negotiation_at": None, "expected_close_date": "2026-10-28",
        "closed_at": None, "domain": "AI", "client_id": "CL-X001", "owner_id": None,
        **over,
    }  # fmt: skip


def _client_row(**over: Any) -> dict[str, Any]:
    return {
        "id": "CL-X001", "name": "External Client", "industry": "Retail", "size": "SMB",
        "region": "West", "created_on": "2026-10-01", **over,
    }  # fmt: skip


async def _deal_json(http: httpx.AsyncClient, deal_id: str) -> dict[str, Any] | None:
    response = await http.get(f"/api/deals/{deal_id}")
    return response.json() if response.status_code == 200 else None


async def test_first_sync_adopts_the_source_and_matches_it(
    http: httpx.AsyncClient, source: FakeSource, dataset: SeedDataset
) -> None:
    first = source.first_sync  # type: ignore[attr-defined]
    assert first.adopted is True
    assert {t.table: t.upserted for t in first.tables} == {
        "sales_people": len(dataset.sales_people),
        "clients": len(dataset.clients),
        "deals": len(dataset.deals),
        "activities": len(dataset.activities),
    }
    assert (await http.get("/api/deals", params={"limit": 1})).json()["total"] == len(dataset.deals)
    assert (await http.get("/api/clients", params={"limit": 1})).json()["total"] == len(
        dataset.clients
    )


async def test_second_full_sync_changes_nothing(source: FakeSource) -> None:
    again = await sync.full_sync()
    assert again.adopted is False
    assert [(t.upserted, t.deleted, t.skipped) for t in again.tables] == [(0, 0, 0)] * 4


async def test_external_insert_shows_up_unassigned(
    http: httpx.AsyncClient, source: FakeSource, published: list[dict[str, Any]]
) -> None:
    source.put("clients", _client_row())
    source.put("deals", _deal())
    assert await sync.apply_row("clients", "CL-X001", "INSERT") == "upserted"
    assert await sync.apply_row("deals", "DL-X001", "INSERT") == "upserted"

    deal = await _deal_json(http, "DL-X001")
    assert deal is not None
    assert deal["owner_id"] is None and deal["owner_name"] is None
    assert deal["client_name"] == "External Client"
    assert {"table": "deals", "op": "INSERT", "id": "DL-X001"} in published


async def test_external_update_moves_the_owner_without_duplicating_it(
    http: httpx.AsyncClient, source: FakeSource, dataset: SeedDataset
) -> None:
    first_rep, second_rep = dataset.sales_people[0]["id"], dataset.sales_people[1]["id"]
    before = (await http.get(f"/api/salespeople/{first_rep}")).json()["open_count"]

    source.put("deals", _deal(owner_id=first_rep, stage="QUALIFIED", qualified_at="2026-10-06"))
    await sync.apply_row("deals", "DL-X001", "UPDATE")
    deal = await _deal_json(http, "DL-X001")
    assert deal and deal["owner_id"] == first_rep and deal["stage"] == "QUALIFIED"
    assert (await http.get(f"/api/salespeople/{first_rep}")).json()["open_count"] == before + 1

    source.put("deals", _deal(owner_id=second_rep, stage="QUALIFIED", qualified_at="2026-10-06"))
    await sync.apply_row("deals", "DL-X001", "UPDATE")
    deal = await _deal_json(http, "DL-X001")
    assert deal and deal["owner_id"] == second_rep
    assert (await http.get(f"/api/salespeople/{first_rep}")).json()["open_count"] == before


async def test_domain_is_matched_ignoring_case(http: httpx.AsyncClient, source: FakeSource) -> None:
    source.put("deals", _deal(domain="ai"))
    await sync.apply_row("deals", "DL-X001", "UPDATE")
    deal = await _deal_json(http, "DL-X001")
    assert deal and deal["domain"] == "AI"


async def test_rows_that_cannot_be_loaded_are_skipped_and_reported(
    http: httpx.AsyncClient, source: FakeSource
) -> None:
    source.put("deals", _deal(id="DL-X002", client_id="CL-NOPE"))
    assert (await sync.apply_row("deals", "DL-X002")).startswith("skipped")

    source.put("deals", _deal(id="DL-X003", domain="!!"))  # not a valid domain name
    assert (await sync.apply_row("deals", "DL-X003")).startswith("skipped")

    assert await _deal_json(http, "DL-X002") is None
    assert await _deal_json(http, "DL-X003") is None
    problems = {(p.table, p.id) for p in sync.status().problems}
    assert {("deals", "DL-X002"), ("deals", "DL-X003")} <= problems


async def test_deal_with_an_unknown_owner_is_kept_unassigned(
    http: httpx.AsyncClient, source: FakeSource
) -> None:
    source.put("deals", _deal(id="DL-X004", owner_id="SP-404"))
    assert await sync.apply_row("deals", "DL-X004") == "upserted"
    deal = await _deal_json(http, "DL-X004")
    assert deal and deal["owner_id"] is None


async def test_external_delete_removes_the_deal_and_its_activities(
    http: httpx.AsyncClient, source: FakeSource, dataset: SeedDataset
) -> None:
    rep = dataset.sales_people[0]["id"]
    source.put(
        "activities",
        {"id": "AC-X001", "type": "CALL", "date": "2026-10-06", "outcome": "POSITIVE",
         "deal_id": "DL-X001", "sales_person_id": rep},
    )  # fmt: skip
    await sync.apply_row("activities", "AC-X001", "INSERT")
    assert [a["id"] for a in (await _deal_json(http, "DL-X001") or {})["activities"]] == ["AC-X001"]

    source.remove("deals", "DL-X001")
    assert await sync.apply_row("deals", "DL-X001", "DELETE") == "deleted"
    assert await _deal_json(http, "DL-X001") is None

    source.put("deals", _deal())  # an orphan activity (no foreign key in the source) is reported
    source.remove("deals", "DL-X001")
    assert (await sync.apply_row("activities", "AC-X001")).startswith("skipped")


async def test_full_sync_catches_up_with_changes_made_while_it_was_not_listening(
    http: httpx.AsyncClient, source: FakeSource, dataset: SeedDataset
) -> None:
    victim = dataset.deals[0]["id"]
    changed = dataset.deals[1]["id"]
    source.remove("deals", victim)
    source.tables["deals"][changed]["title"] = "Renamed while away"

    result = await sync.full_sync()
    by_table = {t.table: t for t in result.tables}
    assert by_table["deals"].deleted == 1 and by_table["deals"].upserted >= 1
    assert await _deal_json(http, victim) is None
    assert (await _deal_json(http, changed) or {})["title"] == "Renamed while away"


async def test_ui_creates_client_and_deal_in_the_source_first(
    http: httpx.AsyncClient, source: FakeSource
) -> None:
    response = await http.post(
        "/api/clients",
        json={
            "client": {"name": "UI Made Ltd", "industry": "Energy", "size": "MID_MARKET",
                       "region": "North"},
            "deal": {"title": "UI deal", "value": 900_000, "domain": "Cybersecurity",
                     "expected_close_date": "2026-10-30"},
        },
    )  # fmt: skip
    assert response.status_code == 201, response.text
    body = response.json()
    deal_id, client_id = body["deal"]["id"], body["client"]["id"]

    assert client_id in source.tables["clients"]
    row = source.tables["deals"][deal_id]
    assert row["status"] == "OPEN" and row["stage"] == "LEAD" and row["client_id"] == client_id
    assert body["assignment"]["assignment_status"] == "ASSIGNED"
    assert row["owner_id"] == body["assignment"]["assigned_to"]["id"]  # owner written to Postgres
    assert (await _deal_json(http, deal_id) or {})["owner_id"] == row["owner_id"]


async def test_ui_stage_edit_override_and_activity_all_go_through_the_source(
    http: httpx.AsyncClient, source: FakeSource
) -> None:
    deal_id = next(d for d in reversed(list(source.tables["deals"])) if d.startswith("DL-") and
                   source.tables["deals"][d]["status"] == "OPEN" and
                   source.tables["deals"][d]["owner_id"])  # fmt: skip
    current_owner = source.tables["deals"][deal_id]["owner_id"]
    stage = source.tables["deals"][deal_id]["stage"]

    if stage != "NEGOTIATION":
        moved = await http.post(f"/api/deals/{deal_id}/stage", json={"action": "ADVANCE"})
        assert moved.status_code == 200, moved.text
        assert source.tables["deals"][deal_id]["stage"] == moved.json()["stage"] != stage

    edited = await http.patch(f"/api/deals/{deal_id}", json={"title": "Edited in UI"})
    assert edited.status_code == 200, edited.text
    assert source.tables["deals"][deal_id]["title"] == "Edited in UI"

    target = None
    reps = (await http.get("/api/salespeople", params={"limit": 100})).json()["items"]
    for rep in reps:
        detail = (await http.get(f"/api/salespeople/{rep['id']}")).json()
        if rep["id"] != current_owner and rep["active"] and detail["open_count"] < rep["capacity"]:
            target = rep["id"]
            break
    assert target is not None
    overridden = await http.post(
        f"/api/recommendations/{deal_id}/override", json={"sales_person_id": target}
    )
    assert overridden.status_code == 200, overridden.text
    assert source.tables["deals"][deal_id]["owner_id"] == target
    assert (await _deal_json(http, deal_id) or {})["owner_id"] == target

    activity = await http.post(
        "/api/activities",
        json={"deal_id": deal_id, "sales_person_id": target, "type": "EMAIL", "outcome": "NEUTRAL"},
    )
    assert activity.status_code == 201, activity.text
    assert activity.json()["id"] in source.tables["activities"]


async def test_ui_edits_a_sales_person_and_adds_one(
    http: httpx.AsyncClient, source: FakeSource, dataset: SeedDataset
) -> None:
    rep_id = dataset.sales_people[0]["id"]
    updated = await http.patch(f"/api/salespeople/{rep_id}", json={"capacity": 14})
    assert updated.status_code == 200, updated.text
    assert source.tables["sales_people"][rep_id]["capacity"] == 14

    created = await http.post(
        "/api/salespeople",
        json={"name": "New Rep", "email": "new.rep@example.com", "region": "East",
              "joined_on": "2026-10-01"},
    )  # fmt: skip
    assert created.status_code == 201, created.text
    assert created.json()["id"] in source.tables["sales_people"]
    assert (await http.get(f"/api/salespeople/{created.json()['id']}")).status_code == 200


async def test_ui_deal_for_a_missing_client_is_a_404(http: httpx.AsyncClient) -> None:
    response = await http.post(
        "/api/deals",
        json={"client_id": "CL-NOPE", "title": "x", "value": 1000, "domain": "AI",
              "expected_close_date": "2026-10-30"},
    )  # fmt: skip
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CLIENT_NOT_FOUND"


async def test_seed_endpoint_resyncs_from_the_source_instead_of_generating(
    http: httpx.AsyncClient, source: FakeSource
) -> None:
    for unloadable in ("DL-X002", "DL-X003"):  # the rows earlier tests made un-loadable
        source.remove("deals", unloadable)
    response = await http.post("/api/admin/seed")
    assert response.status_code == 200, response.text
    counts = response.json()["counts"]
    assert counts["Deal"] == len(source.tables["deals"])
    assert counts["SalesPerson"] == len(source.tables["sales_people"])
    assert (await http.get("/api/admin/sync/status")).status_code == 200


async def test_resync_needs_a_configured_source(
    http: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(source_client, "enabled", lambda: False)
    response = await http.post("/api/admin/resync")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SOURCE_NOT_CONFIGURED"
