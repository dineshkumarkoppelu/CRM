"""Applies app/schema/init.cypher and checks that the schema is complete.

- `apply_schema()` runs every statement of init.cypher (each in its own auto-commit
  transaction; schema commands cannot share a transaction with data writes).
- `check_schema()` is True only when all 11 named constraints/indexes exist and exactly the
  5 expected Domain nodes exist.
- On startup the API calls `apply_schema_safely()`; if Neo4j is not reachable yet,
  `apply_schema_when_ready()` keeps retrying in the background until it succeeds.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Awaitable, Callable
from pathlib import Path

from neo4j.exceptions import Neo4jError

from app.core import db
from app.core.domains import DOMAINS
from app.repositories import schema_repo

logger = logging.getLogger(__name__)

INIT_CYPHER_PATH = Path(__file__).with_name("init.cypher")

EXPECTED_CONSTRAINTS: tuple[str, ...] = (
    "sp_id_unique",
    "client_id_unique",
    "deal_id_unique",
    "activity_id_unique",
    "domain_name_unique",
)
EXPECTED_INDEXES: tuple[str, ...] = (
    "deal_status_idx",
    "deal_stage_idx",
    "deal_expected_close_idx",
    "deal_closed_at_idx",
    "deal_created_at_idx",
    "activity_date_idx",
)

RETRY_INTERVAL_S = 10.0


def parse_statements(text: str) -> list[str]:
    """Drop full-line `//` comments, split on `;`, return the non-empty statements."""
    kept = [line for line in text.splitlines() if not line.lstrip().startswith("//")]
    return [part.strip() for part in "\n".join(kept).split(";") if part.strip()]


async def apply_schema() -> int:
    """Run every statement in init.cypher. Returns the number of statements run."""
    statements = parse_statements(INIT_CYPHER_PATH.read_text(encoding="utf-8"))
    for statement in statements:
        await schema_repo.execute_schema_statement(statement)
    logger.info(
        "Schema init: %d statements applied from %s", len(statements), INIT_CYPHER_PATH.name
    )
    return len(statements)


async def apply_schema_safely() -> bool:
    """`apply_schema()` that logs instead of raising. Returns True on success."""
    try:
        await apply_schema()
        return True
    except Neo4jError as exc:
        # The server rejected a statement (e.g. existing duplicate ids block a constraint).
        logger.error("Schema init failed: %s", exc)
        return False
    except db.CONNECTIVITY_ERRORS as exc:
        logger.warning("Schema init skipped, Neo4j not reachable: %s", exc)
        return False


async def apply_schema_when_ready(
    interval_s: float = RETRY_INTERVAL_S,
    after: Callable[[], Awaitable[object]] | None = None,
) -> None:
    """Background task: retry schema init until Neo4j is reachable and init succeeds, then run
    the optional `after` step (e.g. the startup recompute check)."""
    while True:
        if await db.is_connected() and await apply_schema_safely():
            if after is not None:
                await after()
            return
        await asyncio.sleep(interval_s)


async def check_schema() -> bool:
    """True only if all named constraints/indexes exist, the 5 built-in Domain nodes exist and
    no domain name is duplicated (added domains are allowed)."""
    constraints = set(await schema_repo.list_constraint_names())
    indexes = set(await schema_repo.list_index_names())
    domains = await schema_repo.list_domain_names()

    missing_constraints = [n for n in EXPECTED_CONSTRAINTS if n not in constraints]
    missing_indexes = [n for n in EXPECTED_INDEXES if n not in indexes]
    counts = Counter(domains)
    domains_ok = all(counts[d] == 1 for d in DOMAINS) and all(n == 1 for n in counts.values())

    if missing_constraints or missing_indexes or not domains_ok:
        logger.warning(
            "Schema incomplete: missing constraints=%s, missing indexes=%s, domains=%s",
            missing_constraints,
            missing_indexes,
            domains,
        )
        return False
    return True
