"""Cypher for domains and the domain-to-domain similarity (RELATED_TO) edges."""

from __future__ import annotations

from datetime import date
from typing import Any

from neo4j import AsyncManagedTransaction

from app.core.db import run_in_write_tx, run_read, run_write, tx_run

# Built-ins first (position 0-4), then new domains in creation order.
LIST = """
MATCH (d:Domain)
RETURN d.name AS name, d.description AS description, coalesce(d.builtin, false) AS builtin,
       d.created_at AS created_at, d.embedding_model AS embedding_model,
       d.embedding IS NOT NULL AS has_embedding
ORDER BY coalesce(d.position, 1000000), d.name
"""

FIND_BY_NAME_CI = """
MATCH (d:Domain)
WHERE toLower(d.name) = toLower($name)
RETURN d.name AS name
"""

SET_BUILTINS = """
UNWIND $rows AS row
MATCH (d:Domain {name: row.name})
SET d.description = row.description,
    d.builtin = true,
    d.embedding = row.embedding,
    d.embedding_model = row.embedding_model
"""

CREATE = """
OPTIONAL MATCH (x:Domain)
WITH coalesce(max(x.position), -1) + 1 AS position
CREATE (d:Domain {
  name: $name, description: $description, builtin: false, position: position,
  created_at: $today, embedding: $embedding, embedding_model: $embedding_model
})
RETURN d.name AS name
"""

SET_EMBEDDINGS = """
UNWIND $rows AS row
MATCH (d:Domain {name: row.name})
SET d.embedding = row.embedding, d.embedding_model = row.embedding_model
"""

EMBEDDINGS = """
MATCH (d:Domain)
RETURN d.name AS name, d.description AS description, d.embedding AS embedding,
       d.embedding_model AS embedding_model
ORDER BY coalesce(d.position, 1000000), d.name
"""

DELETE_RELATED = "MATCH (:Domain)-[r:RELATED_TO]->(:Domain) DELETE r"

CREATE_RELATED = """
UNWIND $pairs AS p
MATCH (a:Domain {name: p.a})
MATCH (b:Domain {name: p.b})
CREATE (a)-[:RELATED_TO {similarity: p.similarity, computed_at: $today}]->(b)
RETURN count(*) AS n
"""

# RELATED_TO is one edge per unordered pair; read it undirected.
RELATED_FOR = """
MATCH (d:Domain {name: $name})-[r:RELATED_TO]-(o:Domain)
RETURN o.name AS domain, r.similarity AS similarity
ORDER BY similarity DESC, domain
"""


async def list_domains() -> list[dict[str, Any]]:
    return await run_read(LIST)


async def find_by_name_ci(name: str) -> str | None:
    rows = await run_read(FIND_BY_NAME_CI, {"name": name})
    return rows[0]["name"] if rows else None


async def set_builtins(rows: list[dict[str, Any]]) -> None:
    await run_write(SET_BUILTINS, {"rows": rows})


async def create(
    *, name: str, description: str, embedding: list[float], embedding_model: str, today: date
) -> str:
    params = {
        "name": name,
        "description": description,
        "embedding": embedding,
        "embedding_model": embedding_model,
        "today": today,
    }
    return (await run_write(CREATE, params))[0]["name"]


async def set_embeddings(rows: list[dict[str, Any]]) -> None:
    if rows:
        await run_write(SET_EMBEDDINGS, {"rows": rows})


async def embeddings() -> list[dict[str, Any]]:
    return await run_read(EMBEDDINGS)


async def rebuild_related(pairs: list[dict[str, Any]], today: date) -> int:
    """Delete all RELATED_TO and create the given pairs in ONE transaction."""

    async def work(tx: AsyncManagedTransaction) -> int:
        await tx_run(tx, DELETE_RELATED)
        if not pairs:
            return 0
        return (await tx_run(tx, CREATE_RELATED, {"pairs": pairs, "today": today}))[0]["n"]

    return await run_in_write_tx(work)


async def related_for(name: str) -> list[dict[str, Any]]:
    return await run_read(RELATED_FOR, {"name": name})
