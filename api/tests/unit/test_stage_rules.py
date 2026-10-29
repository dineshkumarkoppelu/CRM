"""Unit tests for the stage machine and small CRUD helpers (no database)."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.errors import AppError
from app.services.crud_service import availability, month_range, new_id, next_state

OPEN_STAGES = ["LEAD", "QUALIFIED", "PROPOSAL", "NEGOTIATION"]


# ---- every legal transition ----
@pytest.mark.parametrize(
    ("stage", "action", "expected"),
    [
        ("LEAD", "ADVANCE", ("OPEN", "QUALIFIED", "qualified_at")),
        ("QUALIFIED", "ADVANCE", ("OPEN", "PROPOSAL", "proposal_at")),
        ("PROPOSAL", "ADVANCE", ("OPEN", "NEGOTIATION", "negotiation_at")),
        ("NEGOTIATION", "WIN", ("WON", "NEGOTIATION", "closed_at")),
        ("LEAD", "LOSE", ("LOST", "LEAD", "closed_at")),
        ("QUALIFIED", "LOSE", ("LOST", "QUALIFIED", "closed_at")),
        ("PROPOSAL", "LOSE", ("LOST", "PROPOSAL", "closed_at")),
        ("NEGOTIATION", "LOSE", ("LOST", "NEGOTIATION", "closed_at")),
    ],
)
def test_legal_transitions(stage: str, action: str, expected: tuple[str, str, str]) -> None:
    assert next_state("OPEN", stage, action) == expected


# ---- every illegal transition on an OPEN deal ----
@pytest.mark.parametrize(
    ("stage", "action"),
    [
        ("NEGOTIATION", "ADVANCE"),  # use WIN instead
        ("LEAD", "WIN"),
        ("QUALIFIED", "WIN"),
        ("PROPOSAL", "WIN"),
    ],
)
def test_illegal_transitions(stage: str, action: str) -> None:
    with pytest.raises(AppError) as info:
        next_state("OPEN", stage, action)
    assert info.value.code == "ILLEGAL_STAGE_TRANSITION"
    assert info.value.status == 400


# ---- any action on a closed deal ----
@pytest.mark.parametrize("status", ["WON", "LOST"])
@pytest.mark.parametrize("stage", OPEN_STAGES)
@pytest.mark.parametrize("action", ["ADVANCE", "WIN", "LOSE"])
def test_closed_deals_cannot_move(status: str, stage: str, action: str) -> None:
    with pytest.raises(AppError) as info:
        next_state(status, stage, action)
    assert info.value.code == "DEAL_CLOSED"
    assert info.value.status == 400


def test_unknown_action_and_stage_are_illegal() -> None:
    for stage, action in [("LEAD", "JUMP"), ("BOGUS", "LOSE"), ("BOGUS", "ADVANCE")]:
        with pytest.raises(AppError) as info:
            next_state("OPEN", stage, action)
        assert info.value.code == "ILLEGAL_STAGE_TRANSITION"


def test_moves_never_go_backwards_or_skip() -> None:
    order = {stage: i for i, stage in enumerate(OPEN_STAGES)}
    for stage in OPEN_STAGES[:-1]:
        _, new_stage, _ = next_state("OPEN", stage, "ADVANCE")
        assert order[new_stage] == order[stage] + 1


# ---- helpers ----
@pytest.mark.parametrize(
    ("open_count", "capacity", "expected"),
    [(0, 8, 1.0), (2, 8, 0.75), (8, 8, 0.0), (10, 8, 0.0), (5, 2, 0.0), (1, 0, 0.0)],
)
def test_availability_is_clamped(open_count: int, capacity: int, expected: float) -> None:
    assert availability(open_count, capacity) == expected


@pytest.mark.parametrize(
    ("month", "expected"),
    [
        ("2026-10", (date(2026, 10, 1), date(2026, 10, 31))),
        ("2024-02", (date(2024, 2, 1), date(2024, 2, 29))),
        ("2026-12", (date(2026, 12, 1), date(2026, 12, 31))),
    ],
)
def test_month_range(month: str, expected: tuple[date, date]) -> None:
    assert month_range(month) == expected


def test_new_id_format() -> None:
    for prefix in ("SP", "CL", "DL", "AC"):
        value = new_id(prefix)
        head, tail = value.split("-")
        assert head == prefix and len(tail) == 8
        int(tail, 16)  # hex
    assert new_id("DL") != new_id("DL")
