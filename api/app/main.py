"""FastAPI app factory and lifespan."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.core import db
from app.core.config import ConfigError, get_config
from app.core.errors import register_exception_handlers
from app.core.logging import add_request_logging, configure_logging
from app.core.settings import get_settings
from app.core.spa import DEFAULT_UI_DIST, mount_spa
from app.routers import (
    activities,
    admin,
    analytics,
    clients,
    deals,
    domains,
    graph,
    health,
    meta,
    recommendations,
    salespeople,
)
from app.schema import runner as schema_runner
from app.services import domain_service, expertise_service, scheduler

logger = logging.getLogger(__name__)


async def _after_schema() -> None:
    """Startup, once Neo4j is reachable: built-in domain descriptions/embeddings, then the
    recompute check."""
    try:
        await domain_service.ensure_builtin_domains()
    except db.CONNECTIVITY_ERRORS as exc:
        logger.warning("Built-in domain setup skipped: %s", exc)
    await _recompute_if_missing_safely()


async def _recompute_if_missing_safely() -> None:
    """Startup: make a restarted stack usable at once (EXPERTISE_IN exists if deals do)."""
    try:
        await expertise_service.recompute_if_missing()
    except db.CONNECTIVITY_ERRORS as exc:
        logger.warning("Startup recompute check skipped: %s", exc)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)

    # Fail fast (before waiting for Neo4j) if config.yaml is invalid.
    try:
        config = get_config()
    except ConfigError as exc:
        logger.critical("%s", exc)
        raise

    background: asyncio.Task[None] | None = None
    if await db.init_driver(settings):
        if await schema_runner.apply_schema_safely():
            await _after_schema()
    else:
        # Neo4j is not up yet: apply the schema (and the recompute check) once it is.
        background = asyncio.create_task(schema_runner.apply_schema_when_ready(after=_after_schema))

    if settings.SCHEDULER_ENABLED:
        scheduler.start(config.scheduler.recompute_cron)
    try:
        yield
    finally:
        scheduler.stop()
        if background is not None:
            background.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await background
        await db.close_driver()


def create_app(ui_dist: Path = DEFAULT_UI_DIST) -> FastAPI:
    app = FastAPI(title="CRM Graph Analytics POC", version="0.1.0", lifespan=lifespan)
    register_exception_handlers(app)
    add_request_logging(app)
    for module in (
        health,
        meta,
        admin,
        salespeople,
        clients,
        deals,
        activities,
        analytics,
        recommendations,
        graph,
        domains,
    ):
        app.include_router(module.router, prefix="/api")
    mount_spa(app, ui_dist)  # built UI from <repo>/ui/dist (after the API routers)
    return app


app = create_app()
