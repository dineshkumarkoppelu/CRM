"""Adding domains (FRESH seed per test). Most tests use a fake embedder built from the stored
built-in vectors (fast, deterministic); one test runs the real local model."""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import httpx
import pytest
from fastapi import FastAPI

from app.core import embeddings
from app.core.db import run_read
from app.core.embeddings import EmbeddingsUnavailable, builtin_embeddings, normalise
from app.seed.planted import PEER_SCENARIO
from tests.conftest import seed_test_db
from tests.integration.helpers import assert_error, assert_invariants_hold, owner_ids_of

EDGE = {
    "name": "Edge Computing",
    "description": "Processing data on devices and gateways close to sensors; low-latency "
    "analytics at the edge of the network.",
}


class FakeEmbedder:
    """'Edge Computing' = mostly IoT plus some Cloud Migration; anything else = DevOps."""

    model_name = "BAAI/bge-small-en-v1.5"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        v = builtin_embeddings()["vectors"]
        out = []
        for text in texts:
            if text.startswith("Edge Computing"):
                mix = [
                    0.9 * a + 0.35 * b for a, b in zip(v["IoT"], v["Cloud Migration"], strict=True)
                ]
            else:
                mix = list(v["DevOps"])
            out.append(normalise(mix))
        return out


class BrokenEmbedder:
    model_name = "BAAI/bge-small-en-v1.5"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        raise EmbeddingsUnavailable("offline")


@pytest.fixture(autouse=True)
async def fresh(api_app: FastAPI) -> None:
    await seed_test_db(api_app)


@pytest.fixture
def fake_embedder() -> Iterator[None]:
    embeddings.set_embedder(FakeEmbedder())
    yield
    embeddings.set_embedder(None)


def _deal(domain: str, name: str = "Gateway Systems") -> dict:
    return {
        "client": {"name": name, "industry": "Retail", "size": "ENTERPRISE", "region": "West"},
        "deal": {"title": "Edge analytics rollout", "value": 3_000_000, "domain": domain,
                 "expected_close_date": "2026-12-15"},
    }  # fmt: skip


async def _add(client: httpx.AsyncClient, body: dict = EDGE) -> httpx.Response:
    return await client.post("/api/domains", json=body, timeout=300)


@pytest.mark.usefixtures("fake_embedder")
async def test_add_domain_links_it_to_similar_domains(client: httpx.AsyncClient) -> None:
    response = await _add(client)
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["name"], body["builtin"]) == ("Edge Computing", False)
    assert body["related"][0]["domain"] == "IoT"  # most similar first
    assert body["related"][0]["used_for_fit"] is True
    assert len(body["related"]) == 5

    names = (await client.get("/api/meta/domains")).json()
    assert names == ["AI", "Cybersecurity", "IoT", "DevOps", "Cloud Migration", "Edge Computing"]
    rows = await run_read("RETURN COUNT { ()-[:RELATED_TO]->() } AS n")
    assert rows[0]["n"] == 15  # 6 domains -> 15 unordered pairs
    await assert_invariants_hold()


@pytest.mark.usefixtures("fake_embedder")
async def test_new_domain_deal_is_routed_with_related_fit(client: httpx.AsyncClient) -> None:
    await _add(client)
    created = (await client.post("/api/clients", json=_deal("Edge Computing"))).json()
    a = created["assignment"]
    assert a["assignment_status"] == "ASSIGNED" and a["domain"] == "Edge Computing"
    top = a["candidates"][0]
    assert top["fit_type"] == "RELATED"
    assert top["reason"].startswith("RELATED fit: no track record in Edge Computing yet")
    # The top rep may win on availability; IoT (the closest domain) experience must count.
    assert any("of IoT (similarity" in c["reason"] for c in a["candidates"])
    assert all(c["fit_type"] == "RELATED" for c in a["candidates"])
    assert {u["id"] for u in a["unavailable"]} == {"SP-001", "SP-005"}
    assert await owner_ids_of(created["deal"]["id"]) == [a["assigned_to"]["id"]]
    stored = await run_read(
        "MATCH (:Deal {id: $id})-[r:RECOMMENDED_TO]->() RETURN count(r) AS n",
        {"id": created["deal"]["id"]},
    )
    assert stored[0]["n"] == 5


@pytest.mark.usefixtures("fake_embedder")
async def test_similarity_rule_adjusts_to_the_new_domain_count(client: httpx.AsyncClient) -> None:
    before = (await client.get("/api/salespeople/SP-001")).json()["similar_peers"][0]["score"]
    await _add(client)
    after = (await client.get("/api/salespeople/SP-001")).json()
    assert (before, after["similar_peers"][0]["score"]) == (0.6, 0.5)  # 3/5 -> 3/6 matched
    assert [e["domain"] for e in after["expertise"]][-1] == "Edge Computing"
    heatmap = (await client.get("/api/analytics/heatmap")).json()
    assert len(heatmap["domains"]) == 6 and len(heatmap["cells"]) == 90

    # The planted PEER scenario is unchanged: one peer, so the weighted fit is the same.
    iot = (await client.post("/api/clients", json=_deal("IoT", "Volt IoT Labs"))).json()
    assert iot["assignment"]["assigned_to"]["id"] == PEER_SCENARIO["expected_assignee"]
    assert iot["assignment"]["candidates"][0]["score"] == PEER_SCENARIO["expected_score"]


@pytest.mark.usefixtures("fake_embedder")
async def test_validation_and_duplicates(client: httpx.AsyncClient) -> None:
    assert (await _add(client)).status_code == 201
    dup = await _add(client, {**EDGE, "name": "edge computing"})
    assert_error(dup, 409, "DOMAIN_EXISTS")
    assert_error(await _add(client, {**EDGE, "name": "IoT"}), 409, "DOMAIN_EXISTS")
    for body in (
        {**EDGE, "name": "X"},
        {**EDGE, "name": "Bad<script>"},
        {**EDGE, "description": "short"},
    ):
        assert_error(await _add(client, body), 422, "VALIDATION_ERROR")
    assert_error(await client.post("/api/clients", json=_deal("Quantum")), 422, "VALIDATION_ERROR")


@pytest.mark.usefixtures("fake_embedder")
async def test_domain_names_are_case_insensitive_for_deals(client: httpx.AsyncClient) -> None:
    await _add(client)
    created = (await client.post("/api/clients", json=_deal("edge computing"))).json()
    assert created["deal"]["domain"] == "Edge Computing"


async def test_embedding_model_unavailable_gives_503(client: httpx.AsyncClient) -> None:
    embeddings.set_embedder(BrokenEmbedder())
    try:
        assert_error(await _add(client), 503, "EMBEDDINGS_UNAVAILABLE")
    finally:
        embeddings.set_embedder(None)
    names = (await client.get("/api/meta/domains")).json()
    assert "Edge Computing" not in names  # nothing was written


@pytest.mark.usefixtures("fake_embedder")
async def test_reset_removes_added_domains(api_app: FastAPI, client: httpx.AsyncClient) -> None:
    await _add(client)
    await seed_test_db(api_app)
    assert len((await client.get("/api/meta/domains")).json()) == 5


async def test_real_local_model_finds_the_right_neighbours(client: httpx.AsyncClient) -> None:
    """The actual embedding model (loaded from api/.models, downloaded on first use)."""
    response = await _add(client)
    assert response.status_code == 201, response.text
    related = response.json()["related"]
    assert related[0]["domain"] == "IoT"
    assert {r["domain"] for r in related if r["used_for_fit"]} >= {"IoT"}
    created = (await client.post("/api/clients", json=_deal("Edge Computing"))).json()
    assert created["assignment"]["candidates"][0]["fit_type"] == "RELATED"
