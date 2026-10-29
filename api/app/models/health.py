"""Response models for GET /api/health (shape from api-contracts.md)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel


class Neo4jInfo(BaseModel):
    connected: bool
    version: str | None = None
    edition: str | None = None
    apoc_version: str | None = None
    gds_version: str | None = None


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    neo4j: Neo4jInfo
    schema_ok: bool | None = None  # null when Neo4j is unreachable (cannot be checked)
    as_of_date: date
