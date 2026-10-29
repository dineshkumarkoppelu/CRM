"""Deal models (api-contracts.md)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, model_validator

from app.models.activities import ActivityOut
from app.models.assignment import AssignmentResult, RecommendationOut
from app.models.common import (
    DealStatus,
    Domain,
    ExpectedCloseDate,
    NonEmptyStr,
    PositiveValue,
    Stage,
    StageAction,
)


class DealOut(BaseModel):
    id: str
    title: str
    value: int
    status: DealStatus
    stage: Stage
    domain: Domain
    client_id: str
    client_name: str
    owner_id: str | None
    owner_name: str | None
    created_at: date
    qualified_at: date | None
    proposal_at: date | None
    negotiation_at: date | None
    expected_close_date: date
    closed_at: date | None


class DealDetail(DealOut):
    activities: list[ActivityOut]
    recommendations: list[RecommendationOut]  # empty until Phase 6


class DealFields(BaseModel):
    """The deal part shared by POST /api/deals and POST /api/clients."""

    model_config = ConfigDict(extra="forbid")

    title: NonEmptyStr
    value: PositiveValue
    domain: Domain
    expected_close_date: ExpectedCloseDate
    owner_id: NonEmptyStr | None = None


class DealCreate(DealFields):
    client_id: NonEmptyStr


class DealCreateResult(BaseModel):
    deal: DealOut
    assignment: AssignmentResult


class StageMove(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: StageAction


class DealUpdate(BaseModel):
    """Partial update of an OPEN deal. `null` is not allowed."""

    model_config = ConfigDict(extra="forbid")

    title: NonEmptyStr | None = None
    value: PositiveValue | None = None
    expected_close_date: ExpectedCloseDate | None = None

    @model_validator(mode="after")
    def _no_nulls(self) -> DealUpdate:
        nulls = sorted(f for f in self.model_fields_set if getattr(self, f) is None)
        if nulls:
            raise ValueError(f"fields cannot be null: {', '.join(nulls)}")
        return self
