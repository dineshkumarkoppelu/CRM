"""Cypher for applying and checking the schema (constraints, indexes, Domain nodes)."""

from __future__ import annotations

from app.core.db import run_auto_commit, run_read

LIST_CONSTRAINT_NAMES = "SHOW CONSTRAINTS YIELD name RETURN name"

LIST_INDEX_NAMES = "SHOW INDEXES YIELD name RETURN name"

LIST_DOMAIN_NAMES = "MATCH (d:Domain) RETURN d.name AS name ORDER BY name"


async def execute_schema_statement(statement: str) -> None:
    """Run one statement from init.cypher in its own auto-commit transaction."""
    await run_auto_commit(statement)


async def list_constraint_names() -> list[str]:
    return [row["name"] for row in await run_read(LIST_CONSTRAINT_NAMES)]


async def list_index_names() -> list[str]:
    return [row["name"] for row in await run_read(LIST_INDEX_NAMES)]


async def list_domain_names() -> list[str]:
    """All Domain names, including duplicates if any exist."""
    return [row["name"] for row in await run_read(LIST_DOMAIN_NAMES)]
