"""In-process pub/sub behind GET /api/events (Server-Sent Events).

The sync publishes `{"table", "op", "id"?}` AFTER Neo4j has been updated, so a browser that
refetches on receipt always sees the change.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

logger = logging.getLogger(__name__)

HEARTBEAT_S = 15.0
QUEUE_SIZE = 256

_subscribers: set[asyncio.Queue[dict[str, Any]]] = set()


def publish(event: dict[str, Any]) -> None:
    """Fan out to every connected browser. A slow subscriber drops events, never blocks."""
    for queue in list(_subscribers):
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("Dropping an event for a slow subscriber")


def subscriber_count() -> int:
    return len(_subscribers)


def _frame(event: str, data: dict[str, Any] | None = None) -> str:
    return f"event: {event}\ndata: {json.dumps(data or {})}\n\n"


async def stream() -> AsyncIterator[str]:
    """SSE frames: `hello` at once, `change` per event, a comment line as heartbeat."""
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=QUEUE_SIZE)
    _subscribers.add(queue)
    try:
        yield _frame("hello")
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_S)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            yield _frame("change", event)
    finally:
        _subscribers.discard(queue)
