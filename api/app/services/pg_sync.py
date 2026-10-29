"""Live Postgres -> Neo4j sync for changes made outside this app (psql, scripts, other tools).

Postgres triggers send a small notification (table, operation, id) for every row change that was
not made by this app. A background task listens for them, reads the current rows from Postgres
and upserts (or deletes) the matching nodes in Neo4j within a moment. Changes the app makes
itself are written to Neo4j directly by the app, so the triggers skip them.

Only the stored data is synced. EXPERTISE_IN / SIMILAR_TO / RECOMMENDED_TO are not touched here;
they are rebuilt by the usual recompute.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

import asyncpg

from app.core import pg
from app.core.settings import get_settings
from app.repositories import postgres_repo, seed_repo
from app.services import live_refresh

logger = logging.getLogger(__name__)

# Held while rows are written to Neo4j by a sync or a seed, so two of them never interleave.
LOCK = asyncio.Lock()

DEBOUNCE_S = 0.2  # gather a burst of notifications into one batch
KEEPALIVE_S = 30.0  # detect a dropped listener connection
RETRY_S = 5.0
MAX_ATTEMPTS = 3

# Parents before children (deals need their client and owner, activities need their deal).
TABLE_ORDER = ("sales_people", "clients", "deals", "activities")
_LOADERS = {
    "sales_people": seed_repo.load_sales_people,
    "clients": seed_repo.load_clients,
    "deals": seed_repo.load_deals,
    "activities": seed_repo.load_activities,
}

_task: asyncio.Task[None] | None = None
_pending: dict[str, dict[str, str]] = {}  # table -> {id: "UPSERT" | "DELETE"}
_wake = asyncio.Event()


def _on_notify(_conn: Any, _pid: int, _channel: str, payload: str) -> None:
    try:
        change = json.loads(payload)
        table, row_id = change["table"], str(change["id"])
        op = "DELETE" if change["op"] == "DELETE" else "UPSERT"
    except (ValueError, KeyError, TypeError):
        logger.warning("Ignoring unreadable Postgres notification: %r", payload)
        return
    if table in TABLE_ORDER:
        _pending.setdefault(table, {})[row_id] = op  # the latest operation per row wins
        _wake.set()


async def _apply(batch: dict[str, dict[str, str]]) -> None:
    """Bring Neo4j in line with the rows named in `batch`."""
    upserted = deleted = 0
    async with LOCK:
        for table in TABLE_ORDER:
            ids = [i for i, op in batch.get(table, {}).items() if op == "UPSERT"]
            if not ids:
                continue
            rows = await postgres_repo.fetch_rows(table, ids)
            if rows:
                await _LOADERS[table](rows)
            gone = sorted(set(ids) - {row["id"] for row in rows})  # deleted again since
            if gone:
                await seed_repo.delete_nodes(table, gone)
            upserted += len(rows)
            deleted += len(gone)
        for table in reversed(TABLE_ORDER):
            ids = [i for i, op in batch.get(table, {}).items() if op == "DELETE"]
            if ids:
                await seed_repo.delete_nodes(table, ids)
                deleted += len(ids)
    logger.info("Synced Postgres changes to Neo4j: %d upserted, %d deleted", upserted, deleted)
    live_refresh.request()


async def _flush() -> None:
    global _pending
    batch, _pending = _pending, {}
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            await _apply(batch)
            return
        except Exception:
            logger.exception("Postgres -> Neo4j sync failed (attempt %d)", attempt)
            await asyncio.sleep(RETRY_S)
    logger.error("Dropped a batch of Postgres changes after %d failed attempts", MAX_ATTEMPTS)


async def sync_all() -> None:
    """Upsert every Postgres row into Neo4j (catches up changes missed while not listening)."""
    async with LOCK:
        data = await postgres_repo.read_dataset()
        await seed_repo.load_sales_people(data.sales_people)
        await seed_repo.load_clients(data.clients)
        await seed_repo.load_deals(data.deals)
        await seed_repo.load_activities(data.activities)
    logger.info(
        "Caught up Neo4j from Postgres: %d deals, %d clients, %d activities",
        len(data.deals),
        len(data.clients),
        len(data.activities),
    )
    live_refresh.request()


async def _listen_once() -> None:
    conn = await asyncpg.connect(
        get_settings().POSTGRES_URL,
        timeout=pg.CONNECTION_TIMEOUT_S,
        server_settings={"application_name": "crm-listener"},
    )
    try:
        await conn.add_listener(postgres_repo.CHANNEL, _on_notify)
        logger.info("Listening for Postgres changes on '%s'", postgres_repo.CHANNEL)
        await sync_all()  # after LISTEN starts, so no change slips through the gap
        while True:
            try:
                await asyncio.wait_for(_wake.wait(), timeout=KEEPALIVE_S)
            except TimeoutError:
                await conn.execute("SELECT 1")  # raises if the connection dropped
                continue
            _wake.clear()
            await asyncio.sleep(DEBOUNCE_S)
            await _flush()
    finally:
        with contextlib.suppress(Exception):
            await conn.close()


async def _run() -> None:
    while True:
        try:
            await _listen_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Postgres change listener stopped (%s); reconnecting", exc)
            await asyncio.sleep(RETRY_S)


def start() -> None:
    """Start listening in the background (once Neo4j and its schema are ready)."""
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_run())


async def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _task
        _task = None
