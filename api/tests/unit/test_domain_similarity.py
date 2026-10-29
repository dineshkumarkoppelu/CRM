"""Unit tests for embedding-based domain similarity and the RELATED fit (no database)."""

from __future__ import annotations

import pytest

from app.core.domains import BUILTIN_DOMAINS, embedding_text
from app.core.embeddings import builtin_embeddings, cosine, normalise
from app.services.domain_service import related_pairs, select_related
from app.services.recommendation_service import (
    Expertise,
    RankingConfig,
    RelatedDomain,
    RepState,
    fit_for,
    rank_candidates,
    related_fit,
)

CFG = RankingConfig(0.7, 0.3, 0.8, 5, related_discount=0.7)


def rep(rep_id: str, open_count: int = 0, capacity: int = 8) -> RepState:
    return RepState(rep_id, f"Rep {rep_id}", True, capacity, open_count)


def exp(won: int, handled: int) -> Expertise:
    return Expertise(handled, won, round(won / handled, 4), handled >= 3)


# ---------------------------------------------------------------- vectors


def test_cosine_and_normalise() -> None:
    assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine([1, 1], [2, 2]) == pytest.approx(1.0)
    assert cosine([0, 0], [1, 0]) == 0.0
    assert normalise([3, 4]) == pytest.approx([0.6, 0.8])
    with pytest.raises(ValueError):
        cosine([1, 2], [1, 2, 3])


def test_builtin_embeddings_file() -> None:
    data = builtin_embeddings()
    assert data["model"] == "BAAI/bge-small-en-v1.5"
    assert list(data["vectors"]) == list(BUILTIN_DOMAINS)
    assert all(len(v) == 384 for v in data["vectors"].values())
    v = data["vectors"]
    # DevOps and Cloud Migration are the closest built-in pair; all pairs are clearly < 1.
    pairs = {(a, b): cosine(v[a], v[b]) for i, a in enumerate(v) for b in list(v)[i + 1 :]}
    assert max(pairs, key=pairs.get) == ("DevOps", "Cloud Migration")
    assert all(0.4 < s < 0.95 for s in pairs.values())


def test_embedding_text() -> None:
    assert embedding_text("IoT", "  Sensors and devices. ") == "IoT: Sensors and devices."


# ---------------------------------------------------------------- related pairs / selection


def test_related_pairs_only_same_model_and_one_per_pair() -> None:
    rows = [
        {"name": "A", "embedding": [1.0, 0.0], "embedding_model": "m"},
        {"name": "B", "embedding": [0.8, 0.6], "embedding_model": "m"},
        {"name": "C", "embedding": [0.0, 1.0], "embedding_model": "other"},
        {"name": "D", "embedding": None, "embedding_model": None},
    ]
    assert related_pairs(rows, "m") == [{"a": "A", "b": "B", "similarity": 0.8}]


def test_select_related_threshold_top_k_and_weights() -> None:
    rows = [
        {"domain": "IoT", "similarity": 0.79},
        {"domain": "Cloud", "similarity": 0.70},
        {"domain": "DevOps", "similarity": 0.69},
        {"domain": "AI", "similarity": 0.67},
        {"domain": "Cyber", "similarity": 0.60},  # below the threshold
    ]
    picked = select_related(rows, top_k=3, min_similarity=0.65)
    assert [(r.domain, r.weight) for r in picked] == [
        ("IoT", 0.14),
        ("Cloud", 0.05),
        ("DevOps", 0.04),
    ]
    assert select_related(rows, top_k=10, min_similarity=0.65)[-1].domain == "AI"
    assert select_related(rows, top_k=3, min_similarity=0.8) == []


# ---------------------------------------------------------------- RELATED fit


RELATED = [RelatedDomain("IoT", 0.79, 0.14), RelatedDomain("Cloud Migration", 0.70, 0.05)]


def test_related_fit_weighted_average_over_all_related_weights() -> None:
    expertise = {("R", "IoT"): exp(8, 10), ("R", "Cloud Migration"): exp(6, 10)}
    fit = related_fit(rep("R", 2), "Edge Computing", expertise, RELATED, 0.7)
    assert fit is not None and fit.fit_type == "RELATED"
    assert fit.fit == pytest.approx(0.7 * (0.14 * 0.8 + 0.05 * 0.6) / 0.19)
    assert fit.reason == (
        "RELATED fit: no track record in Edge Computing yet; wins 80% of IoT (similarity 0.79) "
        "and 60% of Cloud Migration (similarity 0.70); 2/8 open deals."
    )


def test_related_fit_partial_coverage_is_penalised() -> None:
    only_cloud = {("R", "Cloud Migration"): exp(9, 10)}
    fit = related_fit(rep("R"), "Edge Computing", only_cloud, RELATED, 0.7)
    assert fit is not None
    assert fit.fit == pytest.approx(0.7 * 0.05 * 0.9 / 0.19)  # divided by ALL related weights


def test_related_fit_needs_a_qualifying_related_domain() -> None:
    not_qualifying = {("R", "IoT"): Expertise(2, 2, 1.0, False)}
    assert related_fit(rep("R"), "Edge Computing", not_qualifying, RELATED, 0.7) is None
    assert related_fit(rep("R"), "Edge Computing", {}, [], 0.7) is None


def test_ranking_uses_related_when_nobody_has_direct_or_peer() -> None:
    reps = [rep("A", 2), rep("B", 0), rep("C", 4)]
    expertise = {
        ("A", "IoT"): exp(8, 10),
        ("B", "Cloud Migration"): exp(9, 10),
        ("C", "AI"): exp(7, 10),  # no related coverage -> cold start
    }
    result = rank_candidates("Edge Computing", reps, expertise, [], CFG, RELATED)
    types = {c.sales_person_id: c.fit_type for c in result.candidates}
    # C has no related experience: not ranked (its 70% overall rate would otherwise outrank A)
    assert types == {"A": "RELATED", "B": "RELATED"}
    assert result.candidates[0].sales_person_id == "A"


def test_cold_start_only_when_nobody_has_related_experience() -> None:
    reps = [rep("A"), rep("C")]
    expertise = {("C", "AI"): exp(7, 10)}
    result = rank_candidates("Edge Computing", reps, expertise, [], CFG, RELATED)
    assert {c.fit_type for c in result.candidates} == {"COLD_START"}


def test_related_is_not_used_when_someone_has_a_direct_fit() -> None:
    reps = [rep("A"), rep("B")]
    expertise = {("A", "Edge Computing"): exp(5, 10), ("B", "IoT"): exp(9, 10)}
    result = rank_candidates("Edge Computing", reps, expertise, [], CFG, RELATED)
    assert [(c.sales_person_id, c.fit_type) for c in result.candidates] == [("A", "DIRECT")]


def test_fit_for_override_includes_related() -> None:
    expertise = {("R", "IoT"): exp(8, 10)}
    fit = fit_for(rep("R"), "Edge Computing", expertise, [], {}, 0.8, RELATED, 0.7)
    assert fit.fit_type == "RELATED"
