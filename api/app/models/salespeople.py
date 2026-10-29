"""Sales person models (api-contracts.md)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, model_validator

from app.models.common import Capacity, Domain, Email, NonEmptyStr, Region


class SalesPersonOut(BaseModel):
    id: str
    name: str
    email: str
    region: Region
    joined_on: date
    active: bool
    capacity: int


class ExpertiseOut(BaseModel):
    domain: Domain
    handled: int
    won: int
    lost: int
    win_rate: float | None
    qualifies: bool
    last_won_at: date | None


class SimilarPeerOut(BaseModel):
    id: str
    name: str
    matched_domains: list[str]
    match_count: int
    mean_abs_diff: float
    score: float


class SalesPersonDetail(SalesPersonOut):
    open_count: int
    availability: float
    expertise: list[ExpertiseOut]  # empty until Phase 6
    similar_peers: list[SimilarPeerOut]  # empty until Phase 6


class SalesPersonCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: NonEmptyStr
    email: Email
    region: Region
    joined_on: date
    capacity: Capacity | None = None  # default: config assignment.capacity_default
    active: bool = True


class SalesPersonUpdate(BaseModel):
    """Partial update: only the fields sent are changed. `null` is not allowed."""

    model_config = ConfigDict(extra="forbid")

    name: NonEmptyStr | None = None
    email: Email | None = None
    region: Region | None = None
    capacity: Capacity | None = None
    active: bool | None = None

    @model_validator(mode="after")
    def _no_nulls(self) -> SalesPersonUpdate:
        nulls = sorted(f for f in self.model_fields_set if getattr(self, f) is None)
        if nulls:
            raise ValueError(f"fields cannot be null: {', '.join(nulls)}")
        return self
