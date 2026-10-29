"""Integration tests for POST /api/admin/seed against the test Neo4j (AS_OF_DATE=2026-10-06)."""

from __future__ import annotations

from datetime import date

from fastapi import FastAPI

from app.core.clock import subtract_months
from app.core.db import run_read
from tests.conftest import TEST_AS_OF_DATE, seed_test_db
from tests.integration.graph_invariants import invariant_violations

TODAY = date.fromisoformat(TEST_AS_OF_DATE)
WINDOW_START = subtract_months(TODAY, 12)  # exclusive

WINDOW_CELL = """
MATCH (s:SalesPerson {id: $rep})-[:OWNS]->(d:Deal)-[:IN_DOMAIN]->(:Domain {name: $domain})
WHERE d.status IN ['WON', 'LOST'] AND d.closed_at > $window_start AND d.closed_at <= $today
RETURN count(d) AS closed, count(CASE WHEN d.status = 'WON' THEN 1 END) AS won
"""

DEAL_SNAPSHOT = """
MATCH (s:SalesPerson)-[:OWNS]->(d:Deal)-[:FOR_CLIENT]->(c:Client)
RETURN d.id AS id, d.title AS title, d.value AS value, d.status AS status, d.stage AS stage,
       d.created_at AS created_at, d.closed_at AS closed_at, s.id AS owner, c.id AS client
ORDER BY id
"""


async def _window_cell(rep: str, domain: str) -> tuple[int, int]:
    rows = await run_read(
        WINDOW_CELL,
        {"rep": rep, "domain": domain, "window_start": WINDOW_START, "today": TODAY},
    )
    return rows[0]["won"], rows[0]["closed"]


async def test_seed_response_counts(seeded: dict) -> None:
    counts = seeded["counts"]
    assert counts["SalesPerson"] == 15
    assert counts["Deal"] == 695
    assert counts["Domain"] == 5
    assert counts["OWNS"] == 695
    assert counts["FOR_CLIENT"] == 695
    assert counts["IN_DOMAIN"] == 695
    assert 320 <= counts["Client"] <= 400
    assert counts["Activity"] > 0
    assert counts["PERFORMED"] == counts["Activity"]
    assert counts["ON_DEAL"] == counts["Activity"]
    assert seeded["as_of_date"] == TEST_AS_OF_DATE
    assert seeded["expertise_edges"] == 55  # Phase 6: seed also recomputes
    assert seeded["similar_pairs"] == 7
    assert seeded["seed"] == 42
    assert seeded["duration_ms"] > 0


async def test_all_graph_invariants_hold(seeded: dict) -> None:
    violations = await invariant_violations(TODAY)
    assert violations == {name: 0 for name in violations}


async def test_live_window_query_matches_profile_table(seeded: dict) -> None:
    assert await _window_cell("SP-001", "IoT") == (8, 10)
    assert await _window_cell("SP-005", "Cybersecurity") == (9, 10)
    assert await _window_cell("SP-003", "Cybersecurity") == (0, 0)  # window trap


async def test_window_trap_deals_exist_outside_the_window(seeded: dict) -> None:
    rows = await run_read(
        """
        MATCH (:SalesPerson {id: 'SP-003'})-[:OWNS]->(d:Deal)-[:IN_DOMAIN]->
              (:Domain {name: 'Cybersecurity'})
        RETURN count(d) AS n, count(CASE WHEN d.status = 'WON' THEN 1 END) AS won,
               max(d.closed_at) AS latest
        """
    )
    assert rows[0]["n"] == 5
    assert rows[0]["won"] == 4
    assert rows[0]["latest"] <= WINDOW_START  # repositories return Python dates


async def test_schema_still_complete_after_seed(seeded: dict, api_app: FastAPI) -> None:
    from app.schema import runner

    assert await runner.check_schema() is True


async def test_reseed_gives_identical_data(seeded: dict, api_app: FastAPI) -> None:
    before = await run_read(DEAL_SNAPSHOT)
    second = await seed_test_db(api_app)
    after = await run_read(DEAL_SNAPSHOT)

    assert second["counts"] == seeded["counts"]
    assert len(after) == 695
    assert after == before  # same ids, values, dates, owners and clients
