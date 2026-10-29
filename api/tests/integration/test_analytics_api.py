"""Integration tests for /api/analytics (fresh seed, AS_OF_DATE = 2026-10-06)."""

from __future__ import annotations

import httpx
import pytest

from app.core.db import run_write
from app.core.domains import DOMAINS
from app.seed.profiles import PROFILES

pytestmark = pytest.mark.usefixtures("seeded")

STAGES = ["LEAD", "QUALIFIED", "PROPOSAL", "NEGOTIATION"]
DEMO_REPS = {"SP-001", "SP-002", "SP-005", "SP-006"}


async def _get(client: httpx.AsyncClient, path: str) -> dict | list:
    response = await client.get(f"/api/analytics/{path}")
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------- shapes


async def test_kpis_shape_and_values(client: httpx.AsyncClient) -> None:
    kpis = await _get(client, "kpis")
    assert set(kpis) == {
        "open_deals", "open_value", "won_this_month", "clients_converted_this_month",
        "win_rate_window", "avg_cycle_days", "avg_won_value", "stalled_count",
    }  # fmt: skip
    assert kpis["open_deals"] == 80
    assert kpis["won_this_month"] >= 8
    assert 1 <= kpis["clients_converted_this_month"] <= kpis["won_this_month"]
    assert kpis["stalled_count"] == 6
    assert 0 < kpis["win_rate_window"] < 1
    assert isinstance(kpis["avg_won_value"], int)


async def test_pipeline(client: httpx.AsyncClient) -> None:
    pipeline = await _get(client, "pipeline")
    assert set(pipeline) == {"reps", "unassigned_open_count"}
    assert pipeline["unassigned_open_count"] == 0
    reps = pipeline["reps"]
    assert len(reps) == 15
    by_id = {r["sales_person_id"]: r for r in reps}
    assert {pid: r["open_count"] for pid, r in by_id.items()} == {
        p.id: p.open_deals for p in PROFILES
    }
    assert by_id["SP-001"]["open_count"] == 8 and by_id["SP-002"]["open_count"] == 2
    assert by_id["SP-005"]["open_count"] == 8
    for row in reps:
        assert list(row["by_stage"]) == STAGES
        assert sum(row["by_stage"].values()) == row["open_count"]
    order = [(-r["open_count"], r["sales_person_id"]) for r in reps]
    assert order == sorted(order)


async def test_pipeline_counts_unassigned_and_skips_inactive(client: httpx.AsyncClient) -> None:
    body = {
        "client": {"name": "Pipeline Probe", "industry": "Retail", "size": "SMB", "region": "East"},
        "deal": {"title": "Probe", "value": 300000, "domain": "AI",
                 "expected_close_date": "2026-11-30"},
    }  # fmt: skip
    response = await client.post("/api/clients", json=body)
    assert response.status_code == 201
    # The engine assigns new deals since Phase 6; remove the owner to get an unassigned deal.
    await run_write(
        "MATCH (:SalesPerson)-[o:OWNS]->(:Deal {id: $id}) DELETE o",
        {"id": response.json()["deal"]["id"]},
    )
    await client.patch("/api/salespeople/SP-012", json={"active": False})
    try:
        pipeline = await _get(client, "pipeline")
        assert pipeline["unassigned_open_count"] == 1
        assert "SP-012" not in {r["sales_person_id"] for r in pipeline["reps"]}
        assert len(pipeline["reps"]) == 14
    finally:
        await client.patch("/api/salespeople/SP-012", json={"active": True})


async def test_win_rates(client: httpx.AsyncClient) -> None:
    body = await _get(client, "win-rates")
    assert len(body["by_rep"]) == 15
    assert [d["domain"] for d in body["by_domain"]] == list(DOMAINS)
    aarav = next(r for r in body["by_rep"] if r["sales_person_id"] == "SP-001")
    assert (aarav["won"], aarav["handled"]) == (28, 40)
    assert aarav["win_rate"] == 0.7
    assert sum(r["handled"] for r in body["by_rep"]) == 430


async def test_heatmap(client: httpx.AsyncClient) -> None:
    body = await _get(client, "heatmap")
    assert body["domains"] == list(DOMAINS)
    assert len(body["reps"]) == 15
    cells = {(c["sales_person_id"], c["domain"]): c for c in body["cells"]}
    assert len(body["cells"]) == len(cells) == 75

    iot = cells[("SP-001", "IoT")]
    assert (iot["handled"], iot["won"], iot["win_rate"], iot["qualifies"]) == (10, 8, 0.8, True)
    bhavna_iot = cells[("SP-002", "IoT")]
    assert bhavna_iot["handled"] == 0 and bhavna_iot["win_rate"] is None
    assert bhavna_iot["qualifies"] is False
    assert cells[("SP-003", "Cybersecurity")]["handled"] == 0  # window trap
    for p in PROFILES:  # every cell matches the profile table exactly
        for domain in DOMAINS:
            won, closed = p.window.get(domain, (0, 0))
            cell = cells[(p.id, domain)]
            assert (cell["won"], cell["handled"]) == (won, closed), (p.id, domain)


async def test_cycle(client: httpx.AsyncClient) -> None:
    body = await _get(client, "cycle")
    assert len(body["by_rep"]) == 15
    assert [d["domain"] for d in body["by_domain"]] == list(DOMAINS)
    for row in body["by_rep"] + body["by_domain"]:
        if row["won_count"]:
            assert 30 <= row["avg_cycle_days"] <= 150  # WON cycle range in the generator
        else:
            assert row["avg_cycle_days"] is None


async def test_stalled(client: httpx.AsyncClient) -> None:
    stalled = await _get(client, "stalled")
    assert len(stalled) == 6
    assert not {s["owner_id"] for s in stalled} & DEMO_REPS
    for row in stalled:
        assert row["days_since_activity"] > 21
        assert row["last_activity_date"] is not None
    days = [s["days_since_activity"] for s in stalled]
    assert days == sorted(days, reverse=True)


async def test_funnel(client: httpx.AsyncClient) -> None:
    body = await _get(client, "funnel")
    assert [s["stage"] for s in body["stages"]] == STAGES
    reached = [s["reached"] for s in body["stages"]]
    assert reached == sorted(reached, reverse=True)  # non-increasing
    assert body["stages"][0]["conversion_from_previous"] is None
    for prev, cur in zip(body["stages"], body["stages"][1:], strict=False):
        assert cur["conversion_from_previous"] == round(cur["reached"] / prev["reached"], 4)
    assert body["won"] + body["lost"] <= reached[0]


async def test_leaderboard(client: httpx.AsyncClient) -> None:
    body = await _get(client, "leaderboard")
    for period in ("month", "quarter"):
        rows = body[period]
        assert len(rows) == 15  # reps with 0 included
        key = [(-r["clients_converted"], -r["won_value"]) for r in rows]
        assert key == sorted(key)
    month = {r["sales_person_id"]: r for r in body["month"]}
    quarter = {r["sales_person_id"]: r for r in body["quarter"]}
    # 2026-10-06: the current month is the first month of Q4, so the two are identical.
    assert month == quarter
    assert sum(r["clients_converted"] for r in body["month"]) >= 8


async def test_domain_trend(client: httpx.AsyncClient) -> None:
    body = await _get(client, "domain-trend")
    assert len(body["months"]) == 12
    assert body["months"][0] == "2025-11" and body["months"][-1] == "2026-10"
    assert [s["domain"] for s in body["series"]] == list(DOMAINS)
    assert all(len(s["counts"]) == 12 for s in body["series"])
    assert sum(sum(s["counts"]) for s in body["series"]) > 0
