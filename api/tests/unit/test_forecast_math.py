"""Unit tests for the forecast math (no database)."""

from __future__ import annotations

from datetime import date

import pytest

from app.services.forecast_service import (
    REP_DOMAIN_STAGE,
    TEAM_DOMAIN_STAGE,
    TEAM_STAGE,
    ScoredDeal,
    at_least,
    build_backtest,
    build_forecast,
    build_probability_table,
    client_probability,
    reached_stages,
    stage_as_of,
    totals,
)

D = date(2026, 5, 1)


def closed(owner: str | None, domain: str, status: str, reached: str = "LEAD") -> dict:
    """A closed deal row that reached `reached` (stage dates set up to that stage)."""
    order = ["LEAD", "QUALIFIED", "PROPOSAL", "NEGOTIATION"]
    upto = order.index(reached)
    return {
        "owner_id": owner,
        "domain": domain,
        "status": status,
        "qualified_at": D if upto >= 1 else None,
        "proposal_at": D if upto >= 2 else None,
        "negotiation_at": D if upto >= 3 else None,
        "closed_at": D,
    }


def deal(
    deal_id: str, owner: str, client: str, p: float, value: int = 100, stage: str = "LEAD"
) -> ScoredDeal:
    return ScoredDeal(deal_id, owner, client, f"Client {client}", stage, value, p, TEAM_STAGE)


# ---------------------------------------------------------------- reached stages


def test_reached_stages() -> None:
    assert reached_stages(closed("R", "AI", "LOST")) == ["LEAD"]
    assert reached_stages(closed("R", "AI", "WON", "NEGOTIATION")) == [
        "LEAD", "QUALIFIED", "PROPOSAL", "NEGOTIATION",
    ]  # fmt: skip


# ---------------------------------------------------------------- fallback chain


def test_level_1_rep_domain_stage() -> None:
    rows = [closed("R1", "IoT", "WON", "PROPOSAL")] * 3 + [closed("R1", "IoT", "LOST", "PROPOSAL")]
    table = build_probability_table(rows, min_sample=3)
    assert table.lookup("R1", "IoT", "PROPOSAL") == (0.75, REP_DOMAIN_STAGE)
    assert table.lookup("R1", "IoT", "LEAD") == (0.75, REP_DOMAIN_STAGE)  # all reached LEAD


def test_level_2_team_domain_stage_when_rep_sample_too_small() -> None:
    rows = [closed("R1", "IoT", "WON", "QUALIFIED")] * 2  # rep: only 2 < 3
    rows += [closed("R2", "IoT", "LOST", "QUALIFIED")] * 2  # team IoT: 4
    table = build_probability_table(rows, min_sample=3)
    assert table.lookup("R1", "IoT", "QUALIFIED") == (0.5, TEAM_DOMAIN_STAGE)


def test_level_3_team_stage_when_domain_sample_too_small() -> None:
    rows = [closed("R1", "IoT", "WON", "NEGOTIATION")]  # IoT team: 1
    rows += [closed("R2", "AI", "WON", "NEGOTIATION")] * 2
    rows += [closed("R3", "DevOps", "LOST", "NEGOTIATION")]
    table = build_probability_table(rows, min_sample=3)
    assert table.lookup("R1", "IoT", "NEGOTIATION") == (0.75, TEAM_STAGE)


def test_team_stage_is_used_even_below_minimum() -> None:
    table = build_probability_table([closed("R1", "AI", "WON", "NEGOTIATION")], min_sample=3)
    assert table.lookup("R9", "IoT", "NEGOTIATION") == (1.0, TEAM_STAGE)


def test_empty_history_gives_zero_team_stage() -> None:
    assert build_probability_table([], 3).lookup("R1", "AI", "LEAD") == (0.0, TEAM_STAGE)


def test_unowned_closed_deals_count_only_at_team_level() -> None:
    rows = [closed(None, "AI", "WON")] * 3
    table = build_probability_table(rows, min_sample=3)
    assert table.lookup("R1", "AI", "LEAD") == (1.0, TEAM_DOMAIN_STAGE)


def test_population_is_deals_that_reached_the_stage() -> None:
    # 2 deals lost at LEAD do not count for PROPOSAL.
    rows = [closed("R1", "AI", "LOST")] * 2 + [closed("R1", "AI", "WON", "PROPOSAL")] * 3
    table = build_probability_table(rows, min_sample=3)
    assert table.lookup("R1", "AI", "PROPOSAL") == (1.0, REP_DOMAIN_STAGE)
    assert table.lookup("R1", "AI", "LEAD") == (0.6, REP_DOMAIN_STAGE)


# ---------------------------------------------------------------- client probability


@pytest.mark.parametrize(
    ("ps", "expected"),
    [([0.4], 0.4), ([0.5, 0.5], 0.75), ([0.0], 0.0), ([0.0, 0.0], 0.0), ([1.0], 1.0),
     ([1.0, 0.2], 1.0), ([0.2, 0.3, 0.5], 0.72), ([], 0.0)],
)  # fmt: skip
def test_client_probability(ps: list[float], expected: float) -> None:
    assert client_probability(ps) == pytest.approx(expected)


# ---------------------------------------------------------------- thresholds


def test_threshold_edges() -> None:
    assert at_least(0.70, 0.70) is True  # exactly 0.70 is commit
    assert at_least(1 - (1 - 0.7), 0.70) is True  # float noise around the threshold
    assert at_least(0.6999, 0.70) is False
    assert at_least(0.30, 0.30) is True
    assert at_least(0.2999, 0.30) is False


def test_totals_commit_and_best_case() -> None:
    deals = [
        deal("D1", "R1", "C1", 0.70),
        deal("D2", "R1", "C2", 0.30),
        deal("D3", "R1", "C3", 0.29),
    ]
    t = totals(deals, commit_threshold=0.70, best_threshold=0.30)
    assert (t.commit, t.best_case) == (1, 2)
    assert t.expected_conversions == pytest.approx(1.29)
    assert t.expected_revenue == pytest.approx(129.0)


# ---------------------------------------------------------------- stage as of


@pytest.mark.parametrize(
    ("dates", "expected"),
    [
        ({}, "LEAD"),
        ({"qualified_at": date(2026, 8, 20)}, "QUALIFIED"),
        ({"qualified_at": date(2026, 9, 1)}, "QUALIFIED"),  # on asof counts
        ({"qualified_at": date(2026, 9, 2)}, "LEAD"),  # after asof does not
        ({"qualified_at": date(2026, 8, 1), "proposal_at": date(2026, 8, 10),
          "negotiation_at": date(2026, 9, 15)}, "PROPOSAL"),
        ({"qualified_at": date(2026, 8, 1), "proposal_at": date(2026, 8, 10),
          "negotiation_at": date(2026, 8, 31)}, "NEGOTIATION"),
    ],
)  # fmt: skip
def test_stage_as_of(dates: dict, expected: str) -> None:
    row = {"qualified_at": None, "proposal_at": None, "negotiation_at": None, **dates}
    assert stage_as_of(row, date(2026, 9, 1)) == expected


# ---------------------------------------------------------------- shaping


REPS = [
    {"id": "R1", "name": "Rep One"},
    {"id": "R2", "name": "Rep Two"},
    {"id": "R3", "name": "Idle"},
]


def test_build_forecast_rep_and_team_views() -> None:
    scored = [
        deal("D1", "R1", "C1", 0.5, 1000),
        deal("D2", "R1", "C1", 0.5, 1000),  # same client -> P = 0.75
        deal("D3", "R2", "C1", 0.6, 500),  # same client, other owner
        deal("D4", "R2", "C2", 0.2, 500),
    ]
    out = build_forecast(
        month="2026-10", scored=scored, reps=REPS, converted_by_rep={"R2": 3},
        converted_team=3, commit_threshold=0.7, best_threshold=0.3,
    )  # fmt: skip
    rows = {r.sales_person_id: r for r in out.by_rep}
    assert [r.sales_person_id for r in out.by_rep] == ["R2", "R1", "R3"]  # 0.8 > 0.75 > 0
    assert rows["R1"].expected_conversions == 0.75 and rows["R1"].commit == 1
    assert rows["R2"].expected_conversions == 0.8 and rows["R2"].converted_so_far == 3
    assert rows["R3"].expected_conversions == 0 and rows["R3"].clients == []
    assert rows["R1"].clients[0].probability == 0.75 and len(rows["R1"].clients[0].deals) == 2
    # Team: C1 over all owners = 1 - 0.5*0.5*0.4 = 0.9; C2 = 0.2
    assert out.team.expected_conversions == 1.1
    assert out.team.commit == 1 and out.team.best_case == 1
    assert out.team.expected_revenue == 1000 * 0.5 * 2 + 500 * 0.6 + 500 * 0.2


def test_by_rep_sorted_by_expected_desc() -> None:
    scored = [deal("D1", "R1", "C1", 0.1), deal("D2", "R2", "C2", 0.9)]
    out = build_forecast(
        month="2026-10", scored=scored, reps=REPS, converted_by_rep={}, converted_team=0,
        commit_threshold=0.7, best_threshold=0.3,
    )  # fmt: skip
    assert [r.sales_person_id for r in out.by_rep] == ["R2", "R1", "R3"]


def test_build_backtest_errors() -> None:
    scored = [deal("D1", "R1", "C1", 0.5), deal("D2", "R2", "C2", 0.25)]
    out = build_backtest(
        month="2026-09", asof=date(2026, 9, 1), scored=scored, reps=REPS,
        actual_by_rep={"R1": 1, "R3": 2}, actual_team=3, commit_threshold=0.7,
        best_threshold=0.3,
    )  # fmt: skip
    rows = {r.sales_person_id: r for r in out.by_rep}
    assert (rows["R1"].predicted_expected, rows["R1"].actual, rows["R1"].abs_error) == (0.5, 1, 0.5)
    assert rows["R2"].abs_error == 0.25 and rows["R3"].abs_error == 2.0
    assert out.mean_abs_error == round((0.5 + 0.25 + 2.0) / 3, 2)
    assert out.team.predicted_expected == 0.75 and out.team.abs_error == 2.25
    assert len(out.limitations) == 2
