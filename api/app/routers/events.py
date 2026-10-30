"""Live change feed (Server-Sent Events) for the web UI."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.sync import events

router = APIRouter(tags=["events"])


@router.get("/events")
async def stream_events() -> StreamingResponse:
    """`text/event-stream`: `hello` on connect, then a `change` event ({table, op, id}) each time
    the data changed in Neo4j. The UI refetches when it receives one."""
    return StreamingResponse(
        events.stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
