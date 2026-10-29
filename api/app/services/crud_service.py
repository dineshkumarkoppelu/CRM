"""CRUD business rules for sales people, clients, deals and activities (phase-03).

Includes the pure stage-transition function `next_state` (domain-rules.md section 3).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import date
from enum import Enum
from typing import Any

from neo4j.exceptions import ConstraintError

from app.core import clock
from app.core.config import get_config
from app.core.errors import AppError
from app.models.activities import ActivityCreate, ActivityOut
from app.models.assignment import AssignedRep, AssignmentResult
from app.models.clients import ClientCreateResult, ClientDetail, ClientOut, ClientWithDealCreate
from app.models.common import DealStatus, Page, Stage, StageAction
from app.models.deals import DealCreate, DealCreateResult, DealDetail, DealOut, DealUpdate
from app.models.salespeople import (
    ExpertiseOut,
    SalesPersonCreate,
    SalesPersonDetail,
    SalesPersonOut,
    SalesPersonUpdate,
    SimilarPeerOut,
)
from app.repositories import activities_repo, clients_repo, deals_repo, salespeople_repo
from app.services import assignment_service, domain_service
from app.services.recommendation_service import availability

__all__ = ["availability", "month_range", "new_id", "next_state"]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure rules
# ---------------------------------------------------------------------------
_ADVANCE: dict[str, tuple[str, str]] = {
    Stage.LEAD: (Stage.QUALIFIED, "qualified_at"),
    Stage.QUALIFIED: (Stage.PROPOSAL, "proposal_at"),
    Stage.PROPOSAL: (Stage.NEGOTIATION, "negotiation_at"),
}


def next_state(current_status: str, current_stage: str, action: str) -> tuple[str, str, str]:
    """(new_status, new_stage, date_field_to_stamp) for a stage action.

    ADVANCE: one stage forward (not from NEGOTIATION - use WIN). WIN: only from NEGOTIATION.
    LOSE: from any open stage; the stage is unchanged. Any action on a closed deal: DEAL_CLOSED.
    """
    if current_status != DealStatus.OPEN:
        raise AppError(
            "DEAL_CLOSED",
            f"Deal is {current_status}; closed deals cannot change stage",
            400,
            {"status": str(current_status), "action": str(action)},
        )
    details = {"stage": str(current_stage), "action": str(action)}
    if action == StageAction.ADVANCE:
        if current_stage not in _ADVANCE:
            raise AppError(
                "ILLEGAL_STAGE_TRANSITION",
                f"Cannot ADVANCE from {current_stage}; use WIN or LOSE",
                400,
                details,
            )
        new_stage, field = _ADVANCE[current_stage]
        return DealStatus.OPEN.value, str(new_stage), field
    if action == StageAction.WIN:
        if current_stage != Stage.NEGOTIATION:
            raise AppError(
                "ILLEGAL_STAGE_TRANSITION",
                f"WIN is only allowed from NEGOTIATION (deal is at {current_stage})",
                400,
                details,
            )
        return DealStatus.WON.value, Stage.NEGOTIATION.value, "closed_at"
    if action == StageAction.LOSE:
        if current_stage not in set(Stage):
            raise AppError(
                "ILLEGAL_STAGE_TRANSITION", f"Unknown stage {current_stage}", 400, details
            )
        return DealStatus.LOST.value, str(current_stage), "closed_at"
    raise AppError("ILLEGAL_STAGE_TRANSITION", f"Unknown action {action}", 400, details)


def month_range(closing_month: str) -> tuple[date, date]:
    """'YYYY-MM' -> (first day, last day)."""
    year, month = (int(part) for part in closing_month.split("-"))
    return clock.month_bounds(date(year, month, 1))


def new_id(prefix: str) -> str:
    """API-created ids: prefix + first 8 hex chars of a UUID4 (tech.md), e.g. DL-3f9a1c2e."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _not_found(code: str, what: str, entity_id: str) -> AppError:
    return AppError(code, f"{what} {entity_id} not found", 404, {"id": entity_id})


def _plain(changes: dict[str, Any]) -> dict[str, Any]:
    """Enum members -> their string values (for Cypher parameters)."""
    return {k: (v.value if isinstance(v, Enum) else v) for k, v in changes.items()}


async def _with_id_retry[T](create: Callable[[], Awaitable[T]]) -> T:
    """Run `create` (which generates fresh ids each call); retry once on an id collision."""
    try:
        return await create()
    except ConstraintError:
        logger.warning("Generated id collided with an existing one; retrying once")
    try:
        return await create()
    except ConstraintError as exc:
        raise AppError("ID_CONFLICT", "Could not generate a unique id; please retry", 409) from exc


async def _require_rep(rep_id: str) -> dict[str, Any]:
    rep = await salespeople_repo.get_sales_person(rep_id)
    if rep is None:
        raise _not_found("REP_NOT_FOUND", "Sales person", rep_id)
    return rep


async def _require_deal(deal_id: str) -> dict[str, Any]:
    deal = await deals_repo.get_deal(deal_id)
    if deal is None:
        raise _not_found("DEAL_NOT_FOUND", "Deal", deal_id)
    return deal


async def _check_manual_owner(owner_id: str | None) -> dict[str, Any] | None:
    """The rep for a manual assignment: must exist (404) and be active (409).

    Being at capacity is allowed (the manager decides) - the result carries a warning.
    """
    if owner_id is None:
        return None
    rep = await _require_rep(owner_id)
    if not rep["active"]:
        raise AppError(
            "REP_NOT_AVAILABLE", f"Sales person {owner_id} is inactive", 409, {"id": owner_id}
        )
    return rep


def _manual_assignment(deal_id: str, domain: str, rep: dict[str, Any]) -> AssignmentResult:
    open_count, capacity = rep["open_count"], rep["capacity"]
    if open_count >= capacity:
        message = f"Rep is at capacity ({open_count}/{capacity})"
    else:
        message = f"Manually assigned to {rep['name']}"
    return AssignmentResult(
        deal_id=deal_id,
        domain=domain,
        assignment_status="MANUAL",
        assigned_to=AssignedRep(id=rep["id"], name=rep["name"]),
        candidates=[],
        unavailable=[],
        message=message,
    )


async def _assignment_for_new_deal(
    deal_id: str, domain: str, owner: dict[str, Any] | None
) -> AssignmentResult:
    if owner is not None:
        return _manual_assignment(deal_id, domain, owner)
    return await assignment_service.assign_deal(deal_id)


# ---------------------------------------------------------------------------
# Sales people
# ---------------------------------------------------------------------------
async def list_sales_people(active: bool | None, limit: int, offset: int) -> Page[SalesPersonOut]:
    rows = await salespeople_repo.list_sales_people(active, limit, offset)
    total = await salespeople_repo.count_sales_people(active)
    return Page[SalesPersonOut](items=[SalesPersonOut(**r) for r in rows], total=total)


async def get_sales_person(rep_id: str) -> SalesPersonDetail:
    rep = await _require_rep(rep_id)
    edges = {r["domain"]: r for r in await salespeople_repo.list_expertise(rep_id)}
    empty = {"handled": 0, "won": 0, "lost": 0, "win_rate": None, "qualifies": False,
             "last_won_at": None}  # fmt: skip
    expertise = [  # every domain in display order; no edge = no closed deals in the window
        ExpertiseOut(**{**empty, **edges.get(domain, {}), "domain": domain})
        for domain in await domain_service.domain_names()
    ]
    peers = [SimilarPeerOut(**r) for r in await salespeople_repo.list_similar_peers(rep_id)]
    return SalesPersonDetail(
        **rep,
        availability=availability(rep["open_count"], rep["capacity"]),
        expertise=expertise,
        similar_peers=peers,
    )


async def create_sales_person(body: SalesPersonCreate) -> SalesPersonOut:
    capacity = body.capacity or get_config().assignment.capacity_default

    async def create() -> dict[str, Any]:
        return await salespeople_repo.create_sales_person(
            rep_id=new_id("SP"),
            name=body.name,
            email=body.email,
            region=body.region.value,
            joined_on=body.joined_on,
            active=body.active,
            capacity=capacity,
        )

    return SalesPersonOut(**await _with_id_retry(create))


async def update_sales_person(rep_id: str, body: SalesPersonUpdate) -> SalesPersonOut:
    changes = _plain(body.model_dump(exclude_unset=True))
    if not changes:
        return SalesPersonOut(**await _require_rep(rep_id))
    row = await salespeople_repo.update_sales_person(rep_id, changes)
    if row is None:
        raise _not_found("REP_NOT_FOUND", "Sales person", rep_id)
    return SalesPersonOut(**row)


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------
async def list_clients(q: str | None, limit: int, offset: int) -> Page[ClientOut]:
    search = q.strip() if q and q.strip() else None
    rows, total = await clients_repo.list_clients(search, limit, offset)
    return Page[ClientOut](items=[ClientOut(**r) for r in rows], total=total)


async def get_client(client_id: str) -> ClientDetail:
    client = await clients_repo.get_client(client_id)
    if client is None:
        raise _not_found("CLIENT_NOT_FOUND", "Client", client_id)
    deals = [DealOut(**r) for r in await deals_repo.list_deals_for_client(client_id)]
    return ClientDetail(**client, deals=deals)


async def create_client_with_deal(body: ClientWithDealCreate) -> ClientCreateResult:
    """Client + first deal in ONE transaction, then the assignment hook (or MANUAL owner)."""
    domain = await domain_service.require_domain(body.deal.domain)
    owner = await _check_manual_owner(body.deal.owner_id)
    today = clock.today()

    async def create() -> dict[str, Any]:
        return await clients_repo.create_client_with_deal(
            client={
                "id": new_id("CL"),
                "name": body.client.name,
                "industry": body.client.industry,
                "size": body.client.size.value,
                "region": body.client.region.value,
            },
            deal={
                "id": new_id("DL"),
                "title": body.deal.title,
                "value": body.deal.value,
                "domain": domain,
                "expected_close_date": body.deal.expected_close_date,
            },
            owner_id=owner["id"] if owner else None,
            today=today,
        )

    ids = await _with_id_retry(create)
    assignment = await _assignment_for_new_deal(ids["deal_id"], domain, owner)
    client = await clients_repo.get_client(ids["client_id"])
    deal = await _require_deal(ids["deal_id"])
    return ClientCreateResult(
        client=ClientOut(**client), deal=DealOut(**deal), assignment=assignment
    )


# ---------------------------------------------------------------------------
# Deals
# ---------------------------------------------------------------------------
async def list_deals(
    *,
    status: DealStatus | None,
    stage: Stage | None,
    domain: str | None,
    owner_id: str | None,
    client_id: str | None,
    closing_month: str | None,
    limit: int,
    offset: int,
) -> Page[DealOut]:
    close_from, close_to = month_range(closing_month) if closing_month else (None, None)
    if domain is not None:
        domain = await domain_service.require_domain(domain)
    rows, total = await deals_repo.list_deals(
        status=status.value if status else None,
        stage=stage.value if stage else None,
        domain=domain,
        owner_id=owner_id,
        client_id=client_id,
        close_from=close_from,
        close_to=close_to,
        limit=limit,
        offset=offset,
    )
    return Page[DealOut](items=[DealOut(**r) for r in rows], total=total)


async def get_deal(deal_id: str) -> DealDetail:
    deal = await _require_deal(deal_id)
    activities = [ActivityOut(**r) for r in await activities_repo.list_for_deal(deal_id)]
    recommendations = await deals_repo.list_recommendations(deal_id)
    return DealDetail(**deal, activities=activities, recommendations=recommendations)


async def create_deal(body: DealCreate) -> DealCreateResult:
    """A new deal for an existing client."""
    if await clients_repo.get_client(body.client_id) is None:
        raise _not_found("CLIENT_NOT_FOUND", "Client", body.client_id)
    domain = await domain_service.require_domain(body.domain)
    owner = await _check_manual_owner(body.owner_id)
    today = clock.today()
    deal_id = ""

    async def create() -> bool:
        nonlocal deal_id
        deal_id = new_id("DL")
        return await deals_repo.create_deal_for_client(
            deal_id=deal_id,
            client_id=body.client_id,
            title=body.title,
            value=body.value,
            domain=domain,
            expected_close_date=body.expected_close_date,
            owner_id=owner["id"] if owner else None,
            today=today,
        )

    if not await _with_id_retry(create):  # client deleted in the meantime
        raise _not_found("CLIENT_NOT_FOUND", "Client", body.client_id)
    assignment = await _assignment_for_new_deal(deal_id, domain, owner)
    return DealCreateResult(deal=DealOut(**await _require_deal(deal_id)), assignment=assignment)


async def move_deal_stage(deal_id: str, action: StageAction) -> DealOut:
    deal = await _require_deal(deal_id)
    new_status, new_stage, date_field = next_state(deal["status"], deal["stage"], action)
    changes = {"status": new_status, "stage": new_stage, date_field: clock.today()}
    if not await deals_repo.move_stage(deal_id, deal["status"], deal["stage"], changes):
        raise AppError("CONFLICT", "Deal was changed by another request; reload and retry", 409)
    return DealOut(**await _require_deal(deal_id))


async def update_deal(deal_id: str, body: DealUpdate) -> DealOut:
    deal = await _require_deal(deal_id)
    if deal["status"] != DealStatus.OPEN:
        raise AppError(
            "DEAL_CLOSED", f"Deal is {deal['status']}; only OPEN deals can be edited", 400
        )
    changes = _plain(body.model_dump(exclude_unset=True))
    if changes and not await deals_repo.update_open_deal(deal_id, changes):
        raise AppError(
            "DEAL_CLOSED", "Deal was closed in the meantime; it can no longer be edited", 400
        )
    return DealOut(**await _require_deal(deal_id))


# ---------------------------------------------------------------------------
# Activities
# ---------------------------------------------------------------------------
async def create_activity(body: ActivityCreate) -> ActivityOut:
    deal = await _require_deal(body.deal_id)
    await _require_rep(body.sales_person_id)  # need not be the deal owner

    today = clock.today()
    activity_date = body.date or today
    latest = min(today, deal["closed_at"]) if deal["closed_at"] else today
    if not deal["created_at"] <= activity_date <= latest:
        raise AppError(
            "INVALID_ACTIVITY_DATE",
            f"Activity date must be between {deal['created_at']} and {latest}",
            400,
            {
                "date": activity_date.isoformat(),
                "earliest": deal["created_at"].isoformat(),
                "latest": latest.isoformat(),
            },
        )

    async def create() -> dict[str, Any] | None:
        return await activities_repo.create_activity(
            activity_id=new_id("AC"),
            deal_id=body.deal_id,
            sales_person_id=body.sales_person_id,
            activity_type=body.type.value,
            activity_date=activity_date,
            outcome=body.outcome.value,
        )

    row = await _with_id_retry(create)
    if row is None:  # deal or rep deleted in the meantime
        raise AppError("CONFLICT", "Deal or sales person no longer exists", 409)
    return ActivityOut(**row)


async def list_deal_activities(deal_id: str) -> list[ActivityOut]:
    await _require_deal(deal_id)
    return [ActivityOut(**r) for r in await activities_repo.list_for_deal(deal_id)]
