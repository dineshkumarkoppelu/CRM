"""Unit tests for the pure GDS comparison helpers (no database)."""

from __future__ import annotations

from app.services.gds_service import merge_rows, top_pairs, unordered_gds_pairs


def test_unordered_pairs_dedupe_and_round() -> None:
    rows = [
        {"rep_1": "SP-002", "rep_2": "SP-001", "similarity": 0.714285714},
        {"rep_1": "SP-001", "rep_2": "SP-002", "similarity": 0.714285714},
        {"rep_1": "SP-003", "rep_2": "SP-003", "similarity": 1.0},  # self-pair ignored
    ]
    assert unordered_gds_pairs(rows) == {("SP-001", "SP-002"): 0.7143}


def test_top_pairs_ties_by_id() -> None:
    gds = {("B", "C"): 0.5, ("A", "C"): 0.5, ("A", "B"): 0.9}
    assert top_pairs(gds, 2) == [("A", "B"), ("A", "C")]


def test_merge_union_nulls_and_order() -> None:
    rule = [
        {"rep_a": "A", "rep_b": "B", "rule_score": 0.6, "rule_matched_domains": ["AI"]},
        {"rep_a": "C", "rep_b": "D", "rule_score": 0.8, "rule_matched_domains": ["IoT"]},
    ]
    gds = {("A", "B"): 0.7, ("E", "F"): 0.9, ("G", "H"): 0.1}
    rows = merge_rows(rule, gds, top_n=1)  # only the single best GDS pair is added
    assert [(r.rep_a, r.rep_b) for r in rows] == [("E", "F"), ("A", "B"), ("C", "D")]
    ef, ab, cd = rows
    assert ef.rule_score is None and ef.rule_matched_domains is None
    assert ab.gds_score == 0.7 and ab.rule_matched_domains == ["AI"]
    assert cd.gds_score is None  # rule pair without a GDS score sorts last
