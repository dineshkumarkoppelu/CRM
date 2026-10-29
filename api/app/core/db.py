"""Neo4j driver lifecycle and query helpers.

Exactly one AsyncDriver per process: created in the FastAPI lifespan (`init_driver`) and
closed on shutdown (`close_driver`). Repositories run their Cypher through `run_read` /
`run_write`, which use managed transactions.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from neo4j import (
    AsyncDriver,
    AsyncGraphDatabase,
    AsyncManagedTransaction,
    AsyncSession,
    NotificationDisabledCategory,
    Query,
    unit_of_work,
)
from neo4j.exceptions import DriverError, Neo4jError
from neo4j.time import Date as Neo4jDate
from neo4j.time import DateTime as Neo4jDateTime

from app.core.settings import Settings

logger = logging.getLogger(__name__)

# Community Edition has exactly one user database.
DATABASE = "neo4j"

STARTUP_CONNECT_TIMEOUT_S = 30.0
STARTUP_RETRY_INTERVAL_S = 2.0

# Phase 9 robustness: socket connect timeout, and a server-side timeout for every transaction.
CONNECTION_TIMEOUT_S = 10.0
TX_TIMEOUT_S = 15.0

# Long-running admin work (seed, recompute, GDS comparison) runs inside `no_tx_timeout()`.
_tx_timeout: ContextVar[float | None] = ContextVar("tx_timeout", default=TX_TIMEOUT_S)

_driver: AsyncDriver | None = None


@contextmanager
def no_tx_timeout() -> Iterator[None]:
    """Exempt the queries run inside this block (same task) from the 15 s transaction timeout."""
    token = _tx_timeout.set(None)
    try:
        yield
    finally:
        _tx_timeout.reset(token)


def _timed[F](work: F) -> F:
    """Attach the current transaction timeout to a transaction function."""
    timeout = _tx_timeout.get()
    return unit_of_work(timeout=timeout)(work) if timeout is not None else work  # type: ignore[return-value]


# Errors meaning "Neo4j is not reachable right now". Besides driver errors, the driver raises
# a plain ValueError ("Cannot resolve address ...") when the host name does not resolve.
CONNECTIVITY_ERRORS: tuple[type[Exception], ...] = (DriverError, Neo4jError, OSError, ValueError)


async def init_driver(settings: Settings) -> bool:
    """Create the process-wide driver and wait (up to 30 s) for Neo4j to accept connections.

    Returns True if Neo4j answered. If it is still unreachable after the wait, the API starts
    anyway in a degraded state: the driver reconnects on its own once Neo4j is back, and
    /api/health reports the outage.
    """
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
            connection_timeout=CONNECTION_TIMEOUT_S,
            # Queries on derived edges (EXPERTISE_IN, SIMILAR_TO, RECOMMENDED_TO) legitimately
            # run before those edges exist (fresh seed, before the first recompute). Neo4j then
            # warns "unknown relationship type / property" on every call; silence only that
            # category. Other categories (deprecations, performance hints) stay on.
            notifications_disabled_categories=[NotificationDisabledCategory.UNRECOGNIZED],
        )
    return await wait_for_connectivity(_driver)


async def wait_for_connectivity(
    driver: AsyncDriver,
    timeout_s: float = STARTUP_CONNECT_TIMEOUT_S,
    interval_s: float = STARTUP_RETRY_INTERVAL_S,
) -> bool:
    """Retry `verify_connectivity()` until it succeeds or `timeout_s` elapses."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    attempt = 0
    while True:
        attempt += 1
        try:
            await driver.verify_connectivity()
            logger.info("Connected to Neo4j (attempt %d)", attempt)
            return True
        except CONNECTIVITY_ERRORS as exc:
            if loop.time() + interval_s > deadline:
                logger.warning(
                    "Neo4j not reachable after %.0f s (%s). Starting in degraded mode.",
                    timeout_s,
                    exc,
                )
                return False
            logger.info("Waiting for Neo4j (attempt %d): %s", attempt, exc)
            await asyncio.sleep(interval_s)


async def close_driver() -> None:
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None


def get_driver() -> AsyncDriver:
    if _driver is None:
        raise RuntimeError("Neo4j driver is not initialised (app lifespan not started)")
    return _driver


async def is_connected() -> bool:
    """True if a Bolt connection can be established right now."""
    try:
        await get_driver().verify_connectivity()
        return True
    except CONNECTIVITY_ERRORS as exc:
        logger.warning("Neo4j connectivity check failed: %s", exc)
        return False


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an async session on the default database."""
    async with get_driver().session(database=DATABASE) as session:
        yield session


def to_native(value: Any) -> Any:
    """Convert neo4j.time values (recursively) to Python `datetime` objects.

    Repositories always hand plain Python types (e.g. `datetime.date`) to the rest of the app.
    """
    if isinstance(value, (Neo4jDate, Neo4jDateTime)):
        return value.to_native()
    if isinstance(value, dict):
        return {key: to_native(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_native(item) for item in value]
    return value


async def _collect(
    tx: AsyncManagedTransaction, query: str, params: dict[str, Any]
) -> list[dict[str, Any]]:
    result = await tx.run(query, params)
    return [to_native(record.data()) async for record in result]


async def tx_run(
    tx: AsyncManagedTransaction, query: str, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Run one statement inside a transaction function (see `run_in_write_tx`)."""
    return await _collect(tx, query, params or {})


async def run_in_write_tx[T](work: Callable[[AsyncManagedTransaction], Awaitable[T]]) -> T:
    """Run several statements as ONE managed write transaction (all commit or none).

    `work(tx)` calls `tx_run(tx, ...)` for each statement. The driver may retry `work` on
    transient errors, so it must not have side effects outside the transaction.
    """
    async with get_driver().session(database=DATABASE) as session:
        return await session.execute_write(_timed(work))


async def run_read(query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Run a parameterised read query in a managed read transaction."""
    async with get_driver().session(database=DATABASE) as session:
        return await session.execute_read(_timed(_collect), query, params or {})


async def run_write(query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Run a parameterised write query in a managed write transaction."""
    async with get_driver().session(database=DATABASE) as session:
        return await session.execute_write(_timed(_collect), query, params or {})


async def run_auto_commit(query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Run one statement in an auto-commit transaction (`session.run`).

    Only for statements that cannot run in a managed transaction: schema commands
    (CREATE CONSTRAINT / INDEX) and `CALL { ... } IN TRANSACTIONS` (tech.md).
    """
    async with get_driver().session(database=DATABASE) as session:
        result = await session.run(Query(query, timeout=_tx_timeout.get()), params or {})
        return [to_native(record.data()) async for record in result]
