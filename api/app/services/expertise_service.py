"""EXPERTISE_IN and SIMILAR_TO recompute (domain-rules.md sections 4-5).

`compute_similar_pairs` is pure and unit-tested. One "recompute" = expertise, then similarity.
The last result is kept in memory for GET /api/admin/recompute/status.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from app.core import clock, db
from app.core.config import get_config
from app.core.domains import BUILTIN_DOMAINS
from app.core.numbers import round_half_up
from app.models.assignment import RecomputeResult
from app.repositories import expertise_repo
from app.services import busy, domain_service

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SimilarPairOut:
    rep_a: str
    rep_b: str
    matched_domains: list[str]
    match_count: int
    mean_abs_diff: float  # 4 dp
    score: float  # 4 dp


def compute_similar_pairs(
    rows: Iterable[Mapping[str, Any]],
    tolerance: float,
    min_domains: int,
    total_domains: int = len(BUILTIN_DOMAINS),
    domain_order: Sequence[str] = BUILTIN_DOMAINS,
) -> list[SimilarPairOut]:
    """Pairs of reps similar per section 5. `rows` = QUALIFYING edges (rep_id, domain, win_rate).

    The rounded difference is compared with the tolerance (0.80 vs 0.70 must match at 0.10).
    Output: rep_a < rep_b, matched domains in the fixed domain order, sorted by (rep_a, rep_b).
    """
    rates: dict[str, dict[str, float]] = defaultdict(dict)
    for row in rows:
        rates[row["rep_id"]][row["domain"]] = row["win_rate"]

    reps = sorted(rates)
    pairs: list[SimilarPairOut] = []
    for i, rep_a in enumerate(reps):
        for rep_b in reps[i + 1 :]:
            diffs = {
                d: abs(rates[rep_a][d] - rates[rep_b][d])
                for d in domain_order
                if d in rates[rep_a] and d in rates[rep_b]
            }
            matched = [d for d, diff in diffs.items() if round(diff, 4) <= tolerance]
            if len(matched) < min_domains:
                continue
            mean_abs_diff = sum(diffs[d] for d in matched) / len(matched)
            score = (len(matched) / total_domains) * (1 - mean_abs_diff)
            pairs.append(
                SimilarPairOut(
                    rep_a=rep_a,
                    rep_b=rep_b,
                    matched_domains=matched,
                    match_count=len(matched),
                    mean_abs_diff=round_half_up(mean_abs_diff, 4),
                    score=round_half_up(score, 4),
                )
            )
    return pairs


# ---------------------------------------------------------------------------
# Recompute (DB)
# ---------------------------------------------------------------------------
_last_run_at: datetime | None = None
_last_result: RecomputeResult | None = None


def last_run() -> tuple[datetime | None, RecomputeResult | None]:
    return _last_run_at, _last_result


async def recompute_exclusive(operation: str = "recompute") -> RecomputeResult:
    """`recompute()` under the admin lock: 409 BUSY if a seed or recompute is running."""
    async with busy.exclusive(operation):
        return await recompute()


async def recompute() -> RecomputeResult:
    """Rebuild EXPERTISE_IN, then SIMILAR_TO. Idempotent (full rebuild each time).

    Callers outside a seed should use `recompute_exclusive`. Exempt from the 15 s transaction
    timeout; the duration is logged and returned.
    """
    with db.no_tx_timeout():
        return await _recompute()


async def _recompute() -> RecomputeResult:
    global _last_run_at, _last_result
    started = time.perf_counter()
    config = get_config()
    today = clock.today()

    expertise_edges = await expertise_repo.rebuild_expertise(
        window_start=clock.window_start(config.analytics.lookback_months),
        today=today,
        min_deals=config.expertise.min_deals_per_domain,
    )
    # The rule adjusts to the live domain list: score = match_count / (number of domains) * ...
    all_domains = await domain_service.domain_names()
    pairs = compute_similar_pairs(
        await expertise_repo.qualifying_expertise(),
        tolerance=config.similarity.similarity_tolerance,
        min_domains=config.similarity.similarity_min_domains,
        total_domains=len(all_domains),
        domain_order=all_domains,
    )
    similar_pairs = await expertise_repo.rebuild_similarity([asdict(p) for p in pairs], today)
    related_pairs = await domain_service.rebuild_related()  # domain-to-domain (embeddings)

    result = RecomputeResult(
        expertise_edges=expertise_edges,
        similar_pairs=similar_pairs,
        related_pairs=related_pairs,
        duration_ms=round((time.perf_counter() - started) * 1000),
        computed_at=today,
    )
    _last_run_at, _last_result = clock.utc_now(), result
    logger.info(
        "Recompute: %d EXPERTISE_IN, %d SIMILAR_TO, %d RELATED_TO (%d domains) in %d ms",
        expertise_edges,
        similar_pairs,
        related_pairs,
        len(all_domains),
        result.duration_ms,
    )
    return result


async def recompute_if_missing() -> bool:
    """On startup: if deals exist but no EXPERTISE_IN does, recompute once. True if it ran."""
    counts = await expertise_repo.counts()
    if counts["deals"] > 0 and counts["expertise_edges"] == 0:
        logger.info("No EXPERTISE_IN found but %d deals exist: running recompute", counts["deals"])
        await recompute()
        return True
    return False
