"""Integration tests for /api/activities and GET /api/deals/{id}/activities (fresh seed)."""

from __future__ import annotations

import re
from datetime import timedelta

import httpx
import pytest

from app.seed.generator import SeedDataset
from tests.integration.helpers import TODAY, TODAY_ISO, assert_error, assert_invariants_hold

pytestmark = pytest.mark.usefixtures("seeded")

ACTIVITY_FIELDS = {"id", "type", "date", "outcome", "deal_id", "sales_person_id",
                   "sales_person_name"}  # fmt: skip


def _open_deal(dataset: SeedDataset, owner: str) -> dict:
    return next(d for d in dataset.deals if d["status"] == "OPEN" and d["owner_id"] == owner)


def _closed_deal(dataset: SeedDataset) -> dict:
    return next(
        d for d in dataset.deals if d["closed_at"] and (d["closed_at"] - d["created_at"]).days > 5
    )


async def _log(client: httpx.AsyncClient, **body: object) -> httpx.Response:
    payload = {"type": "CALL", "outcome": "POSITIVE", **body}
    return await client.post("/api/activities", json=payload)


async def test_create_defaults_to_today(client: httpx.AsyncClient, dataset: SeedDataset) -> None:
    deal = _open_deal(dataset, "SP-002")
    response = await _log(client, deal_id=deal["id"], sales_person_id="SP-002")
    assert response.status_code == 201, response.text
    activity = response.json()
    assert set(activity) == ACTIVITY_FIELDS
    assert re.fullmatch(r"AC-[0-9a-f]{8}", activity["id"])
    assert activity["date"] == TODAY_ISO
    assert activity["sales_person_name"] == "Bhavna Rao"


async def test_colleague_can_log_on_someone_elses_deal(
    client: httpx.AsyncClient, dataset: SeedDataset
) -> None:
    deal = _open_deal(dataset, "SP-001")
    response = await _log(client, deal_id=deal["id"], sales_person_id="SP-009", type="DEMO")
    assert response.status_code == 201, response.text
    assert response.json()["sales_person_name"] == "Manoj Das"


async def test_list_newest_first(client: httpx.AsyncClient, dataset: SeedDataset) -> None:
    deal = _open_deal(dataset, "SP-007")
    older = (TODAY - timedelta(days=1)).isoformat()
    await _log(client, deal_id=deal["id"], sales_person_id="SP-007", date=older)
    await _log(client, deal_id=deal["id"], sales_person_id="SP-007", type="EMAIL")
    rows = (await client.get(f"/api/deals/{deal['id']}/activities")).json()
    seeded = [a for a in dataset.activities if a["deal_id"] == deal["id"]]
    assert len(rows) == len(seeded) + 2
    assert rows[0]["date"] == TODAY_ISO
    assert [r["date"] for r in rows] == sorted((r["date"] for r in rows), reverse=True)


async def test_date_rules_on_open_deal(client: httpx.AsyncClient, dataset: SeedDataset) -> None:
    deal = _open_deal(dataset, "SP-008")
    before_created = (deal["created_at"] - timedelta(days=1)).isoformat()
    tomorrow = (TODAY + timedelta(days=1)).isoformat()
    for bad in (before_created, tomorrow):
        response = await _log(client, deal_id=deal["id"], sales_person_id="SP-008", date=bad)
        error = assert_error(response, 400, "INVALID_ACTIVITY_DATE")
        assert error["details"]["earliest"] == deal["created_at"].isoformat()
    on_created = deal["created_at"].isoformat()
    ok = await _log(client, deal_id=deal["id"], sales_person_id="SP-008", date=on_created)
    assert ok.status_code == 201, ok.text


async def test_date_rules_on_closed_deal(client: httpx.AsyncClient, dataset: SeedDataset) -> None:
    deal = _closed_deal(dataset)
    owner = deal["owner_id"]
    after_close = (deal["closed_at"] + timedelta(days=1)).isoformat()
    response = await _log(client, deal_id=deal["id"], sales_person_id=owner, date=after_close)
    assert_error(response, 400, "INVALID_ACTIVITY_DATE")
    before_close = (deal["closed_at"] - timedelta(days=1)).isoformat()
    ok = await _log(client, deal_id=deal["id"], sales_person_id=owner, date=before_close)
    assert ok.status_code == 201, ok.text


async def test_not_found_and_validation(client: httpx.AsyncClient, dataset: SeedDataset) -> None:
    deal = _open_deal(dataset, "SP-010")
    assert_error(
        await _log(client, deal_id="DL-9999", sales_person_id="SP-010"), 404, "DEAL_NOT_FOUND"
    )
    assert_error(
        await _log(client, deal_id=deal["id"], sales_person_id="SP-999"), 404, "REP_NOT_FOUND"
    )
    for override in ({"type": "LUNCH"}, {"outcome": "GREAT"}, {"date": "not-a-date"}):
        response = await _log(client, deal_id=deal["id"], sales_person_id="SP-010", **override)
        assert_error(response, 422, "VALIDATION_ERROR")
    assert_error(await client.get("/api/deals/DL-9999/activities"), 404, "DEAL_NOT_FOUND")


async def test_graph_invariants_still_hold() -> None:
    await assert_invariants_hold()
