"""GDS similarity comparison (fresh seed per module). Must not change Phase 6 behaviour."""

from __future__ import annotations

import httpx
import pytest

from app.core.db import run_read
from app.repositories import gds_repo
from app.seed.planted import EXPECTED_SIMILAR_PAIRS, PEER_SCENARIO
from app.services.gds_service import GRAPH_PREFIX
from tests.integration.helpers import new_client_body

pytestmark = pytest.mark.usefixtures("seeded")

ROW_FIELDS = {"rep_a", "rep_b", "rule_score", "rule_matched_domains", "gds_score"}


async def _compare(client: httpx.AsyncClient, **params: str) -> list[dict]:
    response = await client.get("/api/analytics/similarity-compare", params=params, timeout=180)
    assert response.status_code == 200, response.text
    return response.json()


async def _leftover_projections() -> list[str]:
    return [g for g in await gds_repo.list_graph_names() if g.startswith(GRAPH_PREFIX)]


async def test_compare_rows(client: httpx.AsyncClient) -> None:
    rows = await _compare(client)
    assert rows and all(set(r) == ROW_FIELDS for r in rows)
    assert all(r["rep_a"] < r["rep_b"] for r in rows)
    by_pair = {(r["rep_a"], r["rep_b"]): r for r in rows}
    assert len(by_pair) == len(rows)  # unordered pairs, no duplicates

    for pair, (match_count, score) in EXPECTED_SIMILAR_PAIRS.items():  # every rule pair present
        row = by_pair[pair]
        assert round(row["rule_score"], 2) == score
        assert len(row["rule_matched_domains"]) == match_count

    aarav_bhavna = by_pair[("SP-001", "SP-002")]
    assert aarav_bhavna["gds_score"] is not None and aarav_bhavna["gds_score"] > 0
    assert aarav_bhavna["gds_score"] == round(2.0 / 2.8, 4)  # weighted Jaccard by hand

    rule_only = [r for r in rows if r["rule_score"] is None]
    assert all(r["gds_score"] is not None for r in rule_only)  # extra rows come from GDS
    assert len(rows) <= len(EXPECTED_SIMILAR_PAIRS) + 20


async def test_sorted_by_gds_then_rule(client: httpx.AsyncClient) -> None:
    rows = await _compare(client)
    keys = [
        (r["gds_score"] is None, -(r["gds_score"] or 0), r["rule_score"] is None,
         -(r["rule_score"] or 0), r["rep_a"], r["rep_b"])
        for r in rows
    ]  # fmt: skip
    assert keys == sorted(keys)


async def test_no_projection_is_left_behind(client: httpx.AsyncClient) -> None:
    await _compare(client)
    await _compare(client)
    assert await _leftover_projections() == []


async def test_persist_only_updates_existing_edges(client: httpx.AsyncClient) -> None:
    before = (await run_read("RETURN COUNT { ()-[:SIMILAR_TO]->() } AS n"))[0]["n"]
    rows = await _compare(client, persist="true")
    edges = await run_read(
        "MATCH (a:SalesPerson)-[r:SIMILAR_TO]->(b:SalesPerson) "
        "RETURN a.id AS a, b.id AS b, r.gds_score AS gds_score"
    )
    assert len(edges) == before == 7  # no new SIMILAR_TO edges
    by_pair = {(r["rep_a"], r["rep_b"]): r["gds_score"] for r in rows}
    for edge in edges:
        assert edge["gds_score"] == by_pair[(edge["a"], edge["b"])]


async def test_assignment_unchanged_after_persist(client: httpx.AsyncClient) -> None:
    await _compare(client, persist="true")
    assignment = (await client.post("/api/clients", json=new_client_body())).json()["assignment"]
    assert assignment["assigned_to"]["id"] == PEER_SCENARIO["expected_assignee"]
    assert assignment["candidates"][0]["score"] == PEER_SCENARIO["expected_score"]
    assert [c["sales_person_id"] for c in assignment["candidates"]] == PEER_SCENARIO[
        "expected_top5"
    ]
    assert await _leftover_projections() == []
