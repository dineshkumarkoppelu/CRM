"""Concurrency guard for heavy admin work (Phase 9).

Seed (which also recomputes) and recompute rebuild large parts of the graph and must never
overlap. A second caller gets 409 `BUSY` instead of waiting; the nightly job skips its run.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.core.errors import AppError

_lock = asyncio.Lock()
_running: str | None = None


def running() -> str | None:
    """Name of the operation currently holding the lock, if any."""
    return _running


@asynccontextmanager
async def exclusive(operation: str) -> AsyncIterator[None]:
    """Run the block alone, or raise 409 BUSY if another operation is running.

    The check and the acquire happen without an await in between, so two requests in the
    same event loop cannot both get in.
    """
    global _running
    if _lock.locked():
        raise AppError(
            "BUSY",
            f"Cannot start {operation}: {_running or 'another operation'} is already running",
            409,
            {"running": _running},
        )
    async with _lock:
        _running = operation
        try:
            yield
        finally:
            _running = None
