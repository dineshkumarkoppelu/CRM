"""Pure ranking maths for the assignment engine (domain-rules.md section 6). NO database access.

Inputs are plain data loaded by `assignment_service`; everything here is unit-tested.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from app.core.numbers import round_half_up

DIRECT = "DIRECT"
PEER = "PEER"
RELATED = "RELATED"
COLD_START = "COLD_START"
INACTIVE = "INACTIVE"
AT_CAPACITY = "AT_CAPACITY"


@dataclass(frozen=True)
class RepState:
    id: str
    name: str
    active: bool
    capacity: int
    open_count: int


@dataclass(frozen=True)
class Expertise:
    """One EXPERTISE_IN edge (rep, domain) - handled >= 1 in the window."""

    handled: int
    won: int
    win_rate: float
    qualifies: bool


@dataclass(frozen=True)
class SimilarPair:
    rep_a: str
    rep_b: str
    score: float
    matched_domains: tuple[str, ...]


@dataclass(frozen=True)
class RankingConfig:
    weight_fit: float
    weight_availability: float
    peer_discount: float
    max_candidates: int
    related_discount: float = 0.7


@dataclass(frozen=True)
class RelatedDomain:
    """A domain similar to the deal's domain (embedding similarity) and its weight."""

    domain: str
    similarity: float
    weight: float  # > 0; a RELATED fit is the weighted average over these


@dataclass(frozen=True)
class Fit:
    fit: float
    fit_type: str
    reason: str


@dataclass(frozen=True)
class Candidate:
    sales_person_id: str
    name: str
    rank: int
    score: float
    fit: float
    availability: float
    fit_type: str
    reason: str
    open_count: int


@dataclass(frozen=True)
class UnavailableRep:
    id: str
    name: str
    reason: str  # INACTIVE / AT_CAPACITY
    open_count: int
    capacity: int


@dataclass(frozen=True)
class RankingResult:
    candidates: list[Candidate]  # top max_candidates, rank 1 first
    unavailable: list[UnavailableRep]  # by id


ExpertiseMap = Mapping[tuple[str, str], Expertise]  # (rep_id, domain) -> edge


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def availability(open_count: int, capacity: int) -> float:
    """1 - open_count / capacity, clamped to [0, 1] (domain-rules.md section 2)."""
    if capacity <= 0:
        return 0.0
    return max(0.0, min(1.0, 1 - open_count / capacity))


def is_available(rep: RepState) -> bool:
    return rep.active and rep.open_count < rep.capacity


def pct(value: float) -> int:
    """Whole percentage points, half-up (0.665 -> 67)."""
    return int(round_half_up(value * 100, 0))


def join_domains(domains: Sequence[str]) -> str:
    """'AI' / 'AI and IoT' / 'AI, DevOps and Cloud Migration'."""
    if len(domains) <= 1:
        return "".join(domains)
    return ", ".join(domains[:-1]) + " and " + domains[-1]


def _load(rep: RepState) -> str:
    return f"{rep.open_count}/{rep.capacity} open deals."


def peers_by_rep(pairs: Iterable[SimilarPair]) -> dict[str, list[SimilarPair]]:
    """SIMILAR_TO is undirected: index each pair under both reps."""
    index: dict[str, list[SimilarPair]] = defaultdict(list)
    for pair in pairs:
        index[pair.rep_a].append(pair)
        index[pair.rep_b].append(pair)
    return dict(index)


def overall_win_rate(rep_id: str, expertise: ExpertiseMap) -> float:
    """Won / handled over all of the rep's domains in the window (0 if no closed deals)."""
    won = handled = 0
    for (rid, _), edge in expertise.items():
        if rid == rep_id:
            won += edge.won
            handled += edge.handled
    return won / handled if handled else 0.0


# ---------------------------------------------------------------------------
# Fit (Step 2 and Step 3)
# ---------------------------------------------------------------------------
def direct_fit(rep: RepState, domain: str, expertise: ExpertiseMap) -> Fit | None:
    edge = expertise.get((rep.id, domain))
    if edge is None or not edge.qualifies:
        return None
    reason = (
        f"DIRECT fit: wins {pct(edge.win_rate)}% of {domain} deals "
        f"({edge.won}/{edge.handled}); {_load(rep)}"
    )
    return Fit(edge.win_rate, DIRECT, reason)


def peer_fit(
    rep: RepState,
    domain: str,
    expertise: ExpertiseMap,
    peers: Mapping[str, list[SimilarPair]],
    names: Mapping[str, str],
    peer_discount: float,
) -> Fit | None:
    """Borrow the domain win rate of similar reps who qualify in D with >= 1 win there."""
    contributions: list[tuple[str, float, float, SimilarPair]] = []  # (peer, score, wr, pair)
    for pair in peers.get(rep.id, []):
        peer_id = pair.rep_b if pair.rep_a == rep.id else pair.rep_a
        edge = expertise.get((peer_id, domain))
        if edge is not None and edge.qualifies and edge.won >= 1:
            contributions.append((peer_id, pair.score, edge.win_rate, pair))
    total_score = sum(c[1] for c in contributions)
    if not contributions or total_score <= 0:
        return None

    fit = peer_discount * sum(score * wr for _, score, wr, _ in contributions) / total_score
    peer_id, _, peer_wr, pair = min(contributions, key=lambda c: (-(c[1] * c[2]), c[0]))
    diffs = [
        abs(expertise[(rep.id, d)].win_rate - expertise[(peer_id, d)].win_rate)
        for d in pair.matched_domains
        if (rep.id, d) in expertise and (peer_id, d) in expertise
    ]
    peer_name = names.get(peer_id, peer_id)
    reason = (
        f"PEER fit: matches {peer_name} in {join_domains(list(pair.matched_domains))} "
        f"(within {pct(max(diffs, default=0.0))} pts); {peer_name} wins {pct(peer_wr)}% of "
        f"{domain} deals; {_load(rep)}"
    )
    return Fit(fit, PEER, reason)


def related_fit(
    rep: RepState,
    domain: str,
    expertise: ExpertiseMap,
    related: Sequence[RelatedDomain],
    related_discount: float,
) -> Fit | None:
    """Borrow the rep's OWN win rates in domains similar to D (used when nobody has a DIRECT
    or PEER fit, typically a newly added domain).

    fit = discount * sum(weight * win_rate(R, Dk) for Dk where R qualifies) / sum(all weights)
    Dividing by ALL the related weights means a rep covering only a weakly related domain
    gets a proportionally smaller fit.
    """
    total_weight = sum(r.weight for r in related)
    contributions = [
        (r, expertise[(rep.id, r.domain)])
        for r in related
        if (rep.id, r.domain) in expertise and expertise[(rep.id, r.domain)].qualifies
    ]
    if not contributions or total_weight <= 0:
        return None
    fit = related_discount * sum(r.weight * e.win_rate for r, e in contributions) / total_weight
    parts = [
        f"{pct(e.win_rate)}% of {r.domain} (similarity {r.similarity:.2f})"
        for r, e in contributions
    ]
    reason = (
        f"RELATED fit: no track record in {domain} yet; wins {join_domains(parts)}; {_load(rep)}"
    )
    return Fit(fit, RELATED, reason)


def cold_start_fit(rep: RepState, domain: str, expertise: ExpertiseMap) -> Fit:
    wr = overall_win_rate(rep.id, expertise)
    reason = f"No domain history for {domain}: overall win rate {pct(wr)}%; {_load(rep)}"
    return Fit(wr, COLD_START, reason)


def fit_for(
    rep: RepState,
    domain: str,
    expertise: ExpertiseMap,
    pairs: Iterable[SimilarPair],
    names: Mapping[str, str],
    peer_discount: float,
    related: Sequence[RelatedDomain] = (),
    related_discount: float = 0.7,
) -> Fit:
    """DIRECT, else PEER, else RELATED, else COLD_START - used for a manual override target."""
    return (
        direct_fit(rep, domain, expertise)
        or peer_fit(rep, domain, expertise, peers_by_rep(pairs), names, peer_discount)
        or related_fit(rep, domain, expertise, related, related_discount)
        or cold_start_fit(rep, domain, expertise)
    )


def score_of(fit: float, avail: float, config: RankingConfig) -> float:
    return round_half_up(config.weight_fit * fit + config.weight_availability * avail, 4)


# ---------------------------------------------------------------------------
# Ranking (Steps 1-5)
# ---------------------------------------------------------------------------
def rank_candidates(
    domain: str,
    reps: Sequence[RepState],
    expertise: ExpertiseMap,
    pairs: Iterable[SimilarPair],
    config: RankingConfig,
    related: Sequence[RelatedDomain] = (),
) -> RankingResult:
    names = {r.id: r.name for r in reps}
    peers = peers_by_rep(pairs)

    # Step 1 - eligibility
    eligible = [r for r in reps if is_available(r)]
    unavailable = [
        UnavailableRep(r.id, r.name, INACTIVE if not r.active else AT_CAPACITY, r.open_count,
                       r.capacity)
        for r in sorted(reps, key=lambda r: r.id)
        if not is_available(r)
    ]  # fmt: skip

    # Step 2 - DIRECT / PEER fit
    fits: list[tuple[RepState, Fit]] = []
    for rep in eligible:
        fit = direct_fit(rep, domain, expertise) or peer_fit(
            rep, domain, expertise, peers, names, config.peer_discount
        )
        if fit is not None:
            fits.append((rep, fit))
    # Step 3 - tiers, like Step 2: only if nobody has a DIRECT/PEER fit (e.g. a newly added
    # domain), rank the reps that have a RELATED fit (own win rates in similar domains). Reps
    # without one are not ranked, so an undiscounted overall win rate can never outrank real
    # related experience. COLD_START only if nobody has a RELATED fit either.
    if not fits:
        for rep in eligible:
            fit = related_fit(rep, domain, expertise, related, config.related_discount)
            if fit is not None:
                fits.append((rep, fit))
    if not fits:
        fits = [(rep, cold_start_fit(rep, domain, expertise)) for rep in eligible]

    # Step 4 - score; Step 5 - sort and keep the top max_candidates
    scored = []
    for rep, fit in fits:
        fit_value = round_half_up(fit.fit, 4)
        avail = round_half_up(availability(rep.open_count, rep.capacity), 4)
        scored.append((score_of(fit.fit, avail, config), fit_value, avail, rep, fit))
    scored.sort(key=lambda s: (-s[0], -s[1], s[3].open_count, s[3].id))

    candidates = [
        Candidate(rep.id, rep.name, rank, score, fit_value, avail, fit.fit_type, fit.reason,
                  rep.open_count)
        for rank, (score, fit_value, avail, rep, fit) in enumerate(
            scored[: config.max_candidates], start=1
        )
    ]  # fmt: skip
    return RankingResult(candidates=candidates, unavailable=unavailable)
