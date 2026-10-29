"""Wipe the database and load the deterministic synthetic dataset."""

from __future__ import annotations

import logging
import time

from app.core import clock, db
from app.core.config import get_config
from app.models.admin import SeedCounts, SeedResult
from app.repositories import seed_repo
from app.schema import runner as schema_runner
from app.seed.generator import generate
from app.services import busy, domain_service, expertise_service

logger = logging.getLogger(__name__)


async def seed_database() -> SeedResult:
    """Wipe and reload the demo data, then recompute. 409 BUSY if seed/recompute is running.

    Exempt from the 15 s transaction timeout; the duration is logged and returned.
    """
    async with busy.exclusive("seed"):
        with db.no_tx_timeout():
            return await _seed()


async def _seed() -> SeedResult:
    """Generate (in memory) -> wipe -> schema init -> load -> recompute."""
    started = time.perf_counter()
    config = get_config()
    today = clock.today()
    seed = config.seed.seed_random_seed

    # Generate first: if this fails, the database is left untouched.
    dataset = generate(
        seed=seed,
        today=today,
        lookback_months=config.analytics.lookback_months,
        capacity=config.assignment.capacity_default,
    )

    await seed_repo.wipe_all()
    await schema_runner.apply_schema()  # recreates the 5 built-in Domain nodes
    await domain_service.ensure_builtin_domains()  # descriptions + stored embeddings
    await seed_repo.load_sales_people(dataset.sales_people)
    await seed_repo.load_clients(dataset.clients)
    await seed_repo.load_deals(dataset.deals)
    await seed_repo.load_activities(dataset.activities)
    counts = SeedCounts(**await seed_repo.counts())
    recompute = await expertise_service.recompute()  # EXPERTISE_IN + SIMILAR_TO

    duration_ms = round((time.perf_counter() - started) * 1000)
    logger.info(
        "Seeded %d deals, %d clients, %d activities in %d ms (seed=%d, as_of=%s)",
        counts.Deal,
        counts.Client,
        counts.Activity,
        duration_ms,
        seed,
        today,
    )
    return SeedResult(
        counts=counts,
        expertise_edges=recompute.expertise_edges,
        similar_pairs=recompute.similar_pairs,
        duration_ms=duration_ms,
        as_of_date=today,
        seed=seed,
    )
