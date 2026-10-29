"""Integration tests for schema init and the /api/meta endpoints (test Neo4j)."""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from app.core.domains import DOMAINS
from app.repositories import schema_repo
from app.schema import runner

EXPECTED_DOMAIN_ORDER = ["AI", "Cybersecurity", "IoT", "DevOps", "Cloud Migration"]


def test_init_cypher_parses_into_12_statements() -> None:
    # 5 constraints + 6 indexes + 1 MERGE of the domains; comments are stripped.
    statements = runner.parse_statements(runner.INIT_CYPHER_PATH.read_text(encoding="utf-8"))
    assert len(statements) == 12
    assert not any("//" in s for s in statements)
    assert all("IF NOT EXISTS" in s for s in statements[:11])


async def test_schema_is_complete_after_startup(api_app: FastAPI) -> None:
    assert await runner.check_schema() is True

    constraints = set(await schema_repo.list_constraint_names())
    indexes = set(await schema_repo.list_index_names())
    assert set(runner.EXPECTED_CONSTRAINTS) <= constraints
    assert set(runner.EXPECTED_INDEXES) <= indexes
    assert len(runner.EXPECTED_CONSTRAINTS) + len(runner.EXPECTED_INDEXES) == 11


async def test_runner_is_idempotent(api_app: FastAPI) -> None:
    assert await runner.apply_schema() == 12
    assert await runner.apply_schema() == 12  # second run: no error

    domains = await schema_repo.list_domain_names()
    assert sorted(domains) == sorted(DOMAINS)  # still exactly 5, no duplicates
    assert await runner.check_schema() is True


async def test_health_reports_schema_ok(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/health")).json()
    assert body["schema_ok"] is True
    assert body["status"] == "ok"


async def test_meta_domains_in_fixed_order(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/meta/domains")
    assert response.status_code == 200
    assert response.json() == EXPECTED_DOMAIN_ORDER


async def test_meta_config_is_grouped_like_the_yaml(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/meta/config")
    assert response.status_code == 200
    body = response.json()
    assert list(body) == [
        "analytics",
        "expertise",
        "similarity",
        "assignment",
        "forecast",
        "domains",
        "scheduler",
        "seed",
    ]
    assert body["assignment"]["weight_fit"] == 0.7
    assert body["similarity"]["similarity_tolerance"] == 0.1
    assert body["scheduler"]["recompute_cron"] == "0 2 * * *"
