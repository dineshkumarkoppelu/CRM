"""Response models for /api/admin."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict


class SeedCounts(BaseModel):
    # Field names are the Neo4j label / relationship type names.
    model_config = ConfigDict(extra="forbid")

    SalesPerson: int
    Client: int
    Deal: int
    Activity: int
    Domain: int
    OWNS: int
    FOR_CLIENT: int
    IN_DOMAIN: int
    PERFORMED: int
    ON_DEAL: int


class SeedResult(BaseModel):
    counts: SeedCounts
    expertise_edges: int  # from the recompute that runs after loading (Phase 6)
    similar_pairs: int
    duration_ms: int
    as_of_date: date
    seed: int
