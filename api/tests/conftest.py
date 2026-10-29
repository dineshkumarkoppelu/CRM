"""Shared fixtures.

Integration tests always run against the separate TEST Neo4j instance (Bolt port 7688,
`TEST_NEO4J_URI`), never the dev database. If it is not reachable they are skipped.
"""

from __future__ import annotations

import socket
from collections.abc import AsyncIterator
from datetime import date
from urllib.parse import urlparse

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from app.core.settings import get_settings
from app.seed.generator import SeedDataset, generate

DEFAULT_TEST_NEO4J_URI = "bolt://localhost:7688"
TEST_AS_OF_DATE = "2026-10-06"
START_HINT = (
    r"start the test instance in another terminal: C:\neo4j\test\bin\neo4j.bat console "
    "(see README.md, 'Neo4j setup')"
)


def _port_open(uri: str, timeout_s: float = 2.0) -> bool:
    parsed = urlparse(uri)
    host, port = parsed.hostname or "localhost", parsed.port or 7687
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def test_neo4j_uri() -> str:
    get_settings.cache_clear()
    try:
        settings = get_settings()
    except ValidationError as exc:
        pytest.skip(f"Settings incomplete (copy api/.env.example to api/.env): {exc}")
    uri = settings.TEST_NEO4J_URI or DEFAULT_TEST_NEO4J_URI
    if not _port_open(uri):
        pytest.skip(f"Test Neo4j not reachable at {uri} - {START_HINT}")
    return uri


@pytest.fixture(scope="session")
async def api_app(test_neo4j_uri: str) -> AsyncIterator[FastAPI]:
    """The FastAPI app wired to the TEST database, with its lifespan running."""
    mp = pytest.MonkeyPatch()
    mp.setenv("NEO4J_URI", test_neo4j_uri)
    mp.setenv("SCHEDULER_ENABLED", "false")
    mp.setenv("AS_OF_DATE", TEST_AS_OF_DATE)
    get_settings.cache_clear()
    # Safety net: never let tests touch the dev database.
    assert get_settings().NEO4J_URI == test_neo4j_uri

    from app.main import create_app

    application = create_app()
    try:
        # httpx's ASGITransport does not run the lifespan, so run it explicitly.
        async with application.router.lifespan_context(application):
            yield application
    finally:
        mp.undo()
        get_settings.cache_clear()


def _http_client(api_app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=api_app)
    return httpx.AsyncClient(transport=transport, base_url="http://test", timeout=180)


@pytest.fixture
async def client(api_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with _http_client(api_app) as http_client:
        yield http_client


@pytest.fixture(scope="session")
def dataset() -> SeedDataset:
    """The exact dataset the seed endpoint loads in tests (seed 42, AS_OF_DATE 2026-10-06),
    so tests can compute expected counts independently of the API."""
    return generate(
        seed=42, today=date.fromisoformat(TEST_AS_OF_DATE), lookback_months=12, capacity=8
    )


async def seed_test_db(api_app: FastAPI) -> dict:
    """POST /api/admin/seed on the TEST database and return the JSON body."""
    async with _http_client(api_app) as http_client:
        response = await http_client.post("/api/admin/seed")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture(scope="module")
async def seeded(api_app: FastAPI) -> dict:
    """A freshly seeded test database for the whole test module (AS_OF_DATE = 2026-10-06)."""
    return await seed_test_db(api_app)
