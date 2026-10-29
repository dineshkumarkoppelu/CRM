"""Assignment / recommendation / recompute shapes (api-contracts.md, Phase 6)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.models.common import Domain, FitType, RecommendationStatus

AssignmentStatus = Literal["ASSIGNED", "UNASSIGNED", "MANUAL", "PENDING_ENGINE"]


class AssignedRep(BaseModel):
    id: str
    name: str


class RecommendationOut(BaseModel):
    sales_person_id: str
    name: str
    rank: int  # 1 = best; 0 = added by a manual override
    score: float
    fit: float
    availability: float
    fit_type: FitType
    reason: str
    status: RecommendationStatus


class UnavailableRep(BaseModel):
    id: str
    name: str
    reason: Literal["INACTIVE", "AT_CAPACITY"]
    open_count: int
    capacity: int


class AssignmentResult(BaseModel):
    deal_id: str
    domain: Domain
    assignment_status: AssignmentStatus
    assigned_to: AssignedRep | None = None
    candidates: list[RecommendationOut] = []
    unavailable: list[UnavailableRep] = []
    message: str


class OverrideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sales_person_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class RecomputeResult(BaseModel):
    expertise_edges: int
    similar_pairs: int
    related_pairs: int  # RELATED_TO edges between domains (embedding similarity)
    duration_ms: int
    computed_at: date  # the business "today" the edges were computed for


class RecomputeStatus(BaseModel):
    last_run_at: datetime | None  # wall-clock UTC of the last run in this process
    last_result: RecomputeResult | None
    next_run_at: datetime | None  # null when the scheduler is disabled
