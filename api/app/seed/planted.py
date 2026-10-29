"""Planted-scenario constants (phase-02 R2.2).

Derived by hand from the profile table and the formulas in domain-rules.md, assuming the
default config.yaml and a FRESHLY seeded database. Tests (and later the demo script) import
these; they are the acceptance tests for Phase 6.
"""

from __future__ import annotations

PEER_SCENARIO: dict = {
    "domain": "IoT",
    "expected_assignee": "SP-002",
    "fit_type": "PEER",
    "peer": "SP-001",
    "matched_domains": ["AI", "DevOps", "Cloud Migration"],
    "expected_score": 0.673,
    "expected_top5": ["SP-002", "SP-014", "SP-009", "SP-010", "SP-011"],
    "expected_unavailable": {"SP-001": "AT_CAPACITY", "SP-005": "AT_CAPACITY"},
}

CAPACITY_SCENARIO: dict = {
    "domain": "Cybersecurity",
    "expected_assignee": "SP-006",
    "fit_type": "DIRECT",
    "expected_score": 0.64,
    # SP-008, SP-013 and SP-015 tie at 0.4625 and are ordered by the tie-break.
    "expected_top5": ["SP-006", "SP-007", "SP-008", "SP-013", "SP-015"],
    # SP-005 (best Cybersecurity win rate) is the one the demo points at.
    "expected_unavailable": {"SP-001": "AT_CAPACITY", "SP-005": "AT_CAPACITY"},
}

WINDOW_TRAP: dict = {
    "rep": "SP-003",
    "domain": "Cybersecurity",
    # Must have NO qualifying Cybersecurity expertise (all 5 such deals are outside the window).
}

# Exactly these 7 pairs, lower id first: (rep_a, rep_b) -> (match_count, score rounded to 2 dp)
EXPECTED_SIMILAR_PAIRS: dict[tuple[str, str], tuple[int, float]] = {
    ("SP-001", "SP-002"): (3, 0.60),
    ("SP-008", "SP-013"): (3, 0.59),
    ("SP-008", "SP-015"): (3, 0.59),
    ("SP-009", "SP-010"): (3, 0.54),
    ("SP-011", "SP-014"): (3, 0.57),
    ("SP-012", "SP-014"): (4, 0.80),
    ("SP-013", "SP-015"): (5, 1.00),
}

EXPECTED_EXPERTISE_EDGES = 55
