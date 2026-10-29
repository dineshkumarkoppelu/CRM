"""Small helpers shared by the API integration tests."""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx

from app.core.db import run_read
from tests.conftest import TEST_AS_OF_DATE
from tests.integration.graph_invariants import invariant_violations

TODAY = date.fromisoformat(TEST_AS_OF_DATE)
TODAY_ISO = TEST_AS_OF_DATE

DEAL_FIELDS = {
    "id", "title", "value", "status", "stage", "domain", "client_id", "client_name",
    "owner_id", "owner_name", "created_at", "qualified_at", "proposal_at", "negotiation_at",
    "expected_close_date", "closed_at",
}  # fmt: skip


def assert_error(response: httpx.Response, status: int, code: str) -> dict[str, Any]:
    """The response has the standard error shape with the given status and code."""
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == code, body
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]
    return body["error"]


async def owner_ids_of(deal_id: str) -> list[str]:
    rows = await run_read(
        "MATCH (s:SalesPerson)-[:OWNS]->(:Deal {id: $id}) RETURN s.id AS id", {"id": deal_id}
    )
    return [r["id"] for r in rows]


async def assert_invariants_hold() -> None:
    violations = await invariant_violations(TODAY)
    assert violations == {name: 0 for name in violations}


def new_client_body(**deal_overrides: Any) -> dict[str, Any]:
    deal = {
        "title": "Smart factory sensors",
        "value": 1_500_000,
        "domain": "IoT",
        "expected_close_date": "2026-11-20",
    }
    deal.update(deal_overrides)
    return {
        "client": {
            "name": "Acme Robotics",
            "industry": "Manufacturing",
            "size": "MID_MARKET",
            "region": "South",
        },
        "deal": deal,
    }
