"""Unit tests for rank_candidates and the reason templates (no database)."""

from __future__ import annotations

import pytest

from app.seed.planted import CAPACITY_SCENARIO, PEER_SCENARIO
from app.seed.profiles import PROFILES
from app.services.expertise_service import compute_similar_pairs
from app.services.recommendation_service import (
    Expertise,
    RankingConfig,
    RepState,
    SimilarPair,
    fit_for,
    join_domains,
    pct,
    rank_candidates,
)

CFG = RankingConfig(weight_fit=0.7, weight_availability=0.3, peer_discount=0.8, max_candidates=5)


def rep(rep_id: str, open_count: int = 0, capacity: int = 8, active: bool = True) -> RepState:
    return RepState(rep_id, f"Rep {rep_id}", active, capacity, open_count)


def exp(won: int, handled: int) -> Expertise:
    return Expertise(handled, won, round(won / handled, 4), handled >= 3)


# ---------------------------------------------------------------- helpers


def test_join_domains() -> None:
    assert join_domains(["AI"]) == "AI"
    assert join_domains(["AI", "IoT"]) == "AI and IoT"
    assert join_domains(["AI", "DevOps", "Cloud Migration"]) == "AI, DevOps and Cloud Migration"


def test_pct_is_half_up() -> None:
    assert pct(0.8) == 80 and pct(0.665) == 67 and pct(0.6667) == 67 and pct(0.125) == 13


# ---------------------------------------------------------------- DIRECT / PEER / mixed


def test_direct_only_and_reason() -> None:
    reps = [rep("A", 2), rep("B", 4)]
    expertise = {("A", "AI"): exp(6, 10), ("B", "AI"): exp(9, 10)}
    result = rank_candidates("AI", reps, expertise, [], CFG)
    top, second = result.candidates
    assert top.sales_person_id == "B"  # 0.7*0.9 + 0.3*0.5 = 0.78 > 0.7*0.6 + 0.3*0.75 = 0.645
    assert (top.score, top.fit, top.availability, top.fit_type) == (0.78, 0.9, 0.5, "DIRECT")
    assert top.reason == "DIRECT fit: wins 90% of AI deals (9/10); 4/8 open deals."
    assert second.score == 0.645 and second.rank == 2


def test_peer_only_and_reason() -> None:
    reps = [rep("A", 8), rep("B", 2)]  # A is at capacity, B has no IoT history
    expertise = {
        ("A", "IoT"): exp(8, 10), ("A", "AI"): exp(7, 10), ("A", "DevOps"): exp(6, 10),
        ("B", "AI"): exp(7, 10), ("B", "DevOps"): exp(6, 10),
    }  # fmt: skip
    pairs = [SimilarPair("A", "B", 0.6, ("AI", "DevOps"))]
    result = rank_candidates("IoT", reps, expertise, pairs, CFG)
    (only,) = result.candidates
    assert only.sales_person_id == "B" and only.fit_type == "PEER"
    assert only.fit == 0.64 and only.score == 0.673
    assert only.reason == (
        "PEER fit: matches Rep A in AI and DevOps (within 0 pts); Rep A wins 80% of IoT deals; "
        "2/8 open deals."
    )
    assert [(u.id, u.reason) for u in result.unavailable] == [("A", "AT_CAPACITY")]


def test_peer_fit_is_weighted_by_similarity_and_names_the_strongest_peer() -> None:
    reps = [rep("R"), rep("P1", 8), rep("P2", 8), rep("P3", 8)]
    expertise = {
        ("P1", "IoT"): exp(9, 10),  # strongest: 0.2 * 0.9 = 0.18
        ("P2", "IoT"): exp(6, 10),  # 0.25 * 0.6 = 0.15
        ("P3", "IoT"): Expertise(4, 0, 0.0, True),  # won 0 -> not a contributing peer
        ("R", "AI"): exp(5, 10), ("P1", "AI"): exp(5, 10), ("P2", "AI"): exp(4, 10),
    }  # fmt: skip
    pairs = [
        SimilarPair("P1", "R", 0.2, ("AI",)),
        SimilarPair("P2", "R", 0.25, ("AI",)),
        SimilarPair("P3", "R", 0.9, ("AI",)),
    ]
    (c,) = rank_candidates("IoT", reps, expertise, pairs, CFG).candidates
    assert c.fit == round(0.8 * (0.2 * 0.9 + 0.25 * 0.6) / 0.45, 4)
    assert "matches Rep P1 in AI (within 0 pts); Rep P1 wins 90% of IoT deals" in c.reason


def test_peer_must_qualify_in_the_domain() -> None:
    reps = [rep("R"), rep("P", 8)]
    expertise = {("P", "IoT"): Expertise(2, 2, 1.0, False)}  # only 2 deals: not qualifying
    pairs = [SimilarPair("P", "R", 0.6, ("AI",))]
    (c,) = rank_candidates("IoT", reps, expertise, pairs, CFG).candidates
    assert c.fit_type == "COLD_START"


def test_mixed_direct_and_peer_and_reps_without_fit_are_not_ranked() -> None:
    reps = [rep("D", 4), rep("P", 0), rep("N", 0), rep("X", 8)]
    expertise = {
        ("D", "AI"): exp(5, 10), ("X", "AI"): exp(9, 10),
        ("P", "DevOps"): exp(5, 10), ("X", "DevOps"): exp(5, 10),
        ("N", "DevOps"): exp(1, 10),
    }  # fmt: skip
    pairs = [SimilarPair("P", "X", 0.4, ("DevOps",))]
    result = rank_candidates("AI", reps, expertise, pairs, CFG)
    assert [(c.sales_person_id, c.fit_type) for c in result.candidates] == [
        ("P", "PEER"),  # 0.7 * 0.72 + 0.3 * 1.0 = 0.804
        ("D", "DIRECT"),  # 0.7 * 0.5 + 0.3 * 0.5 = 0.5
    ]
    assert "N" not in {c.sales_person_id for c in result.candidates}  # no fit, not cold start


# ---------------------------------------------------------------- availability


def test_unavailable_reps_are_excluded_and_listed() -> None:
    reps = [rep("A", 1, active=False), rep("B", 8), rep("C", 9), rep("D", 1)]
    expertise = {(r, "AI"): exp(9, 10) for r in "ABCD"}
    result = rank_candidates("AI", reps, expertise, [], CFG)
    assert [c.sales_person_id for c in result.candidates] == ["D"]
    assert [(u.id, u.reason, u.open_count, u.capacity) for u in result.unavailable] == [
        ("A", "INACTIVE", 1, 8), ("B", "AT_CAPACITY", 8, 8), ("C", "AT_CAPACITY", 9, 8),
    ]  # fmt: skip


def test_nobody_available() -> None:
    result = rank_candidates("AI", [rep("A", 8), rep("B", 1, active=False)], {}, [], CFG)
    assert result.candidates == [] and len(result.unavailable) == 2


# ---------------------------------------------------------------- cold start


def test_cold_start_uses_overall_win_rate_and_reason() -> None:
    reps = [rep("A", 2), rep("B", 0)]
    expertise = {("A", "AI"): exp(3, 4), ("A", "DevOps"): Expertise(2, 1, 0.5, False)}
    result = rank_candidates("IoT", reps, expertise, [], CFG)
    a = next(c for c in result.candidates if c.sales_person_id == "A")
    b = next(c for c in result.candidates if c.sales_person_id == "B")
    assert a.fit_type == b.fit_type == "COLD_START"
    assert a.fit == round(4 / 6, 4) and b.fit == 0.0
    assert a.reason == "No domain history for IoT: overall win rate 67%; 2/8 open deals."
    assert b.reason == "No domain history for IoT: overall win rate 0%; 0/8 open deals."


# ---------------------------------------------------------------- ordering and cap


def test_tie_break_score_then_fit_then_open_count_then_id() -> None:
    # A and B: same score 0.7*0.6 + 0.3*0.5 = 0.57; C: fit 0.5 + avail 0.7333 -> 0.57 too
    reps = [rep("B", 4), rep("A", 4), rep("C", 4, capacity=15)]
    expertise = {("A", "AI"): exp(6, 10), ("B", "AI"): exp(6, 10), ("C", "AI"): exp(5, 10)}
    result = rank_candidates("AI", reps, expertise, [], CFG)
    assert [c.score for c in result.candidates] == [0.57, 0.57, 0.57]
    assert [c.sales_person_id for c in result.candidates] == ["A", "B", "C"]  # fit, then id


def test_tie_break_open_count_before_id() -> None:
    reps = [rep("A", 4, capacity=8), rep("B", 2, capacity=4)]  # same availability 0.5
    expertise = {("A", "AI"): exp(6, 10), ("B", "AI"): exp(6, 10)}
    result = rank_candidates("AI", reps, expertise, [], CFG)
    assert [c.sales_person_id for c in result.candidates] == ["B", "A"]


def test_max_candidates_cap_and_ranks() -> None:
    reps = [rep(f"R{i:02d}") for i in range(9)]
    expertise = {(r.id, "AI"): exp(5, 10) for r in reps}
    result = rank_candidates("AI", reps, expertise, [], CFG)
    assert len(result.candidates) == 5 and [c.rank for c in result.candidates] == [1, 2, 3, 4, 5]
    cap2 = RankingConfig(0.7, 0.3, 0.8, 2)
    assert len(rank_candidates("AI", reps, expertise, [], cap2).candidates) == 2


# ---------------------------------------------------------------- planted scenarios (pure)


def _profile_inputs() -> tuple[list[RepState], dict, list[SimilarPair]]:
    reps = [RepState(p.id, p.name, True, 8, p.open_deals) for p in PROFILES]
    expertise = {
        (p.id, d): exp(won, closed) for p in PROFILES for d, (won, closed) in p.window.items()
    }
    rows = [{"rep_id": r, "domain": d, "win_rate": e.win_rate}
            for (r, d), e in expertise.items() if e.qualifies]  # fmt: skip
    pairs = [
        SimilarPair(p.rep_a, p.rep_b, p.score, tuple(p.matched_domains))
        for p in compute_similar_pairs(rows, 0.10, 3)
    ]
    return reps, expertise, pairs


@pytest.mark.parametrize("scenario", [PEER_SCENARIO, CAPACITY_SCENARIO])
def test_planted_scenarios_from_the_profile_table(scenario: dict) -> None:
    reps, expertise, pairs = _profile_inputs()
    result = rank_candidates(scenario["domain"], reps, expertise, pairs, CFG)
    top = result.candidates[0]
    assert top.sales_person_id == scenario["expected_assignee"]
    assert top.fit_type == scenario["fit_type"]
    assert top.score == scenario["expected_score"]
    assert [c.sales_person_id for c in result.candidates] == scenario["expected_top5"]
    assert {u.id: u.reason for u in result.unavailable} == scenario["expected_unavailable"]


def test_peer_scenario_reason_text() -> None:
    reps, expertise, pairs = _profile_inputs()
    top = rank_candidates("IoT", reps, expertise, pairs, CFG).candidates[0]
    assert top.reason == (
        "PEER fit: matches Aarav Mehta in AI, DevOps and Cloud Migration (within 0 pts); "
        "Aarav Mehta wins 80% of IoT deals; 2/8 open deals."
    )


def test_window_trap_rohan_has_no_direct_cybersecurity_fit() -> None:
    reps, expertise, pairs = _profile_inputs()
    result = rank_candidates("Cybersecurity", reps, expertise, pairs, CFG)
    assert "SP-003" not in {c.sales_person_id for c in result.candidates}


def test_fit_for_falls_back_to_cold_start() -> None:
    reps, expertise, pairs = _profile_inputs()
    names = {r.id: r.name for r in reps}
    rohan = next(r for r in reps if r.id == "SP-003")
    assert fit_for(rohan, "Cybersecurity", expertise, pairs, names, 0.8).fit_type == "COLD_START"
    divya = next(r for r in reps if r.id == "SP-006")
    assert fit_for(divya, "Cybersecurity", expertise, pairs, names, 0.8).fit_type == "DIRECT"
