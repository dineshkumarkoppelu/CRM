"""Domain models (/api/domains)."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.models.common import DOMAIN_NAME_PATTERN


class RelatedDomainOut(BaseModel):
    domain: str
    similarity: float  # cosine similarity of the description embeddings, 4 dp
    used_for_fit: bool  # among the top-k above the threshold (counts for a RELATED fit)


class DomainOut(BaseModel):
    name: str
    description: str | None
    builtin: bool
    created_at: date | None
    related: list[RelatedDomainOut]


class DomainCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=2, max_length=40, pattern=DOMAIN_NAME_PATTERN
        ),
    ]
    description: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=10, max_length=400)
    ]
