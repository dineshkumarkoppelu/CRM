"""Shared API models: enums (graph-schema.md), pagination, error body, common validators."""

from __future__ import annotations

from datetime import date, timedelta
from enum import StrEnum
from typing import Annotated

from fastapi import Query
from pydantic import AfterValidator, BaseModel, Field, StringConstraints

from app.core import clock


class DealStatus(StrEnum):
    OPEN = "OPEN"
    WON = "WON"
    LOST = "LOST"


class Stage(StrEnum):
    LEAD = "LEAD"
    QUALIFIED = "QUALIFIED"
    PROPOSAL = "PROPOSAL"
    NEGOTIATION = "NEGOTIATION"


class StageAction(StrEnum):
    ADVANCE = "ADVANCE"
    WIN = "WIN"
    LOSE = "LOSE"


class ActivityType(StrEnum):
    CALL = "CALL"
    EMAIL = "EMAIL"
    MEETING = "MEETING"
    DEMO = "DEMO"


class Outcome(StrEnum):
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE = "NEGATIVE"


class ClientSize(StrEnum):
    SMB = "SMB"
    MID_MARKET = "MID_MARKET"
    ENTERPRISE = "ENTERPRISE"


class Region(StrEnum):
    NORTH = "North"
    SOUTH = "South"
    EAST = "East"
    WEST = "West"
    INTERNATIONAL = "International"


# Domains are no longer a fixed enum: the 5 built-ins plus any created via POST /api/domains.
# Requests are checked against the database by `domain_service.require_domain` (422 if unknown).
DOMAIN_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9 &/+.\-]*[A-Za-z0-9+]$"
Domain = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]


class FitType(StrEnum):
    DIRECT = "DIRECT"
    PEER = "PEER"
    RELATED = "RELATED"  # borrowed from similar domains (new domains with no history yet)
    COLD_START = "COLD_START"


class RecommendationStatus(StrEnum):
    ASSIGNED = "ASSIGNED"
    CANDIDATE = "CANDIDATE"
    OVERRIDDEN = "OVERRIDDEN"


# ---- pagination (tech.md: limit default 50, max 200) ----
LimitQuery = Annotated[int, Query(ge=1, le=200, description="Page size (max 200)")]
OffsetQuery = Annotated[int, Query(ge=0, description="Rows to skip")]
DEFAULT_LIMIT = 50


class Page[T](BaseModel):
    items: list[T]
    total: int


# ---- error body (documentation of the shape produced by core/errors.py) ----
class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict = Field(default_factory=dict)


class ErrorBody(BaseModel):
    error: ErrorDetail


def error_responses(*codes: int) -> dict[int | str, dict]:
    """`responses=` entries for /docs so every error status shows the standard body."""
    return {code: {"model": ErrorBody} for code in codes}


# ---- reusable field types ----
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Email = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
]
Capacity = Annotated[int, Field(ge=1, le=50)]
PositiveValue = Annotated[int, Field(gt=0, description="Amount in INR")]

MAX_EXPECTED_CLOSE_DAYS_IN_PAST = 365


def _not_too_far_in_past(value: date) -> date:
    earliest = clock.today() - timedelta(days=MAX_EXPECTED_CLOSE_DAYS_IN_PAST)
    if value < earliest:
        raise ValueError(
            f"must not be more than {MAX_EXPECTED_CLOSE_DAYS_IN_PAST} days in the past "
            f"(earliest allowed {earliest.isoformat()})"
        )
    return value


ExpectedCloseDate = Annotated[date, AfterValidator(_not_too_far_in_past)]
