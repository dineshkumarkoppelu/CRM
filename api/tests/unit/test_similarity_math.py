"""Unit tests for compute_similar_pairs (no database)."""

from __future__ import annotations

from app.core.domains import DOMAINS
from app.seed.planted import EXPECTED_SIMILAR_PAIRS
from app.seed.profiles import PROFILES
from app.services.expertise_service import compute_similar_pairs


def profile_rows() -> list[dict]:
    """Qualifying (rep, domain, win_rate) rows straight from the profile table."""
    return [
        {"rep_id": p.id, "domain": d, "win_rate": round(won / closed, 4)}
        for p in PROFILES
        for d, (won, closed) in p.window.items()
        if closed >= 3
    ]


def test_profile_table_gives_exactly_the_7_planted_pairs() -> None:
    pairs = compute_similar_pairs(profile_rows(), tolerance=0.10, min_domains=3)
    got = {(p.rep_a, p.rep_b): (p.match_count, round(p.score, 2)) for p in pairs}
    assert got == EXPECTED_SIMILAR_PAIRS


def test_aarav_bhavna_pair_details() -> None:
    pairs = compute_similar_pairs(profile_rows(), tolerance=0.10, min_domains=3)
    pair = next(p for p in pairs if (p.rep_a, p.rep_b) == ("SP-001", "SP-002"))
    assert pair.matched_domains == ["AI", "DevOps", "Cloud Migration"]  # fixed domain order
    assert pair.mean_abs_diff == 0.0 and pair.score == 0.6


def test_pairs_are_ordered_lower_id_first() -> None:
    pairs = compute_similar_pairs(profile_rows(), tolerance=0.10, min_domains=3)
    assert all(p.rep_a < p.rep_b for p in pairs)
    assert [(p.rep_a, p.rep_b) for p in pairs] == sorted((p.rep_a, p.rep_b) for p in pairs)


def test_two_shared_domains_is_not_similar() -> None:
    rows = [
        {"rep_id": "A", "domain": "AI", "win_rate": 0.5},
        {"rep_id": "A", "domain": "IoT", "win_rate": 0.5},
        {"rep_id": "B", "domain": "AI", "win_rate": 0.5},
        {"rep_id": "B", "domain": "IoT", "win_rate": 0.5},
    ]
    assert compute_similar_pairs(rows, tolerance=0.10, min_domains=3) == []


def test_floating_point_edge_080_vs_070_matches_at_010() -> None:
    assert abs(0.8 - 0.7) > 0.10  # the raw difference is 0.10000000000000009
    rows = [{"rep_id": r, "domain": d, "win_rate": wr}
            for r, wr in (("A", 0.8), ("B", 0.7)) for d in DOMAINS[:3]]  # fmt: skip
    pairs = compute_similar_pairs(rows, tolerance=0.10, min_domains=3)
    assert len(pairs) == 1
    assert pairs[0].match_count == 3
    assert pairs[0].mean_abs_diff == 0.1
    assert pairs[0].score == round(3 / 5 * 0.9, 4)


def test_difference_above_tolerance_is_not_matched() -> None:
    rows = [{"rep_id": r, "domain": d, "win_rate": wr}
            for r, wr in (("A", 0.8), ("B", 0.69)) for d in DOMAINS[:3]]  # fmt: skip
    assert compute_similar_pairs(rows, tolerance=0.10, min_domains=3) == []


def test_only_shared_domains_count() -> None:
    rows = [{"rep_id": "A", "domain": d, "win_rate": 0.5} for d in DOMAINS]
    rows += [{"rep_id": "B", "domain": d, "win_rate": 0.5} for d in DOMAINS[:3]]
    (pair,) = compute_similar_pairs(rows, tolerance=0.10, min_domains=3)
    assert pair.matched_domains == list(DOMAINS[:3]) and pair.score == 0.6


def test_config_values_are_parameters() -> None:
    rows = profile_rows()
    strict = compute_similar_pairs(rows, tolerance=0.10, min_domains=5)
    assert {(p.rep_a, p.rep_b) for p in strict} == {("SP-013", "SP-015")}
    loose = compute_similar_pairs(rows, tolerance=0.10, min_domains=3, total_domains=10)
    assert next(p for p in loose if p.rep_a == "SP-013").score == 0.5  # 5/10 * (1 - 0)
