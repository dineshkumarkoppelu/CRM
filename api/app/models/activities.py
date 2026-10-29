"""Activity models (api-contracts.md)."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict

from app.models.common import ActivityType, NonEmptyStr, Outcome

# Note: the field is called `date`, so the type is written as `dt.date` to avoid the name clash.


class ActivityOut(BaseModel):
    id: str
    type: ActivityType
    date: dt.date
    outcome: Outcome
    deal_id: str
    sales_person_id: str
    sales_person_name: str


class ActivityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deal_id: NonEmptyStr
    sales_person_id: NonEmptyStr
    type: ActivityType
    date: dt.date | None = None  # defaults to today; must be >= deal created_at and <= today
    outcome: Outcome
