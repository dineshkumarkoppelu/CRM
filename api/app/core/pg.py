"""Postgres connection pool lifecycle.

Exactly one asyncpg pool per process: created in the FastAPI lifespan (`init_pool`) and closed
on shutdown (`close_pool`). Postgres holds the raw CRM rows; Neo4j is loaded from it.
"""

from __future__ import annotations

import asyncio
import logging

import asyncpg

from app.core.errors import AppError
from app.core.settings import Settings, get_settings

logger = logging.getLogger(__name__)

STARTUP_CONNECT_TIMEOUT_S = 30.0
STARTUP_RETRY_INTERVAL_S = 2.0
CONNECTION_TIMEOUT_S = 10.0

# Tags every connection of this app. The change triggers skip rows written under this name
# (the app already wrote them to Neo4j itself); everything else is pushed to Neo4j.
APP_NAME = "crm-app"
SERVER_SETTINGS = {"application_name": APP_NAME}

# Errors meaning "Postgres is not reachable right now".
CONNECTIVITY_ERRORS: tuple[type[Exception], ...] = (
    asyncpg.PostgresError,
    asyncpg.InterfaceError,
    OSError,
    TimeoutError,
)

_pool: asyncpg.Pool | None = None


async def init_pool(settings: Settings) -> bool:
    """Create the process-wide pool, waiting (up to 30 s) for Postgres to accept connections.

    Returns True if Postgres answered; False if it is still unreachable (the API then starts
    degraded and `get_pool` tries again on the next use).
    """
    global _pool
    if _pool is not None:
        return True
    loop = asyncio.get_running_loop()
    deadline = loop.time() + STARTUP_CONNECT_TIMEOUT_S
    attempt = 0
    while True:
        attempt += 1
        try:
            _pool = await asyncpg.create_pool(
                settings.POSTGRES_URL,
                min_size=1,
                max_size=5,
                timeout=CONNECTION_TIMEOUT_S,
                server_settings=SERVER_SETTINGS,
            )
            logger.info("Connected to Postgres (attempt %d)", attempt)
            return True
        except CONNECTIVITY_ERRORS as exc:
            if loop.time() + STARTUP_RETRY_INTERVAL_S > deadline:
                logger.warning(
                    "Postgres not reachable after %.0f s (%s). Starting in degraded mode.",
                    STARTUP_CONNECT_TIMEOUT_S,
                    exc,
                )
                return False
            logger.info("Waiting for Postgres (attempt %d): %s", attempt, exc)
            await asyncio.sleep(STARTUP_RETRY_INTERVAL_S)


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def get_pool() -> asyncpg.Pool:
    """The pool; if startup could not reach Postgres, connect now (raises if still down)."""
    global _pool
    if _pool is None:
        try:
            _pool = await asyncpg.create_pool(
                get_settings().POSTGRES_URL,
                min_size=1,
                max_size=5,
                timeout=CONNECTION_TIMEOUT_S,
                server_settings=SERVER_SETTINGS,
            )
        except CONNECTIVITY_ERRORS as exc:
            logger.warning("Postgres connection failed: %s", exc)
            raise AppError("POSTGRES_UNAVAILABLE", "Postgres is not reachable", 503) from exc
    return _pool
