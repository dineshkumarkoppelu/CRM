"""Integration tests for the forecast and back-test (fresh seed, AS_OF_DATE = 2026-10-06)."""

from __future__ import annotations

import math

import httpx
import pytest

from app.core.db import run_read

pytestmark = pytest.mark.usefixtures("seeded")

SOURCES = {"REP_DOMAIN_STAGE", "TEAM_DOMAIN_STAGE", "TEAM_STAGE"}


async def _get(client: httpx.AsyncClient, path: str) -> dict:
    response = await client.get(f"/api/analytics/{path}")
    assert response.status_code == 200, response.text
    return response.json()


async def test_forecast_shape_and_values(client: httpx.AsyncClient) -> None:
    body = await _get(client, "forecast")
    assert body["month"] == "2026-10"
    assert set(body["team"]) == {
        "expected_conversions", "commit", "best_case", "expected_revenue", "converted_so_far",
    }  # fmt: skip
    assert body["team"]["commit"] <= body["team"]["best_case"]
    assert len(body["by_rep"]) == 15  # all active reps

    expected = [r["expected_conversions"] for r in body["by_rep"]]
    assert expected == sorted(expected, reverse=True)

    for rep in body["by_rep"]:
        assert rep["commit"] <= rep["best_case"] <= len(rep["clients"])
        if rep["clients"]:
            assert rep["expected_conversions"] > 0
        probabilities = [c["probability"] for c in rep["clients"]]
        assert probabilities == sorted(probabilities, reverse=True)
        for c in rep["clients"]:
            assert 0 <= c["probability"] <= 1
            for d in c["deals"]:
                assert 0 <= d["p_deal"] <= 1
                assert d["probability_source"] in SOURCES


async def test_in_scope_deals_match_open_october_deals(client: httpx.AsyncClient) -> None:
    body = await _get(client, "forecast")
    in_scope = sum(len(c["deals"]) for r in body["by_rep"] for c in r["clients"])
    rows = await run_read(
        """MATCH (:SalesPerson)-[:OWNS]->(d:Deal {status: 'OPEN'})
           WHERE d.expected_close_date >= date('2026-10-01')
             AND d.expected_close_date <= date('2026-10-31')
           RETURN count(d) AS n"""
    )
    assert in_scope == rows[0]["n"] == 55


async def test_converted_so_far_matches_kpis(client: httpx.AsyncClient) -> None:
    forecast = await _get(client, "forecast")
    kpis = await _get(client, "kpis")
    assert forecast["team"]["converted_so_far"] == kpis["clients_converted_this_month"]
    assert (
        sum(r["converted_so_far"] for r in forecast["by_rep"])
        >= kpis["clients_converted_this_month"]
    )


async def test_backtest(client: httpx.AsyncClient) -> None:
    body = await _get(client, "forecast/backtest")
    assert body["month"] == "2026-09" and body["asof"] == "2026-09-01"
    assert body["team"]["actual"] >= 12  # planted: >= 12 distinct clients converted
    assert math.isfinite(body["mean_abs_error"]) and body["mean_abs_error"] >= 0
    assert body["team"]["predicted_expected"] > 0
    assert len(body["by_rep"]) == 15
    for row in body["by_rep"]:
        assert row["abs_error"] == pytest.approx(
            abs(row["predicted_expected"] - row["actual"]), abs=0.011
        )
    assert body["limitations"] == [
        "Owner history is not tracked; current owner is used.",
        "Expected close date history is not tracked; final value is used.",
    ]
