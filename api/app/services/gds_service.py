"""Rule-based vs GDS similarity, side by side (Phase 7). Never used for assignment.

What the two scores mean (they are EXPECTED to differ):
- Rule score (Phase 6, domain-rules.md section 5): are the two reps' win rates CLOSE (within
  the tolerance) in enough shared qualifying domains? A yes/no rule plus a score.
- GDS score: weighted Jaccard over the reps' qualifying domains, weighted by win rate:
  sum(min(wr_a, wr_b)) / sum(max(wr_a, wr_b)) across the union of their domains. It measures
  how much their domain footprints OVERLAP (and how heavily), not how close the rates are.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from neo4j.exceptions import ClientError

from app.core import db
from app.core.errors import AppError
from app.models.analytics import SimilarityCompareRow
from app.repositories import gds_repo
from app.services.analytics_service import round_half_up

logger = logging.getLogger(__name__)

GRAPH_PREFIX = "rep_domain_"
TOP_GDS_PAIRS = 20

COMPARE_NOTE = (
    "rule_score: win rates within the tolerance in enough shared domains (used for assignment). "
    "gds_score: weighted Jaccard of the reps' qualifying domains weighted by win rate (overlap "
    "of domain footprints). They measure different things and are expected to differ."
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def unordered_gds_pairs(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], float]:
    """GDS streams both (a, b) and (b, a); keep one per unordered pair (lower id first), 4 dp."""
    pairs: dict[tuple[str, str], float] = {}
    for row in rows:
        a, b = sorted((row["rep_1"], row["rep_2"]))
        if a == b:
            continue
        score = round_half_up(row["similarity"], 4)
        pairs[(a, b)] = max(score, pairs.get((a, b), score))
    return pairs


def top_pairs(gds: Mapping[tuple[str, str], float], n: int) -> list[tuple[str, str]]:
    return [k for k, _ in sorted(gds.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]


def merge_rows(
    rule: Iterable[Mapping[str, Any]], gds: Mapping[tuple[str, str], float], top_n: int
) -> list[SimilarityCompareRow]:
    """Union of all rule pairs and the top-N GDS pairs. Sorted by gds_score desc (nulls last),
    then rule_score desc (nulls last), then ids."""
    rule_by_pair = {(r["rep_a"], r["rep_b"]): r for r in rule}
    keys = set(rule_by_pair) | set(top_pairs(gds, top_n))
    rows = [
        SimilarityCompareRow(
            rep_a=a,
            rep_b=b,
            rule_score=rule_by_pair[(a, b)]["rule_score"] if (a, b) in rule_by_pair else None,
            rule_matched_domains=(
                list(rule_by_pair[(a, b)]["rule_matched_domains"])
                if (a, b) in rule_by_pair
                else None
            ),
            gds_score=gds.get((a, b)),
        )
        for a, b in keys
    ]
    rows.sort(
        key=lambda r: (
            r.gds_score is None,
            -(r.gds_score or 0.0),
            r.rule_score is None,
            -(r.rule_score or 0.0),
            r.rep_a,
            r.rep_b,
        )
    )
    return rows


# ---------------------------------------------------------------------------
# GDS run (DB)
# ---------------------------------------------------------------------------
async def gds_similarity() -> dict[tuple[str, str], float]:
    """Project, stream weighted Node Similarity, ALWAYS drop the projection."""
    graph_name = f"{GRAPH_PREFIX}{uuid.uuid4().hex[:12]}"  # unique: concurrent calls never collide
    top_k = max(1, await gds_repo.count_reps() - 1)
    try:
        projected = await gds_repo.project(graph_name)
        if not projected or projected["relationship_count"] == 0:
            return {}
        return unordered_gds_pairs(await gds_repo.node_similarity(graph_name, top_k))
    except ClientError as exc:
        if "gds." in str(exc.message or "") or "ProcedureNotFound" in str(exc.code or ""):
            raise AppError(
                "GDS_UNAVAILABLE", "Graph Data Science plugin is not available", 503
            ) from exc
        raise
    finally:
        try:
            await gds_repo.drop(graph_name)
        except Exception:  # never mask the original result/error
            logger.warning("Could not drop GDS projection %s", graph_name, exc_info=True)


async def compare(persist: bool = False) -> list[SimilarityCompareRow]:
    """Exempt from the 15 s transaction timeout: the first GDS call after a Neo4j restart
    warms up the GDS engine and can take 30-50 s. The duration is logged."""
    started = time.perf_counter()
    with db.no_tx_timeout():
        rows = await _compare(persist)
    logger.info(
        "Similarity compare: %d rows in %d ms", len(rows), (time.perf_counter() - started) * 1000
    )
    return rows


async def _compare(persist: bool) -> list[SimilarityCompareRow]:
    gds = await gds_similarity()
    rule = await gds_repo.rule_pairs()
    if persist:
        updated = await gds_repo.persist_gds_scores(
            [{"rep_a": a, "rep_b": b, "gds_score": score} for (a, b), score in gds.items()]
        )
        logger.info("Persisted gds_score on %d existing SIMILAR_TO edges", updated)
    return merge_rows(rule, gds, TOP_GDS_PAIRS)
