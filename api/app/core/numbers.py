"""Small numeric helpers shared by the services."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def round_half_up(value: float, ndigits: int) -> float:
    """Decimal half-up rounding (Python's round() is banker's rounding on binary floats)."""
    quantum = Decimal(1).scaleb(-ndigits)
    return float(Decimal(repr(float(value))).quantize(quantum, rounding=ROUND_HALF_UP))
