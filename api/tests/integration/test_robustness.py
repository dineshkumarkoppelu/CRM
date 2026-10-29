"""Phase 9 robustness: request ids, BUSY guard, transaction timeouts, error shape per status."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from neo4j.exceptions import Neo4jError, ServiceUnavailable

from app.core import db
from app.repositories import analytics_repo
from app.seed.generator import SeedDataset
from app.services import analytics_service
from tests.integration.helpers import assert_error, new_client_body

pytestmark = pytest.mark.usefixtures("seeded")

SLEEP_QUERY = "CALL apoc.util.sleep($ms) RETURN 1 AS done"


# ---------------------------------------------------------------- request id


async def test_every_response_has_a_request_id(client: httpx.AsyncClient) -> None:
    ok = await client.get("/api/meta/domains")
    missing = await client.get("/api/deals/DL-9999")
    for response in (ok, missing):
        rid = response.headers.get("X-Request-ID")
        assert rid and len(rid) == 16
    assert ok.headers["X-Request-ID"] != missing.headers["X-Request-ID"]


async def test_safe_incoming_request_id_is_echoed(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/health", headers={"X-Request-ID": "demo-run_42.a"})
    assert response.headers["X-Request-ID"] == "demo-run_42.a"


async def test_unsafe_incoming_request_id_is_replaced(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/health", headers={"X-Request-ID": "bad id\r\nX-Evil: 1"})
    assert response.headers["X-Request-ID"] != "bad id\r\nX-Evil: 1"
    assert len(response.headers["X-Request-ID"]) == 16


# ---------------------------------------------------------------- BUSY guard


async def test_seed_and_recompute_cannot_overlap(client: httpx.AsyncClient) -> None:
    seed = asyncio.create_task(client.post("/api/admin/seed"))
    await asyncio.sleep(0.3)  # seed holds the lock from its first line
    second = await client.post("/api/admin/recompute")
    error = assert_error(second, 409, "BUSY")
    assert error["details"]["running"] == "seed"
    assert_error(await client.post("/api/admin/seed"), 409, "BUSY")
    assert (await seed).status_code == 200
    assert (await client.post("/api/admin/recompute")).status_code == 200  # free again


# ---------------------------------------------------------------- timeouts


async def test_transaction_timeout_is_enforced_by_the_server() -> None:
    token = db._tx_timeout.set(0.5)
    try:
        with pytest.raises(Neo4jError) as info:
            await db.run_read(SLEEP_QUERY, {"ms": 3000})
    finally:
        db._tx_timeout.reset(token)
    assert "TransactionTimedOut" in (info.value.code or "")


async def test_no_tx_timeout_exempts_long_work() -> None:
    token = db._tx_timeout.set(0.5)
    try:
        with db.no_tx_timeout():
            rows = await db.run_read(SLEEP_QUERY, {"ms": 1000})
    finally:
        db._tx_timeout.reset(token)
    assert rows == [{"done": 1}]


def test_default_timeouts() -> None:
    assert db.CONNECTION_TIMEOUT_S == 10.0
    assert db.TX_TIMEOUT_S == 15.0
    assert db._tx_timeout.get() == 15.0


# ---------------------------------------------------------------- error shape per status


async def test_400_illegal_stage_move(client: httpx.AsyncClient, dataset: SeedDataset) -> None:
    lost = next(d for d in dataset.deals if d["status"] == "LOST")
    response = await client.post(f"/api/deals/{lost['id']}/stage", json={"action": "ADVANCE"})
    assert_error(response, 400, "DEAL_CLOSED")


async def test_404_unknown_rep(client: httpx.AsyncClient) -> None:
    assert_error(await client.get("/api/salespeople/SP-404"), 404, "REP_NOT_FOUND")


async def test_409_override_to_full_rep(client: httpx.AsyncClient) -> None:
    body = await client.post("/api/clients", json=new_client_body(domain="AI"))
    deal_id = body.json()["deal"]["id"]
    response = await client.post(
        f"/api/recommendations/{deal_id}/override", json={"sales_person_id": "SP-005"}
    )
    assert_error(response, 409, "REP_NOT_AVAILABLE")


async def test_422_bad_body(client: httpx.AsyncClient) -> None:
    error = assert_error(
        await client.post("/api/activities", json={"type": "LUNCH"}), 422, "VALIDATION_ERROR"
    )
    assert error["details"]["errors"]


async def test_500_unexpected_error(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom() -> None:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(analytics_service, "get_funnel", boom)
    response = await client.get("/api/analytics/funnel")
    assert_error(response, 500, "INTERNAL_ERROR")
    assert response.headers.get("X-Request-ID")


async def test_503_database_unavailable(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def down(**_: object) -> None:
        raise ServiceUnavailable("connection refused")

    monkeypatch.setattr(analytics_repo, "funnel", down)
    assert_error(await client.get("/api/analytics/funnel"), 503, "NEO4J_UNAVAILABLE")


async def test_504_query_timeout(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def slow(**_: object) -> dict:
        token = db._tx_timeout.set(0.3)
        try:
            return (await db.run_read(SLEEP_QUERY, {"ms": 3000}))[0]
        finally:
            db._tx_timeout.reset(token)

    monkeypatch.setattr(analytics_repo, "funnel", slow)
    assert_error(await client.get("/api/analytics/funnel"), 504, "QUERY_TIMEOUT")
