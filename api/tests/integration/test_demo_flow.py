"""End to end: the whole demo through the API, in the order of docs/DEMO_SCRIPT.md.

seed -> dashboard numbers + forecast -> heatmap / similarity -> PEER scenario -> CAPACITY
scenario -> override -> graph explorer. AS_OF_DATE = 2026-10-06 (tests).
"""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from app.seed.planted import CAPACITY_SCENARIO, EXPECTED_SIMILAR_PAIRS, PEER_SCENARIO
from tests.conftest import seed_test_db
from tests.integration.helpers import assert_invariants_hold, owner_ids_of


def _client_body(name: str, domain: str, title: str) -> dict:
    return {
        "client": {"name": name, "industry": "Logistics", "size": "ENTERPRISE", "region": "South"},
        "deal": {
            "title": title,
            "value": 4_200_000,
            "domain": domain,
            "expected_close_date": "2026-12-15",
        },
    }


async def test_full_demo_flow(api_app: FastAPI, client: httpx.AsyncClient) -> None:
    # 0. Reset demo data
    seed = await seed_test_db(api_app)
    assert (seed["counts"]["Deal"], seed["expertise_edges"], seed["similar_pairs"]) == (695, 55, 7)

    # 1. Dashboard: KPIs, forecast, back-test
    kpis = (await client.get("/api/analytics/kpis")).json()
    assert kpis["open_deals"] == 80 and kpis["stalled_count"] == 6
    forecast = (await client.get("/api/analytics/forecast")).json()
    assert forecast["month"] == "2026-10"
    assert sum(len(c["deals"]) for r in forecast["by_rep"] for c in r["clients"]) == 55
    backtest = (await client.get("/api/analytics/forecast/backtest")).json()
    assert backtest["month"] == "2026-09" and backtest["team"]["actual"] >= 12

    # 2. Heatmap: Aarav and Bhavna match in AI / DevOps / Cloud Migration; Aarav strong in IoT
    cells = {
        (c["sales_person_id"], c["domain"]): c
        for c in (await client.get("/api/analytics/heatmap")).json()["cells"]
    }
    for domain in ("AI", "DevOps", "Cloud Migration"):
        assert cells[("SP-001", domain)]["win_rate"] == cells[("SP-002", domain)]["win_rate"]
    assert cells[("SP-001", "IoT")]["win_rate"] == 0.8
    assert cells[("SP-002", "IoT")]["handled"] == 0

    # 3. Graph explorer on SP-002: SIMILAR_TO link to SP-001
    graph = (await client.get("/api/graph/subgraph", params={"sales_person_id": "SP-002"})).json()
    similar = [link for link in graph["links"] if link["type"] == "SIMILAR_TO"]
    assert [{link["source"], link["target"]} for link in similar] == [{"SP-001", "SP-002"}]
    assert similar[0]["props"]["score"] == EXPECTED_SIMILAR_PAIRS[("SP-001", "SP-002")][1]

    # 4. New IoT client -> Bhavna (PEER); Aarav at capacity
    iot = (
        await client.post(
            "/api/clients", json=_client_body("Volt IoT Labs", "IoT", "Fleet telemetry platform")
        )
    ).json()
    a = iot["assignment"]
    assert a["assigned_to"]["id"] == PEER_SCENARIO["expected_assignee"]
    assert (
        a["candidates"][0]["fit_type"] == "PEER"
        and a["candidates"][0]["score"] == PEER_SCENARIO["expected_score"]
    )
    assert [c["sales_person_id"] for c in a["candidates"]] == PEER_SCENARIO["expected_top5"]
    assert {u["id"]: u["reason"] for u in a["unavailable"]} == PEER_SCENARIO["expected_unavailable"]

    # 5. New Cybersecurity client -> Chetan skipped (full), Divya assigned
    cyber = (
        await client.post(
            "/api/clients",
            json=_client_body("SecureNet", "Cybersecurity", "SOC monitoring service"),
        )
    ).json()
    c = cyber["assignment"]
    assert c["assigned_to"]["id"] == CAPACITY_SCENARIO["expected_assignee"]
    assert c["candidates"][0]["score"] == CAPACITY_SCENARIO["expected_score"]
    assert [x["sales_person_id"] for x in c["candidates"]] == CAPACITY_SCENARIO["expected_top5"]
    assert "SP-005" in {u["id"] for u in c["unavailable"]}

    # 6. Override the IoT deal to the runner-up
    deal_id = iot["deal"]["id"]
    override = (
        await client.post(
            f"/api/recommendations/{deal_id}/override", json={"sales_person_id": "SP-014"}
        )
    ).json()
    assert override["assigned_to"]["id"] == "SP-014"
    statuses = {r["sales_person_id"]: r["status"] for r in override["candidates"]}
    assert statuses["SP-002"] == "OVERRIDDEN" and statuses["SP-014"] == "ASSIGNED"
    assert await owner_ids_of(deal_id) == ["SP-014"]

    # The overridden deal now shows in Sana's graph, not Bhavna's
    sana = (await client.get("/api/graph/subgraph", params={"sales_person_id": "SP-014"})).json()
    assert deal_id in {n["id"] for n in sana["nodes"]}
    await assert_invariants_hold()

    # 7. Reset demo data again: back to the planted state
    again = await seed_test_db(api_app)
    assert again["counts"] == seed["counts"]
