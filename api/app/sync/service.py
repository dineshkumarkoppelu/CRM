"""Keeps Neo4j a live copy of the Postgres source of truth.

Three ways data reaches Neo4j, all through the same idempotent upserts:
- `full_sync()`: reads every row from the source API, loads what is new or changed and removes
  what is gone. Runs at startup, after every (re)connect of the LISTEN connection, on a timer
  as a safety net (NOTIFY is not durable) and on demand (`POST /api/admin/resync`).
- `apply_row(table, id)`: one row, re-read from the source. Driven by `crm_changes`
  notifications and by the app's own writes.
- recompute: EXPERTISE_IN / SIMILAR_TO are rebuilt a few seconds after the last change.

Postgres is the source of truth; nothing here ever writes to it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import threading
import time
from collections import OrderedDict
from datetime import date
from typing import Any

import psycopg
from pydantic import ValidationError

from app.core import clock
from app.core.errors import AppError
from app.core.settings import get_settings
from app.models.domains import DomainCreate
from app.models.sync import SyncProblem, SyncResult, SyncStatusOut, TableSyncOut
from app.services import domain_service, expertise_service
from app.sync import events, source_client, sync_repo

logger = logging.getLogger(__name__)

CHANNEL = "crm_changes"
# Load order (parents first). Deletes run in the reverse order.
TABLES: tuple[str, ...] = ("sales_people", "clients", "deals", "activities")

COLUMNS: dict[str, tuple[str, ...]] = {
    "sales_people": ("id", "name", "email", "region", "joined_on", "active", "capacity"),
    "clients": ("id", "name", "industry", "size", "region", "created_on"),
    "deals": (
        "id", "title", "value", "status", "stage", "created_at", "qualified_at", "proposal_at",
        "negotiation_at", "expected_close_date", "closed_at", "domain", "client_id", "owner_id",
    ),
    "activities": ("id", "type", "date", "outcome", "deal_id", "sales_person_id"),
}  # fmt: skip
DATE_COLUMNS = frozenset(
    {
        "joined_on", "created_on", "created_at", "qualified_at", "proposal_at", "negotiation_at",
        "expected_close_date", "closed_at", "date",
    }
)  # fmt: skip
LABEL = sync_repo.TABLE_LABEL
MAX_PROBLEMS = 50
RETRY_AFTER_FAILURE_S = 10.0
RECOMPUTE_RETRY_S = 5.0
RECOMPUTE_ATTEMPTS = 6


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------
def normalize(table: str, raw: dict[str, Any]) -> dict[str, Any]:
    """The columns the graph needs, with ISO date strings turned into `date` objects.

    `inserted_at` is dropped on purpose, so rows compare equal when only that changed.
    """
    row: dict[str, Any] = {}
    for column in COLUMNS[table]:
        value = raw.get(column)
        if column in DATE_COLUMNS and isinstance(value, str):
            value = date.fromisoformat(value[:10])
        row[column] = value
    return row


def parse_notification(payload: str) -> tuple[str, str, str] | None:
    """`(table, op, id)` from a crm_changes payload, or None if it is not one we understand."""
    try:
        data = json.loads(payload)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    table, op, row_id = data.get("table"), data.get("op"), data.get("id")
    if table not in COLUMNS or not isinstance(row_id, str) or not row_id:
        return None
    return table, str(op), row_id


def select_changed(
    rows: list[dict[str, Any]], cache: dict[str, dict[str, Any]], present: set[str]
) -> list[dict[str, Any]]:
    """Rows to upsert: not in Neo4j yet, or different from what was last applied."""
    return [r for r in rows if r["id"] not in present or cache.get(r["id"]) != r]


def canonical_domain(name: str | None, known: list[str]) -> str | None:
    """The existing Domain name that equals `name` ignoring case and surrounding spaces."""
    if not name:
        return None
    wanted = name.strip().casefold()
    return next((k for k in known if k.casefold() == wanted), None)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = asyncio.Lock()  # one sync operation at a time (events queue behind a full sync)
_cache: dict[str, dict[str, dict[str, Any]]] = {t: {} for t in TABLES}  # last applied rows
_problems: OrderedDict[tuple[str, str], SyncProblem] = OrderedDict()
_state: dict[str, Any] = {
    "listening": False,
    "last_sync": None,
    "last_event_at": None,
    "events_applied": 0,
    "last_error": None,
}
_dirty = asyncio.Event()  # a deal / rep changed: recompute once things go quiet
_resync_requested = asyncio.Event()
_tasks: list[asyncio.Task[None]] = []
_stop_listener = threading.Event()


def _note_problem(table: str, row_id: str, reason: str) -> None:
    key = (table, row_id)
    _problems.pop(key, None)
    _problems[key] = SyncProblem(table=table, id=row_id, reason=reason, at=clock.utc_now())
    while len(_problems) > MAX_PROBLEMS:
        _problems.popitem(last=False)
    logger.warning("Sync skipped %s %s: %s", table, row_id, reason)


def _clear_problem(table: str, row_id: str) -> None:
    _problems.pop((table, row_id), None)


def status() -> SyncStatusOut:
    settings = get_settings()
    if not settings.source_enabled:
        mode = "off"
    else:
        mode = "listen" if settings.SOURCE_PG_DSN else "poll"
    return SyncStatusOut(
        enabled=settings.source_enabled,
        mode=mode,
        listening=_state["listening"],
        last_sync=_state["last_sync"],
        last_event_at=_state["last_event_at"],
        events_applied=_state["events_applied"],
        last_error=_state["last_error"],
        problems=list(_problems.values()),
    )


def schedule_recompute() -> None:
    _dirty.set()


# ---------------------------------------------------------------------------
# Applying rows
# ---------------------------------------------------------------------------
async def _resolve_domain(name: str | None) -> str | None:
    """Canonical Domain name; an unknown one is added like POST /api/domains would (it is
    embedded so reps can get a RELATED fit). None if that is impossible right now."""
    known = await sync_repo.domain_names()
    found = canonical_domain(name, known)
    if found is not None or not name:
        return found
    try:
        created = await domain_service.create_domain(
            DomainCreate(
                name=name.strip(),
                description=f"{name.strip()} (added automatically from the CRM data source)",
            )
        )
    except (AppError, ValidationError) as exc:
        logger.warning("Could not add domain %r: %s", name, getattr(exc, "message", exc))
        return None
    return created.name


async def _ensure(table: str, row_id: str | None) -> bool:
    """Make sure a parent row exists in Neo4j, loading it from the source if needed."""
    if not row_id:
        return False
    if await sync_repo.exists(LABEL[table], row_id):
        return True
    raw = await source_client.get(table, row_id)
    if raw is None:
        return False
    return (await _upsert_one(table, normalize(table, raw))) == "upserted"


async def _upsert_one(table: str, row: dict[str, Any]) -> str:
    """Upsert one row (loading missing parents first). 'upserted' or 'skipped: <reason>'."""
    row_id = row["id"]
    if table == "sales_people":
        await sync_repo.upsert_sales_people([row])
    elif table == "clients":
        await sync_repo.upsert_clients([row])
    elif table == "deals":
        if not await _ensure("clients", row["client_id"]):
            return _skip(table, row_id, f"client {row['client_id']} not found")
        domain = await _resolve_domain(row["domain"])
        if domain is None:
            return _skip(table, row_id, f"unknown domain {row['domain']!r}")
        if row["owner_id"] and not await _ensure("sales_people", row["owner_id"]):
            logger.warning("Deal %s: owner %s not found, left unassigned", row_id, row["owner_id"])
        await sync_repo.upsert_deals([{**row, "domain": domain}])
    else:
        if not await _ensure("deals", row["deal_id"]):
            return _skip(table, row_id, f"deal {row['deal_id']} not found")
        if not await _ensure("sales_people", row["sales_person_id"]):
            return _skip(table, row_id, f"sales person {row['sales_person_id']} not found")
        await sync_repo.upsert_activities([row])
    _cache[table][row_id] = row
    _clear_problem(table, row_id)
    return "upserted"


def _skip(table: str, row_id: str, reason: str) -> str:
    _note_problem(table, row_id, reason)
    return f"skipped: {reason}"


async def _delete_one(table: str, row_id: str) -> str:
    await sync_repo.delete_ids(LABEL[table], [row_id])
    _cache[table].pop(row_id, None)
    _clear_problem(table, row_id)
    if table == "deals":  # its activities went with it
        for activity_id in [k for k, v in _cache["activities"].items() if v["deal_id"] == row_id]:
            _cache["activities"].pop(activity_id, None)
    return "deleted"


async def apply_row(table: str, row_id: str, op: str | None = None) -> str:
    """Re-read one row from the source and mirror it into Neo4j (or delete it there)."""
    async with _lock:
        raw = await source_client.get(table, row_id)
        outcome = (
            await _delete_one(table, row_id)
            if raw is None
            else await _upsert_one(table, normalize(table, raw))
        )
    _state["events_applied"] += 1
    _state["last_event_at"] = clock.utc_now()
    if outcome in ("upserted", "deleted"):
        events.publish({"table": table, "op": op or outcome, "id": row_id})
        if table in ("deals", "sales_people"):
            schedule_recompute()
    return outcome


async def handle_notification(payload: str) -> None:
    parsed = parse_notification(payload)
    if parsed is None:
        logger.warning("Ignoring unrecognised %s payload: %.200s", CHANNEL, payload)
        return
    table, op, row_id = parsed
    try:
        await apply_row(table, row_id, op)
    except Exception as exc:  # one bad event must not stop the listener
        _state["last_error"] = f"{table} {row_id}: {exc}"[:300]
        logger.exception("Could not apply %s %s %s", op, table, row_id)
        _resync_requested.set()  # the safety-net sync will pick it up soon


# ---------------------------------------------------------------------------
# Full sync
# ---------------------------------------------------------------------------
async def full_sync(*, force_adopt: bool = False) -> SyncResult:
    """Make Neo4j match the source. Holds the lock for the whole read-and-apply."""
    async with _lock:
        return await _full_sync(force_adopt)


async def _full_sync(force_adopt: bool) -> SyncResult:
    started = time.perf_counter()
    data = {t: [normalize(t, r) for r in await source_client.list_all(t)] for t in TABLES}

    adopted = await _maybe_adopt(data, force_adopt)
    present = {t: await sync_repo.existing_ids(LABEL[t]) for t in TABLES}
    counts = {t: {"upserted": 0, "deleted": 0, "skipped": 0} for t in TABLES}

    # 1. Remove what the source no longer has (children first).
    for table in reversed(TABLES):
        source_ids = {r["id"] for r in data[table]}
        stale = sorted(present[table] - source_ids)
        if stale:
            await sync_repo.delete_ids(LABEL[table], stale)
            present[table] -= set(stale)
            for stale_id in stale:
                _cache[table].pop(stale_id, None)
                _clear_problem(table, stale_id)
            counts[table]["deleted"] = len(stale)
    # A deleted deal took its activities along.
    if counts["deals"]["deleted"]:
        present["activities"] = await sync_repo.existing_ids(LABEL["activities"])

    # 2. Load new and changed rows (parents first).
    for table in ("sales_people", "clients"):
        changed = select_changed(data[table], _cache[table], present[table])
        if changed:
            upsert = (
                sync_repo.upsert_sales_people
                if table == "sales_people"
                else sync_repo.upsert_clients
            )
            await upsert(changed)
            for row in changed:
                _cache[table][row["id"]] = row
                present[table].add(row["id"])
            counts[table]["upserted"] = len(changed)

    await _sync_deals(data["deals"], present, counts)
    await _sync_activities(data["activities"], present, counts)

    result = SyncResult(
        adopted=adopted,
        tables=[TableSyncOut(table=t, source_rows=len(data[t]), **counts[t]) for t in TABLES],
        duration_ms=round((time.perf_counter() - started) * 1000),
        finished_at=clock.utc_now(),
    )
    _state["last_sync"] = result
    _state["last_error"] = None
    changed_tables = [t for t in TABLES if counts[t]["upserted"] or counts[t]["deleted"]]
    for table in changed_tables:
        events.publish({"table": table, "op": "SYNC", "changed": counts[table]["upserted"]})
    if changed_tables and set(changed_tables) & {"deals", "sales_people"}:
        schedule_recompute()
    logger.info(
        "Sync: %s in %d ms%s",
        ", ".join(f"{t.table} {t.upserted}+/{t.deleted}-/{t.skipped}!" for t in result.tables),
        result.duration_ms,
        " (adopted a new source)" if adopted else "",
    )
    return result


async def _maybe_adopt(data: dict[str, list[dict[str, Any]]], force: bool) -> bool:
    """First run against this source: replace whatever else Neo4j holds (the old demo data).

    Done once, remembered by a marker node. Never done when the source is empty - that is far
    more likely a wrong URL than an intention to erase the graph.
    """
    if not force and await sync_repo.get_marker() is not None:
        return False
    if not any(data.values()):
        logger.error("The data source is empty; not replacing the existing graph data")
        return False
    logger.warning("Adopting the data source: replacing existing SalesPerson/Client/Deal/Activity")
    await sync_repo.wipe_entities()
    for cache in _cache.values():
        cache.clear()
    _problems.clear()
    await sync_repo.set_marker(clock.utc_now())
    return True


async def _sync_deals(
    rows: list[dict[str, Any]], present: dict[str, set[str]], counts: dict[str, dict[str, int]]
) -> None:
    changed = select_changed(rows, _cache["deals"], present["deals"])
    ready: list[dict[str, Any]] = []
    known_domains = await sync_repo.domain_names()
    for row in changed:
        domain = canonical_domain(row["domain"], known_domains)
        if domain is None:  # add it (once per name), then look again
            domain = await _resolve_domain(row["domain"])
            if domain is not None:
                known_domains = await sync_repo.domain_names()
        if row["client_id"] not in present["clients"]:
            _skip("deals", row["id"], f"client {row['client_id']} not found")
        elif domain is None:
            _skip("deals", row["id"], f"unknown domain {row['domain']!r}")
        else:
            ready.append({**row, "domain": domain})
            if row["owner_id"] and row["owner_id"] not in present["sales_people"]:
                logger.warning(
                    "Deal %s: owner %s not found, left unassigned", row["id"], row["owner_id"]
                )  # noqa: E501
    if ready:
        await sync_repo.upsert_deals(ready)
        original = {r["id"]: r for r in changed}
        for row in ready:
            _cache["deals"][row["id"]] = original[row["id"]]
            present["deals"].add(row["id"])
            _clear_problem("deals", row["id"])
    counts["deals"]["upserted"] = len(ready)
    counts["deals"]["skipped"] = len(changed) - len(ready)


async def _sync_activities(
    rows: list[dict[str, Any]], present: dict[str, set[str]], counts: dict[str, dict[str, int]]
) -> None:
    changed = select_changed(rows, _cache["activities"], present["activities"])
    ready = [
        r
        for r in changed
        if r["deal_id"] in present["deals"] and r["sales_person_id"] in present["sales_people"]
    ]
    ready_ids = {r["id"] for r in ready}
    for row in changed:
        if row["id"] not in ready_ids:
            _note_problem("activities", row["id"], "deal or sales person not found")
    if ready:
        await sync_repo.upsert_activities(ready)
        for row in ready:
            _cache["activities"][row["id"]] = row
            present["activities"].add(row["id"])
            _clear_problem("activities", row["id"])
    counts["activities"]["upserted"] = len(ready)
    counts["activities"]["skipped"] = len(changed) - len(ready)


# ---------------------------------------------------------------------------
# Recompute (debounced)
# ---------------------------------------------------------------------------
async def _recompute_worker() -> None:
    """Rebuild EXPERTISE_IN / SIMILAR_TO once changes have been quiet for a few seconds."""
    while True:
        await _dirty.wait()
        quiet = get_settings().SYNC_RECOMPUTE_DEBOUNCE_SECONDS
        while True:  # wait for a quiet period
            _dirty.clear()
            await asyncio.sleep(quiet)
            if not _dirty.is_set():
                break
        for _ in range(RECOMPUTE_ATTEMPTS):
            try:
                await expertise_service.recompute_exclusive("sync recompute")
                events.publish({"table": "derived", "op": "RECOMPUTE"})
                break
            except AppError as exc:
                if exc.code != "BUSY":
                    logger.warning("Sync recompute failed: %s", exc.message)
                    break
                await asyncio.sleep(RECOMPUTE_RETRY_S)  # a seed / other recompute is running
            except Exception:
                logger.exception("Sync recompute failed")
                break


# ---------------------------------------------------------------------------
# Listening
# ---------------------------------------------------------------------------
def _listen_blocking(
    dsn: str, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[tuple[str, str | None]]
) -> None:
    """Runs in a thread: LISTEN and forward notifications to the event loop.

    A plain (sync) psycopg connection in a thread works on every platform; psycopg's async API
    cannot run on Windows' default ProactorEventLoop.
    """

    def put(kind: str, value: str | None = None) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, (kind, value))

    try:
        with psycopg.connect(
            dsn,
            autocommit=True,
            application_name="crm-app",  # the trigger ignores writes from this name
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            connect_timeout=10,
        ) as conn:
            conn.execute(f"LISTEN {CHANNEL}")
            put("ready")
            while not _stop_listener.is_set():
                for notification in conn.notifies(timeout=1.0):
                    put("event", notification.payload)
                    if _stop_listener.is_set():
                        break
    except Exception as exc:
        put("closed", f"{type(exc).__name__}: {exc}")
        return
    put("closed", "stopped")


async def _listen_session(dsn: str) -> None:
    """One LISTEN connection: catch up with a full sync, then apply notifications until it drops."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, str | None]] = asyncio.Queue()
    _stop_listener.clear()
    thread = asyncio.create_task(asyncio.to_thread(_listen_blocking, dsn, loop, queue))
    try:
        kind, value = await queue.get()
        if kind != "ready":
            raise ConnectionError(value or "could not LISTEN")
        _state["listening"] = True
        logger.info("Listening for %s notifications", CHANNEL)
        await full_sync()  # LISTEN first, then catch up: nothing can fall in the gap
        while True:
            kind, value = await queue.get()
            if kind == "event" and value is not None:
                await handle_notification(value)
            elif kind == "closed":
                raise ConnectionError(value or "LISTEN connection closed")
    finally:
        _state["listening"] = False
        _stop_listener.set()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(thread, timeout=5)


async def _supervisor() -> None:
    """Keep the real-time link alive: LISTEN when a DSN is set (reconnecting with backoff),
    otherwise poll. While the link is down the app falls back to polling, so it never goes
    stale for long."""
    settings = get_settings()
    dsn = settings.SOURCE_PG_DSN
    delay = 1.0
    while True:
        try:
            if dsn:
                await _listen_session(dsn)
            else:
                await full_sync()
                await asyncio.sleep(settings.SYNC_POLL_SECONDS)
                continue
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _state["last_error"] = f"{type(exc).__name__}: {exc}"[:300]
            logger.warning("Sync link down (%s); retrying in %.0f s", exc, delay)
            if dsn:
                await _safe_full_sync()
        await asyncio.sleep(delay)
        delay = min(delay * 2, 30.0) if dsn else settings.SYNC_POLL_SECONDS


async def _safe_full_sync() -> None:
    try:
        await full_sync()
    except Exception as exc:
        _state["last_error"] = f"{type(exc).__name__}: {exc}"[:300]
        logger.warning("Full sync failed: %s", exc)


async def _reconcile_loop() -> None:
    """The safety net: NOTIFY is not durable, so re-check everything now and then (and soon
    after any event that failed to apply)."""
    interval = get_settings().SYNC_RECONCILE_SECONDS
    while True:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(_resync_requested.wait(), timeout=interval)
            await asyncio.sleep(RETRY_AFTER_FAILURE_S)
        _resync_requested.clear()
        if _state["listening"]:  # in poll mode the supervisor already syncs
            await _safe_full_sync()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
def start() -> None:
    """Start the background tasks (needs a running loop and a reachable Neo4j)."""
    if _tasks or not get_settings().source_enabled:
        return
    _tasks.extend(
        asyncio.create_task(coro, name=name)
        for name, coro in (
            ("sync-supervisor", _supervisor()),
            ("sync-reconcile", _reconcile_loop()),
            ("sync-recompute", _recompute_worker()),
        )
    )
    mode = "LISTEN" if get_settings().SOURCE_PG_DSN else "polling"
    logger.info("Sync started (%s) from %s", mode, get_settings().SOURCE_API_URL)


async def stop() -> None:
    _stop_listener.set()
    for task in _tasks:
        task.cancel()
    for task in _tasks:
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
    _tasks.clear()
    await source_client.close()
    _state["listening"] = False


def reset_for_tests() -> None:
    """Forget everything applied so far (unit tests)."""
    for cache in _cache.values():
        cache.clear()
    _problems.clear()
    _state.update(
        listening=False, last_sync=None, last_event_at=None, events_applied=0, last_error=None
    )


__all__ = [
    "apply_row", "full_sync", "handle_notification", "normalize", "parse_notification",
    "start", "status", "stop",
]  # fmt: skip
