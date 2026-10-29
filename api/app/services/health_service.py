"""Builds the health report from connectivity + version queries."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from app.core import clock, db
from app.models.health import HealthOut, Neo4jInfo
from app.repositories import health_repo
from app.schema import runner as schema_runner

logger = logging.getLogger(__name__)


async def _safe[T](name: str, call: Callable[[], Awaitable[T]]) -> T | None:
    """Run one probe; a failure becomes None (the field is reported as null)."""
    try:
        return await call()
    except db.CONNECTIVITY_ERRORS as exc:
        logger.warning("Health probe '%s' failed: %s", name, exc)
        return None


async def get_health() -> HealthOut:
    connected = await db.is_connected()
    info = Neo4jInfo(connected=connected)
    schema_ok: bool | None = None  # unknown while Neo4j is unreachable

    if connected:
        kernel = await _safe("dbms.components", health_repo.get_kernel_component)
        if kernel:
            info.version = kernel.get("version")
            info.edition = kernel.get("edition")
        info.apoc_version = await _safe("apoc.version", health_repo.get_apoc_version)
        info.gds_version = await _safe("gds.version", health_repo.get_gds_version)
        schema_ok = bool(await _safe("check_schema", schema_runner.check_schema))

    all_ok = (
        connected
        and schema_ok is True
        and all((info.version, info.edition, info.apoc_version, info.gds_version))
    )
    return HealthOut(
        status="ok" if all_ok else "degraded",
        neo4j=info,
        schema_ok=schema_ok,
        as_of_date=clock.today(),
    )
