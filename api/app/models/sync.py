"""Response models for /api/admin/resync and /api/admin/sync/status."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class TableSyncOut(BaseModel):
    table: str
    source_rows: int
    upserted: int
    deleted: int
    skipped: int  # rows that could not be loaded (missing client, unknown domain, ...)


class SyncResult(BaseModel):
    adopted: bool  # True when Neo4j's old data was replaced because the source is new to it
    tables: list[TableSyncOut]
    duration_ms: int
    finished_at: datetime


class SyncProblem(BaseModel):
    table: str
    id: str
    reason: str
    at: datetime


class SyncStatusOut(BaseModel):
    enabled: bool
    mode: Literal["off", "listen", "poll"]
    listening: bool  # the LISTEN connection to Postgres is up
    last_sync: SyncResult | None
    last_event_at: datetime | None
    events_applied: int
    last_error: str | None
    problems: list[SyncProblem]
