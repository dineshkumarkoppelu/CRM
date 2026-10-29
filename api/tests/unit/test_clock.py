"""Unit tests for app.core.clock (no database)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.core import clock
from app.core.settings import Settings


@pytest.fixture
def as_of(monkeypatch: pytest.MonkeyPatch):
    """Pin clock.today() to a given date (or None for the real date)."""

    def _set(value: date | None) -> None:
        monkeypatch.setattr(clock, "get_settings", lambda: SimpleNamespace(AS_OF_DATE=value))

    return _set


def test_today_uses_as_of_date(as_of) -> None:
    as_of(date(2026, 10, 6))
    assert clock.today() == date(2026, 10, 6)


def test_today_falls_back_to_real_date(as_of) -> None:
    as_of(None)
    assert clock.today() == date.today()


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        (date(2026, 10, 6), 12, date(2025, 10, 6)),  # domain-rules.md example
        (date(2026, 3, 31), 1, date(2026, 2, 28)),  # month-end clamp
        (date(2024, 3, 31), 1, date(2024, 2, 29)),  # leap year
        (date(2026, 5, 31), 1, date(2026, 4, 30)),
        (date(2026, 1, 15), 1, date(2025, 12, 15)),  # year boundary
        (date(2026, 2, 28), 12, date(2025, 2, 28)),
        (date(2024, 2, 29), 12, date(2023, 2, 28)),
        (date(2026, 10, 6), 18, date(2025, 4, 6)),
        (date(2026, 10, 6), 0, date(2026, 10, 6)),
    ],
)
def test_subtract_months(start: date, months: int, expected: date) -> None:
    assert clock.subtract_months(start, months) == expected


def test_subtract_months_rejects_negative() -> None:
    with pytest.raises(ValueError):
        clock.subtract_months(date(2026, 1, 1), -1)


@pytest.mark.parametrize(
    ("d", "expected"),
    [
        (date(2026, 10, 6), (date(2026, 10, 1), date(2026, 10, 31))),
        (date(2024, 2, 10), (date(2024, 2, 1), date(2024, 2, 29))),
        (date(2026, 2, 28), (date(2026, 2, 1), date(2026, 2, 28))),
        (date(2026, 12, 31), (date(2026, 12, 1), date(2026, 12, 31))),
    ],
)
def test_month_bounds(d: date, expected: tuple[date, date]) -> None:
    assert clock.month_bounds(d) == expected


def test_current_month_bounds(as_of) -> None:
    as_of(date(2026, 10, 6))
    assert clock.current_month_bounds() == (date(2026, 10, 1), date(2026, 10, 31))


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (date(2026, 10, 6), (date(2026, 9, 1), date(2026, 9, 30))),
        (date(2026, 1, 1), (date(2025, 12, 1), date(2025, 12, 31))),  # year boundary
        (date(2026, 3, 31), (date(2026, 2, 1), date(2026, 2, 28))),  # month-end
        (date(2024, 3, 31), (date(2024, 2, 1), date(2024, 2, 29))),  # leap year
    ],
)
def test_previous_month_bounds(as_of, today: date, expected: tuple[date, date]) -> None:
    as_of(today)
    assert clock.previous_month_bounds() == expected


def test_window_start(as_of) -> None:
    as_of(date(2026, 10, 6))
    # Window is (2025-10-06, 2026-10-06], i.e. 2025-10-07 ... 2026-10-06 inclusive.
    assert clock.window_start(12) == date(2025, 10, 6)


def test_window_start_month_end(as_of) -> None:
    as_of(date(2026, 3, 31))
    assert clock.window_start(1) == date(2026, 2, 28)


@pytest.mark.parametrize("raw", ["", "  "])
def test_empty_as_of_date_means_not_set(raw: str) -> None:
    settings = Settings(NEO4J_PASSWORD="unit-test-only", AS_OF_DATE=raw)
    assert settings.AS_OF_DATE is None


def test_as_of_date_parses_iso() -> None:
    settings = Settings(NEO4J_PASSWORD="unit-test-only", AS_OF_DATE="2026-10-06")
    assert settings.AS_OF_DATE == date(2026, 10, 6)
