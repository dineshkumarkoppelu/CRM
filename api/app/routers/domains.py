"""/api/domains - the domain list and adding new domains."""

from __future__ import annotations

from fastapi import APIRouter

from app.models.common import error_responses
from app.models.domains import DomainCreate, DomainOut
from app.services import domain_service

router = APIRouter(prefix="/domains", tags=["domains"])


@router.get("", response_model=list[DomainOut])
async def list_domains() -> list[DomainOut]:
    """All domains (built-ins first) with their embedding similarity to the other domains."""
    return await domain_service.list_domains()


@router.post(
    "", response_model=DomainOut, status_code=201, responses=error_responses(409, 422, 503)
)
async def create_domain(body: DomainCreate) -> DomainOut:
    """Add a domain. Its description is embedded locally and compared with every existing
    domain; deals in the new domain are routed with a RELATED fit until reps build a track
    record there. The first call downloads/loads the embedding model and can take ~30 s."""
    return await domain_service.create_domain(body)
