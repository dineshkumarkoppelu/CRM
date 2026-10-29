"""Assignment engine orchestration (domain-rules.md section 6): load inputs from the graph,
rank with the pure `recommendation_service`, write RECOMMENDED_TO / OWNS, override, preview.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core import clock
from app.core.config import get_config
from app.core.errors import AppError
from app.models.assignment import (
    AssignedRep,
    AssignmentResult,
    RecommendationOut,
    UnavailableRep,
)
from app.repositories import deals_repo, recommendation_repo
from app.repositories.recommendation_repo import OwnerConflict
from app.services import domain_service
from app.services import recommendation_service as rs

NO_AVAILABLE_MESSAGE = "No available sales person (all inactive or at capacity)"
OVERRIDE_PREFIX = "Manual override: "


@dataclass(frozen=True)
class _Inputs:
    reps: list[rs.RepState]
    expertise: dict[tuple[str, str], rs.Expertise]
    pairs: list[rs.SimilarPair]

    def rep(self, rep_id: str) -> rs.RepState | None:
        return next((r for r in self.reps if r.id == rep_id), None)


async def _load_inputs() -> _Inputs:
    reps = [rs.RepState(**r) for r in await recommendation_repo.reps_state()]
    expertise = {
        (r["rep_id"], r["domain"]): rs.Expertise(
            handled=r["handled"], won=r["won"], win_rate=r["win_rate"], qualifies=r["qualifies"]
        )
        for r in await recommendation_repo.all_expertise()
    }
    pairs = [
        rs.SimilarPair(r["rep_a"], r["rep_b"], r["score"], tuple(r["matched_domains"]))
        for r in await recommendation_repo.all_similar_pairs()
    ]
    return _Inputs(reps, expertise, pairs)


def _ranking_config() -> rs.RankingConfig:
    a = get_config().assignment
    return rs.RankingConfig(
        weight_fit=a.weight_fit,
        weight_availability=a.weight_availability,
        peer_discount=a.peer_discount,
        max_candidates=a.max_candidates,
        related_discount=get_config().domains.related_discount,
    )


def _unavailable(reps: list[rs.RepState]) -> list[UnavailableRep]:
    return [
        UnavailableRep(
            id=r.id,
            name=r.name,
            reason=rs.INACTIVE if not r.active else rs.AT_CAPACITY,
            open_count=r.open_count,
            capacity=r.capacity,
        )
        for r in sorted(reps, key=lambda r: r.id)
        if not rs.is_available(r)
    ]


def _candidate_out(c: rs.Candidate, status: str) -> RecommendationOut:
    return RecommendationOut(
        sales_person_id=c.sales_person_id,
        name=c.name,
        rank=c.rank,
        score=c.score,
        fit=c.fit,
        availability=c.availability,
        fit_type=c.fit_type,
        reason=c.reason,
        status=status,
    )


def _rec_row(c: rs.Candidate, status: str) -> dict[str, Any]:
    return {
        "sales_person_id": c.sales_person_id,
        "rank": c.rank,
        "score": c.score,
        "fit": c.fit,
        "availability": c.availability,
        "fit_type": c.fit_type,
        "reason": c.reason,
        "status": status,
    }


def _assigned_message(top: rs.Candidate) -> str:
    return f"Assigned to {top.name} ({top.fit_type} fit, score {top.score})"


async def _require_open_deal(deal_id: str) -> dict[str, Any]:
    deal = await deals_repo.get_deal(deal_id)
    if deal is None:
        raise AppError("DEAL_NOT_FOUND", f"Deal {deal_id} not found", 404, {"id": deal_id})
    if deal["status"] != "OPEN":
        raise AppError(
            "DEAL_CLOSED", f"Deal is {deal['status']}; only OPEN deals can be assigned", 400
        )
    return deal


# ---------------------------------------------------------------------------
# Assign / preview
# ---------------------------------------------------------------------------
async def assign_deal(deal_id: str) -> AssignmentResult:
    """Rank and assign an OPEN deal without an owner (one write transaction)."""
    deal = await _require_open_deal(deal_id)
    if deal["owner_id"] is not None:
        raise AppError(
            "ALREADY_ASSIGNED",
            f"Deal {deal_id} is already owned by {deal['owner_name']}",
            409,
            {"owner_id": deal["owner_id"]},
        )
    inputs = await _load_inputs()
    ranking = rs.rank_candidates(
        deal["domain"],
        inputs.reps,
        inputs.expertise,
        inputs.pairs,
        _ranking_config(),
        await domain_service.related_domains(deal["domain"]),
    )
    statuses = ["ASSIGNED" if c.rank == 1 else "CANDIDATE" for c in ranking.candidates]
    top = ranking.candidates[0] if ranking.candidates else None
    try:
        await recommendation_repo.replace_recommendations(
            deal_id,
            [_rec_row(c, s) for c, s in zip(ranking.candidates, statuses, strict=True)],
            owner_id=top.sales_person_id if top else None,
            today=clock.today(),
        )
    except OwnerConflict as exc:
        raise AppError(
            "ALREADY_ASSIGNED", "Deal was assigned or closed by another request", 409
        ) from exc

    return AssignmentResult(
        deal_id=deal_id,
        domain=deal["domain"],
        assignment_status="ASSIGNED" if top else "UNASSIGNED",
        assigned_to=AssignedRep(id=top.sales_person_id, name=top.name) if top else None,
        candidates=[
            _candidate_out(c, s) for c, s in zip(ranking.candidates, statuses, strict=True)
        ],
        unavailable=[UnavailableRep(**u.__dict__) for u in ranking.unavailable],
        message=_assigned_message(top) if top else NO_AVAILABLE_MESSAGE,
    )


async def preview_deal(deal_id: str) -> AssignmentResult:
    """The ranking /run would produce right now. Writes nothing. The current owner (if any)
    is still counted in their open_count."""
    deal = await _require_open_deal(deal_id)
    inputs = await _load_inputs()
    ranking = rs.rank_candidates(
        deal["domain"],
        inputs.reps,
        inputs.expertise,
        inputs.pairs,
        _ranking_config(),
        await domain_service.related_domains(deal["domain"]),
    )
    top = ranking.candidates[0] if ranking.candidates else None
    return AssignmentResult(
        deal_id=deal_id,
        domain=deal["domain"],
        assignment_status="ASSIGNED" if top else "UNASSIGNED",
        assigned_to=AssignedRep(id=top.sales_person_id, name=top.name) if top else None,
        candidates=[
            _candidate_out(c, "ASSIGNED" if c.rank == 1 else "CANDIDATE")
            for c in ranking.candidates
        ],
        unavailable=[UnavailableRep(**u.__dict__) for u in ranking.unavailable],
        message=(
            f"Preview only, nothing saved: would assign to {top.name} "
            f"({top.fit_type} fit, score {top.score})"
            if top
            else f"Preview only, nothing saved: {NO_AVAILABLE_MESSAGE}"
        ),
    )


# ---------------------------------------------------------------------------
# Stored result (GET) and override
# ---------------------------------------------------------------------------
async def get_recommendations(deal_id: str, message: str | None = None) -> AssignmentResult:
    """AssignmentResult from the stored RECOMMENDED_TO edges (no recompute).

    Status: ASSIGNED if the owner holds the ASSIGNED recommendation, MANUAL if the deal has an
    owner otherwise, UNASSIGNED if it has none. `unavailable` reflects current rep state.
    """
    deal = await deals_repo.get_deal(deal_id)
    if deal is None:
        raise AppError("DEAL_NOT_FOUND", f"Deal {deal_id} not found", 404, {"id": deal_id})
    recs = [RecommendationOut(**r) for r in await deals_repo.list_recommendations(deal_id)]
    owner = AssignedRep(id=deal["owner_id"], name=deal["owner_name"]) if deal["owner_id"] else None
    by_engine = any(
        r.status == "ASSIGNED" and owner and r.sales_person_id == owner.id for r in recs
    )
    if owner is None:
        status = "UNASSIGNED"
        default_message = NO_AVAILABLE_MESSAGE if recs == [] else "Deal has no owner"
    elif by_engine:
        status = "ASSIGNED"
        default_message = f"Assigned to {owner.name}"
    else:
        status = "MANUAL"
        default_message = f"Manually assigned to {owner.name}"
    reps = [rs.RepState(**r) for r in await recommendation_repo.reps_state()]
    return AssignmentResult(
        deal_id=deal_id,
        domain=deal["domain"],
        assignment_status=status,
        assigned_to=owner,
        candidates=recs,
        unavailable=_unavailable(reps),
        message=message or default_message,
    )


async def override(deal_id: str, rep_id: str) -> AssignmentResult:
    """Manager override (domain-rules.md section 6 'Override')."""
    deal = await _require_open_deal(deal_id)
    inputs = await _load_inputs()
    target = inputs.rep(rep_id)
    if target is None:
        raise AppError("REP_NOT_FOUND", f"Sales person {rep_id} not found", 404, {"id": rep_id})
    if deal["owner_id"] == rep_id:
        return await get_recommendations(deal_id, f"Already assigned to {target.name}")
    if not rs.is_available(target):
        reason = rs.INACTIVE if not target.active else rs.AT_CAPACITY
        raise AppError(
            "REP_NOT_AVAILABLE",
            f"Sales person {rep_id} is not available ({reason}, "
            f"{target.open_count}/{target.capacity} open deals)",
            409,
            {"id": rep_id, "reason": reason},
        )

    # Used only if the target has no recommendation yet: fit computed as normal (DIRECT, PEER,
    # RELATED, else cold start), availability before the target takes this deal.
    config = _ranking_config()
    fit = rs.fit_for(
        target,
        deal["domain"],
        inputs.expertise,
        inputs.pairs,
        {r.id: r.name for r in inputs.reps},
        config.peer_discount,
        await domain_service.related_domains(deal["domain"]),
        config.related_discount,
    )
    avail = rs.availability(target.open_count, target.capacity)
    new_rec = {
        "sales_person_id": rep_id,
        "rank": 0,
        "score": rs.score_of(fit.fit, avail, config),
        "fit": rs.round_half_up(fit.fit, 4),
        "availability": rs.round_half_up(avail, 4),
        "fit_type": fit.fit_type,
        "reason": OVERRIDE_PREFIX + fit.reason,
        "status": "ASSIGNED",
    }
    try:
        await recommendation_repo.override_owner(deal_id, rep_id, new_rec, clock.today())
    except OwnerConflict as exc:
        raise AppError("DEAL_CLOSED", "Deal was closed by another request", 400) from exc
    return await get_recommendations(deal_id, f"Manual override: assigned to {target.name}")
