"""Keep win rates, similarity and owners up to date as data changes.

Anything that changes deals, reps or activities (a UI action or a Postgres change pushed in by
`pg_sync`) calls `request()`. A moment later (changes arriving together are batched) one refresh
runs: the normal EXPERTISE_IN / SIMILAR_TO recompute, then the normal assignment for every OPEN
deal that has no owner yet (for example a deal inserted straight into Postgres).

This only calls the existing recompute and assignment code; the ranking rules are unchanged.
Rankings already stored for deals that have an owner are kept as the record of that decision.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from app.core.errors import AppError
from app.repositories import deals_repo
from app.services import assignment_service, busy, expertise_service

logger = logging.getLogger(__name__)

DEBOUNCE_S = 0.5  # gather a burst of changes into one refresh
BUSY_RETRY_S = 2.0

_task: asyncio.Task[None] | None = None
_requested = asyncio.Event()


def request() -> None:
    """Ask for a refresh soon. Does nothing when the refresh is not running (e.g. in tests)."""
    if _task is not None:
        _requested.set()


async def _assign_unowned() -> int:
    assigned = 0
    for deal_id in await deals_repo.list_unowned_open_ids():
        try:
            result = await assignment_service.assign_deal(deal_id)
        except AppError as exc:  # taken or closed by someone else in the meantime
            logger.info("Auto-assign of %s skipped: %s", deal_id, exc.message)
            continue
        if result.assigned_to is not None:
            assigned += 1
    return assigned


async def refresh() -> None:
    """Recompute expertise + similarity, then assign deals that have no owner."""
    try:
        async with busy.exclusive("live refresh"):
            result = await expertise_service.recompute()
            assigned = await _assign_unowned()
    except AppError as exc:
        if exc.code != "BUSY":
            raise
        await asyncio.sleep(BUSY_RETRY_S)  # a seed / recompute is running; try again after it
        request()
        return
    logger.info(
        "Live refresh: %d EXPERTISE_IN, %d SIMILAR_TO, %d deals auto-assigned in %d ms",
        result.expertise_edges,
        result.similar_pairs,
        assigned,
        result.duration_ms,
    )


async def _run() -> None:
    while True:
        await _requested.wait()
        await asyncio.sleep(DEBOUNCE_S)
        _requested.clear()
        try:
            await refresh()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Live refresh failed")


def start() -> None:
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
