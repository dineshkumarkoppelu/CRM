"""Nightly EXPERTISE_IN / SIMILAR_TO recompute (APScheduler AsyncIOScheduler).

Started in the FastAPI lifespan only when SCHEDULER_ENABLED=true (tests disable it). The cron
expression comes from config.yaml `scheduler.recompute_cron` and runs in server local time.
"""

from __future__ import annotations

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.errors import AppError
from app.services import busy, expertise_service

logger = logging.getLogger(__name__)

JOB_ID = "nightly_recompute"

_scheduler: AsyncIOScheduler | None = None


async def _run_recompute() -> None:
    running = busy.running()
    if running is not None:
        logger.info("Scheduled recompute skipped: %s is running", running)
        return
    try:
        await expertise_service.recompute_exclusive("nightly recompute")
    except AppError as exc:
        logger.info("Scheduled recompute skipped: %s", exc.message)
    except Exception:  # never let a failed run kill the scheduler
        logger.exception("Scheduled recompute failed")


def start(cron: str) -> None:
    """Start the scheduler with one job. Must be called with a running event loop."""
    global _scheduler
    if _scheduler is not None:
        return
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _run_recompute,
        CronTrigger.from_crontab(cron),
        id=JOB_ID,
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info("Scheduler started: recompute cron %r, next run %s", cron, next_run_at())


def stop() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def next_run_at() -> datetime | None:
    if _scheduler is None:
        return None
    job = _scheduler.get_job(JOB_ID)
    return job.next_run_time if job else None
