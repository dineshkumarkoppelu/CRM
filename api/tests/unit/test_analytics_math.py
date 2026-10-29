"""Unit tests for the pure analytics helpers (no database)."""

from __future__ import annotations

from datetime import date

import pytest

from app.services.analytics_service import (
    month_labels,
    quarter_bounds,
    rate,
    round_half_up,
    round_int,
    round_opt,
    zero_fill,
)


@pytest.mark.parametrize(
    ("won", "handled", "expected"),
    [(8, 10, 0.8), (0, 10, 0.0), (1, 3, 0.3333), (2, 3, 0.6667), (5, 5, 1.0), (0, 0, None),
     (3, 0, None)],
)  # fmt: skip
def test_rate_with_null_on_zero(won: int, handled: int, expected: float | None) -> None:
    assert rate(won, handled) == expected


def test_rate_custom_precision() -> None:
    assert rate(1, 3, 2) == 0.33


@pytest.mark.parametrize(
    ("value", "ndigits", "expected"),
    [(0.5, 0, 1.0), (1.5, 0, 2.0), (2.5, 0, 3.0), (0.125, 2, 0.13), (84.85, 1, 84.9),
     (0.00005, 4, 0.0001), (-0.5, 0, -1.0)],
)  # fmt: skip
def test_round_half_up_not_bankers(value: float, ndigits: int, expected: float) -> None:
    assert round_half_up(value, ndigits) == expected


def test_round_helpers_keep_none() -> None:
    assert round_int(None) is None and round_opt(None, 1) is None
    assert round_int(1268118.5) == 1268119
    assert round_opt(84.94, 1) == 84.9


def test_month_labels_within_a_year() -> None:
    labels = month_labels(date(2026, 10, 6))
    assert len(labels) == 12
    assert labels[0] == "2025-11" and labels[-1] == "2026-10"


def test_month_labels_across_year_boundary() -> None:
    assert month_labels(date(2027, 2, 28), 4) == ["2026-11", "2026-12", "2027-01", "2027-02"]
    assert month_labels(date(2026, 1, 31), 2) == ["2025-12", "2026-01"]


def test_month_labels_are_ascending_and_unique() -> None:
    labels = month_labels(date(2026, 3, 31))
    assert labels == sorted(labels) and len(set(labels)) == 12


@pytest.mark.parametrize(
    ("d", "expected"),
    [
        (date(2026, 10, 6), (date(2026, 10, 1), date(2026, 12, 31))),
        (date(2026, 1, 1), (date(2026, 1, 1), date(2026, 3, 31))),
        (date(2026, 3, 31), (date(2026, 1, 1), date(2026, 3, 31))),
        (date(2024, 5, 15), (date(2024, 4, 1), date(2024, 6, 30))),
        (date(2026, 9, 30), (date(2026, 7, 1), date(2026, 9, 30))),
    ],
)
def test_quarter_bounds(d: date, expected: tuple[date, date]) -> None:
    assert quarter_bounds(d) == expected


def test_zero_fill_keeps_order_and_fills_missing() -> None:
    stages = ["LEAD", "QUALIFIED", "PROPOSAL", "NEGOTIATION"]
    filled = zero_fill(stages, {"PROPOSAL": 3, "LEAD": 1})
    assert list(filled) == stages
    assert filled == {"LEAD": 1, "QUALIFIED": 0, "PROPOSAL": 3, "NEGOTIATION": 0}


def test_zero_fill_ignores_unknown_keys() -> None:
    assert zero_fill(["a"], {"a": 2, "b": 9}) == {"a": 2}
