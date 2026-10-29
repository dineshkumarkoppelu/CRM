"""Cypher for the GDS similarity comparison (Phase 7). Read-only except `persist_gds_scores`.

GDS catalog calls run in auto-commit transactions: a managed transaction may be retried by the
driver, which would try to project the same graph name twice.
"""

from __future__ import annotations

from typing import Any

from app.core.db import run_auto_commit, run_read, run_write

# Cypher (aggregation) projection over QUALIFYING expertise only, weighted by win_rate.
PROJECT = """
MATCH (s:SalesPerson)-[e:EXPERTISE_IN]->(d:Domain)
WHERE e.qualifies = true
WITH gds.graph.project($graph_name, s, d, {relationshipProperties: {win_rate: e.win_rate}}) AS g
RETURN g.graphName AS graph_name, g.nodeCount AS node_count,
       g.relationshipCount AS relationship_count
"""

# Weighted Jaccard over the reps' domain neighbourhoods. Only SalesPerson nodes have outgoing
# relationships in the projection, so only rep-rep pairs come back; the label check is a guard.
NODE_SIMILARITY = """
CALL gds.nodeSimilarity.stream($graph_name, {
  relationshipWeightProperty: 'win_rate',
  similarityMetric: 'JACCARD',
  topK: $top_k,
  similarityCutoff: 0.0
})
YIELD node1, node2, similarity
WITH gds.util.asNode(node1) AS a, gds.util.asNode(node2) AS b, similarity
WHERE a:SalesPerson AND b:SalesPerson
RETURN a.id AS rep_1, b.id AS rep_2, similarity
"""

DROP = """
CALL gds.graph.drop($graph_name, false) YIELD graphName
RETURN graphName AS graph_name
"""

LIST_GRAPHS = "CALL gds.graph.list() YIELD graphName RETURN graphName AS graph_name"

COUNT_REPS = "MATCH (s:SalesPerson) RETURN count(s) AS n"

RULE_PAIRS = """
MATCH (a:SalesPerson)-[r:SIMILAR_TO]->(b:SalesPerson)
RETURN a.id AS rep_a, b.id AS rep_b, r.score AS rule_score,
       r.matched_domains AS rule_matched_domains
"""

# Only updates edges that already exist; never creates SIMILAR_TO.
PERSIST_GDS_SCORES = """
UNWIND $pairs AS p
MATCH (a:SalesPerson {id: p.rep_a})-[r:SIMILAR_TO]->(b:SalesPerson {id: p.rep_b})
SET r.gds_score = p.gds_score
RETURN count(r) AS updated
"""


async def project(graph_name: str) -> dict[str, Any] | None:
    rows = await run_auto_commit(PROJECT, {"graph_name": graph_name})
    return rows[0] if rows else None


async def node_similarity(graph_name: str, top_k: int) -> list[dict[str, Any]]:
    return await run_auto_commit(NODE_SIMILARITY, {"graph_name": graph_name, "top_k": top_k})


async def drop(graph_name: str) -> None:
    await run_auto_commit(DROP, {"graph_name": graph_name})


async def list_graph_names() -> list[str]:
    return [r["graph_name"] for r in await run_auto_commit(LIST_GRAPHS)]


async def count_reps() -> int:
    return (await run_read(COUNT_REPS))[0]["n"]


async def rule_pairs() -> list[dict[str, Any]]:
    return await run_read(RULE_PAIRS)


async def persist_gds_scores(pairs: list[dict[str, Any]]) -> int:
    if not pairs:
        return 0
    return (await run_write(PERSIST_GDS_SCORES, {"pairs": pairs}))[0]["updated"]
