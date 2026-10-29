"""Unit tests for the nightly scheduler and the BUSY guard (no database)."""

from __future__ import annotations

import asyncio

import pytest

from app.core.errors import AppError
from app.services import busy, expertise_service, scheduler


async def test_busy_guard_rejects_a_second_operation() -> None:
    async with busy.exclusive("seed"):
        assert busy.running() == "seed"
        with pytest.raises(AppError) as info:
            async with busy.exclusive("recompute"):
                pass
        assert (info.value.code, info.value.status) == ("BUSY", 409)
        assert info.value.details == {"running": "seed"}
    assert busy.running() is None


async def test_busy_guard_releases_on_error() -> None:
    with pytest.raises(RuntimeError):
        async with busy.exclusive("seed"):
            raise RuntimeError("boom")
    async with busy.exclusive("recompute"):  # free again
        assert busy.running() == "recompute"


async def test_scheduler_start_next_run_and_stop() -> None:
    assert scheduler.next_run_at() is None
    scheduler.start("0 2 * * *")
    try:
        scheduler.start("0 3 * * *")  # second start is ignored
        nxt = scheduler.next_run_at()
        assert nxt is not None and (nxt.hour, nxt.minute) == (2, 0)
    finally:
        scheduler.stop()
    assert scheduler.next_run_at() is None


async def test_scheduled_run_skips_while_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def fake_recompute_exclusive(operation: str = "recompute") -> None:
        calls.append(operation)

    monkeypatch.setattr(expertise_service, "recompute_exclusive", fake_recompute_exclusive)
    async with busy.exclusive("seed"):
        await scheduler._run_recompute()
    assert calls == []
    await scheduler._run_recompute()
    assert calls == ["nightly recompute"]


async def test_scheduled_run_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing(operation: str = "recompute") -> None:
        raise RuntimeError("database down")

    async def busy_error(operation: str = "recompute") -> None:
        raise AppError("BUSY", "seed is running", 409)

    for fake in (failing, busy_error):
        monkeypatch.setattr(expertise_service, "recompute_exclusive", fake)
        await scheduler._run_recompute()  # logged, not raised
    await asyncio.sleep(0)
