"""Integration tests for GET /api/health against the test Neo4j."""

from __future__ import annotations

import httpx

from tests.conftest import TEST_AS_OF_DATE


async def test_health_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "ok"
    neo4j = body["neo4j"]
    assert neo4j["connected"] is True
    assert neo4j["edition"] == "community"
    assert neo4j["version"].startswith("5.26")
    assert neo4j["apoc_version"]
    assert neo4j["gds_version"]
    assert body["schema_ok"] is True
    assert body["as_of_date"] == TEST_AS_OF_DATE


async def test_unknown_api_route_returns_error_shape(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "NOT_FOUND", "message": "Not Found", "details": {}}
    }
