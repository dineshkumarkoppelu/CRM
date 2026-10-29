"""Integration tests for the EXPERTISE_IN / SIMILAR_TO recompute (fresh seed per module)."""

from __future__ import annotations

import httpx
import pytest

from app.core.db import run_read
from app.seed.planted import EXPECTED_EXPERTISE_EDGES, EXPECTED_SIMILAR_PAIRS
from app.seed.profiles import PROFILES
from tests.integration.helpers import TODAY, assert_invariants_hold

pytestmark = pytest.mark.usefixtures("seeded")

EXPERTISE_EDGES = """
MATCH (s:SalesPerson)-[e:EXPERTISE_IN]->(d:Domain)
RETURN s.id AS rep, d.name AS domain, e.handled AS handled, e.won AS won, e.lost AS lost,
       e.win_rate AS win_rate, e.qualifies AS qualifies, e.computed_at AS computed_at
ORDER BY rep, domain
"""

SIMILAR_EDGES = """
MATCH (a:SalesPerson)-[r:SIMILAR_TO]->(b:SalesPerson)
RETURN a.id AS rep_a, b.id AS rep_b, r.match_count AS match_count, r.score AS score,
       r.matched_domains AS matched_domains, r.mean_abs_diff AS mean_abs_diff
ORDER BY rep_a, rep_b
"""


async def test_expertise_edges_match_the_profile_table() -> None:
    edges = await run_read(EXPERTISE_EDGES)
    assert len(edges) == EXPECTED_EXPERTISE_EDGES == 55
    by_key = {(e["rep"], e["domain"]): e for e in edges}
    for p in PROFILES:
        for domain, (won, closed) in p.window.items():
            e = by_key[(p.id, domain)]
            assert (e["won"], e["handled"], e["lost"]) == (won, closed, closed - won)
            assert e["win_rate"] == round(won / closed, 4)
            assert e["qualifies"] is (closed >= 3)
            assert e["computed_at"] == TODAY


async def test_window_trap_has_no_cybersecurity_edge() -> None:
    rows = await run_read(
        "MATCH (:SalesPerson {id: 'SP-003'})-[e:EXPERTISE_IN]->(:Domain {name: 'Cybersecurity'}) "
        "RETURN count(e) AS n"
    )
    assert rows[0]["n"] == 0


async def test_similar_pairs_are_exactly_the_planted_7() -> None:
    edges = await run_read(SIMILAR_EDGES)
    got = {(e["rep_a"], e["rep_b"]): (e["match_count"], round(e["score"], 2)) for e in edges}
    assert got == EXPECTED_SIMILAR_PAIRS
    assert all(e["rep_a"] < e["rep_b"] for e in edges)  # lower id -> higher id
    aarav_bhavna = next(e for e in edges if e["rep_a"] == "SP-001")
    assert aarav_bhavna["matched_domains"] == ["AI", "DevOps", "Cloud Migration"]


async def test_recompute_endpoint_is_idempotent(client: httpx.AsyncClient) -> None:
    before = (await run_read(EXPERTISE_EDGES), await run_read(SIMILAR_EDGES))
    first = (await client.post("/api/admin/recompute")).json()
    second = (await client.post("/api/admin/recompute")).json()
    for result in (first, second):
        assert set(result) == {
            "expertise_edges", "similar_pairs", "related_pairs", "duration_ms", "computed_at",
        }  # fmt: skip
        assert (result["expertise_edges"], result["similar_pairs"]) == (55, 7)
        assert result["related_pairs"] == 10  # 5 built-in domains -> 10 unordered pairs
        assert result["computed_at"] == TODAY.isoformat()
    assert (await run_read(EXPERTISE_EDGES), await run_read(SIMILAR_EDGES)) == before


async def test_recompute_status(client: httpx.AsyncClient) -> None:
    await client.post("/api/admin/recompute")
    status = (await client.get("/api/admin/recompute/status")).json()
    assert status["last_run_at"] is not None
    assert status["last_result"]["expertise_edges"] == 55
    assert status["next_run_at"] is None  # scheduler disabled in tests


async def test_rep_detail_shows_expertise_and_peers(client: httpx.AsyncClient) -> None:
    bhavna = (await client.get("/api/salespeople/SP-002")).json()
    assert len(bhavna["expertise"]) == 5
    iot = next(e for e in bhavna["expertise"] if e["domain"] == "IoT")
    assert iot["handled"] == 0 and iot["win_rate"] is None and iot["qualifies"] is False
    assert [p["id"] for p in bhavna["similar_peers"]] == ["SP-001"]
    rahul = (await client.get("/api/salespeople/SP-013")).json()
    scores = [p["score"] for p in rahul["similar_peers"]]
    assert scores == sorted(scores, reverse=True)
    assert rahul["similar_peers"][0]["id"] == "SP-015"  # score 1.00


async def test_graph_invariants_still_hold() -> None:
    await assert_invariants_hold()
