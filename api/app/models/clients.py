"""Client models (api-contracts.md)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict

from app.models.assignment import AssignmentResult
from app.models.common import ClientSize, NonEmptyStr, Region
from app.models.deals import DealFields, DealOut


class ClientOut(BaseModel):
    id: str
    name: str
    industry: str
    size: ClientSize
    region: Region
    created_on: date


class ClientDetail(ClientOut):
    deals: list[DealOut]


class ClientCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: NonEmptyStr
    industry: NonEmptyStr
    size: ClientSize
    region: Region


class ClientWithDealCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client: ClientCreate
    deal: DealFields


class ClientCreateResult(BaseModel):
    client: ClientOut
    deal: DealOut
    assignment: AssignmentResult
