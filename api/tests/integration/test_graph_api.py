"""GET /api/graph/subgraph (fresh seed per module)."""

from __future__ import annotations

import httpx
import pytest

from tests.integration.helpers import assert_error

pytestmark = pytest.mark.usefixtures("seeded")


async def _subgraph(client: httpx.AsyncClient, **params: str) -> dict:
    response = await client.get("/api/graph/subgraph", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _check_consistency(body: dict) -> None:
    ids = [n["id"] for n in body["nodes"]]
    assert len(ids) == len(set(ids))  # node ids unique
    for link in body["links"]:
        assert link["source"] in ids and link["target"] in ids


async def test_bhavna_subgraph_with_peer(client: httpx.AsyncClient) -> None:
    body = await _subgraph(client, sales_person_id="SP-002")
    _check_consistency(body)
    nodes = {n["id"]: n for n in body["nodes"]}
    assert nodes["SP-002"]["type"] == "SalesPerson" and nodes["SP-002"]["label"] == "Bhavna Rao"
    assert nodes["SP-001"]["type"] == "SalesPerson"  # the peer
    similar = [link for link in body["links"] if link["type"] == "SIMILAR_TO"]
    assert len(similar) == 1
    assert {similar[0]["source"], similar[0]["target"]} == {"SP-001", "SP-002"}
    assert similar[0]["props"]["score"] == 0.6

    deals = [n for n in body["nodes"] if n["type"] == "Deal"]
    assert 0 < len(deals) <= 100
    owns = [link for link in body["links"] if link["type"] == "OWNS"]
    assert len(owns) == len(deals) and all(link["source"] == "SP-002" for link in owns)
    expertise = [link for link in body["links"] if link["type"] == "EXPERTISE_IN"]
    assert {link["target"] for link in expertise} == {"AI", "DevOps", "Cloud Migration"}
    # Peers only, not their deals: every OWNS edge belongs to SP-002.
    assert {link["source"] for link in owns} == {"SP-002"}


async def test_deal_cap_and_consistency_for_every_rep(client: httpx.AsyncClient) -> None:
    for i in range(1, 16):
        body = await _subgraph(client, sales_person_id=f"SP-{i:03d}")
        _check_consistency(body)
        assert sum(n["type"] == "Deal" for n in body["nodes"]) <= 100


async def test_without_peers_and_status_filter(client: httpx.AsyncClient) -> None:
    body = await _subgraph(client, sales_person_id="SP-002", include_peers="false")
    assert not [link for link in body["links"] if link["type"] == "SIMILAR_TO"]
    assert "SP-001" not in {n["id"] for n in body["nodes"]}

    open_only = await _subgraph(client, sales_person_id="SP-001", deal_status="OPEN")
    deals = [n for n in open_only["nodes"] if n["type"] == "Deal"]
    assert len(deals) == 8 and all(n["props"]["status"] == "OPEN" for n in deals)


async def test_errors(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/graph/subgraph", params={"sales_person_id": "SP-999"})
    assert_error(response, 404, "REP_NOT_FOUND")
    assert_error(await client.get("/api/graph/subgraph"), 422, "VALIDATION_ERROR")
    response = await client.get(
        "/api/graph/subgraph", params={"sales_person_id": "SP-001", "deal_status": "PENDING"}
    )
    assert_error(response, 422, "VALIDATION_ERROR")
