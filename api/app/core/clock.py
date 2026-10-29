"""The ONLY source of "today" in the application (see .kiro/steering/tech.md).

Never call `date.today()` / `datetime.now()` anywhere else. When `AS_OF_DATE` is set, the
whole app behaves as if that were the current date, which makes seeds, tests and demos
deterministic.
"""

from __future__ import annotations

import calendar
from datetime import UTC, date, datetime

from app.core.settings import get_settings


def today() -> date:
    """`AS_OF_DATE` when set, otherwise the real current date."""
    as_of = get_settings().AS_OF_DATE
    return as_of if as_of is not None else date.today()


def utc_now() -> datetime:
    """Real wall-clock time (UTC) for OPERATIONAL timestamps only (e.g. "recompute last ran").

    Not affected by AS_OF_DATE. Never use it for business dates - use `today()`.
    """
    return datetime.now(UTC)


# ---- pure helpers (no settings access; unit-tested directly) ----


def subtract_months(d: date, months: int) -> date:
    """Calendar-month subtraction, clamping the day to the target month's length.

    Example: 2026-03-31 minus 1 month = 2026-02-28.
    """
    if months < 0:
        raise ValueError("months must be >= 0")
    total = d.year * 12 + (d.month - 1) - months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def month_bounds(d: date) -> tuple[date, date]:
    """(first day, last day) of the calendar month containing `d`."""
    last_day = calendar.monthrange(d.year, d.month)[1]
    return date(d.year, d.month, 1), date(d.year, d.month, last_day)


# ---- helpers relative to today() ----


def current_month_bounds() -> tuple[date, date]:
    """(first day, last day) of the month containing today()."""
    return month_bounds(today())


def previous_month_bounds() -> tuple[date, date]:
    """(first day, last day) of the calendar month before the one containing today()."""
    first_of_current, _ = current_month_bounds()
    return month_bounds(subtract_months(first_of_current, 1))


def window_start(months: int) -> date:
    """today() minus `months` calendar months.

    The lookback window is the half-open range (window_start, today], i.e. a deal is in the
    window when `window_start < closed_at <= today` (domain-rules.md section 1).
    """
    return subtract_months(today(), months)
