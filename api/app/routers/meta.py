"""GET /api/meta/config and GET /api/meta/domains (read-only)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.config import AppConfig, config_dependency
from app.services import domain_service

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/config", response_model=AppConfig)
async def get_config(config: Annotated[AppConfig, Depends(config_dependency)]) -> AppConfig:
    """The business tunables loaded from config.yaml, grouped as in the file."""
    return config


@router.get("/domains", response_model=list[str])
async def get_domains() -> list[str]:
    """All domain names in display order: the 5 built-ins, then added domains (UI uses this)."""
    return await domain_service.domain_names()
