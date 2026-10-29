"""Cypher for the health check (server version/edition and plugin versions)."""

from __future__ import annotations

from typing import Any

from app.core.db import run_read

KERNEL_COMPONENT = """
CALL dbms.components() YIELD name, versions, edition
WHERE name = 'Neo4j Kernel'
RETURN versions[0] AS version, edition
"""

APOC_VERSION = "RETURN apoc.version() AS version"

GDS_VERSION = "RETURN gds.version() AS version"


async def get_kernel_component() -> dict[str, Any] | None:
    rows = await run_read(KERNEL_COMPONENT)
    return rows[0] if rows else None


async def get_apoc_version() -> str | None:
    rows = await run_read(APOC_VERSION)
    return rows[0]["version"] if rows else None


async def get_gds_version() -> str | None:
    rows = await run_read(GDS_VERSION)
    return rows[0]["version"] if rows else None
