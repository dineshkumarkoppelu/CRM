"""Deterministic synthetic CRM dataset (phase-02). Builds rows in memory - NO database access.

Same `seed` + same `today` => identical dataset. Outcomes are never coin flips: for each
(rep, domain) cell exactly `closed` deals are created and exactly `won` of them are WON; the
seeded RNG only decides WHICH ones, plus names, dates, values, stages and activity details.
Every date is derived from `today` (T). Never uses the global `random` module.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from faker import Faker

from app.core.clock import month_bounds, subtract_months
from app.core.domains import DOMAINS
from app.seed.profiles import PROFILES, older_counts

# ---------------------------------------------------------------------------
# Dataset design (phase-02 spec). These shape the demo data; they are not business tunables.
# ---------------------------------------------------------------------------
STAGES: tuple[str, ...] = ("LEAD", "QUALIFIED", "PROPOSAL", "NEGOTIATION")
STAGE_DATE_FIELDS: tuple[str, ...] = ("qualified_at", "proposal_at", "negotiation_at")

OLDER_EXTRA_MONTHS = 6  # older history closes 12..18 months before T
OLDER_END_GAP_DAYS = 7  # ...and at least 7 days outside the window

PREV_MONTH_FORCED_WON = 15  # spec minimum: >= 12 WON (and >= 12 distinct clients)
PREV_MONTH_FORCED_LOST = 15  # spec minimum: >= 30 closed in the previous month
PREV_MONTH_CREATED_GAP_DAYS = 5  # forced deals are created >= 5 days before that month
CURRENT_MONTH_FORCED_WON = 8  # spec minimum: >= 8 WON this month, on or before T

WON_CYCLE_DAYS = (30, 150)
LOST_CYCLE_DAYS = (15, 120)
EXPECTED_CLOSE_JITTER_DAYS = 10
LOST_STAGE_WEIGHTS: dict[str, int] = {
    "LEAD": 25,
    "QUALIFIED": 30,
    "PROPOSAL": 30,
    "NEGOTIATION": 15,
}

OPEN_STAGE_PERCENT: dict[str, int] = {
    "LEAD": 20,
    "QUALIFIED": 25,
    "PROPOSAL": 30,
    "NEGOTIATION": 25,
}
OPEN_AGE_DAYS = (10, 120)
OPEN_EXPECTED_CLOSE_CURRENT_MONTH = 55  # the remaining open deals close next month

STALLED_COUNT = 6
STALLED_LAST_ACTIVITY_DAYS = (25, 60)
STALLED_EXCLUDED_REPS: tuple[str, ...] = ("SP-001", "SP-002", "SP-005", "SP-006")
RECENT_ACTIVITY_DAYS = 14
CLOSED_ACTIVITY_COUNT = (2, 6)
OPEN_ACTIVITY_COUNT = (2, 8)
ACTIVITY_TYPE_WEIGHTS: dict[str, int] = {"CALL": 40, "EMAIL": 30, "MEETING": 20, "DEMO": 10}
OUTCOME_WEIGHTS: dict[str, int] = {"POSITIVE": 40, "NEUTRAL": 40, "NEGATIVE": 20}

CLIENT_DEAL_COUNT_PERCENT: dict[int, int] = {1: 40, 2: 35, 3: 20, 4: 5}
CLIENT_CREATED_BEFORE_FIRST_DEAL_DAYS = (0, 30)
INDUSTRIES: tuple[str, ...] = (
    "BFSI", "Healthcare", "Retail", "Manufacturing", "Logistics", "EdTech", "Media", "Energy",
)  # fmt: skip
SIZE_WEIGHTS: dict[str, int] = {"SMB": 50, "MID_MARKET": 35, "ENTERPRISE": 15}
REGIONS: tuple[str, ...] = ("North", "South", "East", "West", "International")
VALUE_RANGES_INR: dict[str, tuple[int, int]] = {
    "SMB": (200_000, 800_000),  # 2-8 lakh
    "MID_MARKET": (800_000, 2_500_000),  # 8-25 lakh
    "ENTERPRISE": (2_500_000, 8_000_000),  # 25-80 lakh
}
VALUE_STEP_INR = 10_000

REP_JOINED_MONTHS_AGO = (12, 60)  # 1-5 years before T
REP_JOINED_BEFORE_FIRST_DEAL_DAYS = 30

TITLE_TEMPLATES: dict[str, tuple[str, ...]] = {
    "AI": (
        "Customer churn prediction", "Document intelligence pipeline", "Demand forecasting model",
        "Conversational support assistant", "Fraud detection engine", "Recommendation engine",
    ),
    "Cybersecurity": (
        "SOC monitoring service", "Zero-trust network rollout", "Vulnerability management program",
        "Identity and access overhaul", "Endpoint protection upgrade", "Security audit and VAPT",
    ),
    "IoT": (
        "Fleet telemetry platform", "Smart factory sensors", "Cold-chain monitoring",
        "Predictive maintenance sensors", "Smart energy metering", "Asset tracking network",
    ),
    "DevOps": (
        "CI/CD pipeline modernisation", "Kubernetes platform setup", "Observability stack",
        "Infrastructure as code rollout", "Release automation", "Site reliability engagement",
    ),
    "Cloud Migration": (
        "Data centre exit to cloud", "ERP lift and shift", "Hybrid cloud landing zone",
        "Database migration to managed service", "Legacy app re-platforming",
        "Cloud cost optimisation",
    ),
}  # fmt: skip


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SeedDataset:
    """Rows ready for the loader. Dates are `datetime.date` objects."""

    today: date
    seed: int
    sales_people: list[dict[str, Any]]
    clients: list[dict[str, Any]]
    deals: list[dict[str, Any]]
    activities: list[dict[str, Any]]


@dataclass
class _Deal:
    seq: int  # generation order, used as a stable tie-break
    owner_id: str
    domain: str
    status: str  # OPEN / WON / LOST
    kind: str  # "window" / "older" / "open"
    created_at: date = date.min
    closed_at: date | None = None
    stage: str = "LEAD"
    stage_dates: list[date] = field(default_factory=list)  # one per stage reached after LEAD
    expected_close_date: date = date.min
    forced_prev_month: bool = False
    client_idx: int = -1
    id: str = ""


@dataclass(frozen=True)
class _Window:
    """All date anchors derived from T."""

    today: date
    window_start: date  # exclusive: window is (window_start, today]
    older_start: date
    older_end: date
    current_first: date
    current_last: date
    prev_first: date
    prev_last: date
    next_first: date
    next_last: date

    @classmethod
    def build(cls, today: date, lookback_months: int) -> _Window:
        window_start = subtract_months(today, lookback_months)
        current_first, current_last = month_bounds(today)
        prev_first, prev_last = month_bounds(subtract_months(current_first, 1))
        next_first, next_last = month_bounds(current_last + timedelta(days=1))
        return cls(
            today=today,
            window_start=window_start,
            older_start=subtract_months(today, lookback_months + OLDER_EXTRA_MONTHS),
            older_end=window_start - timedelta(days=OLDER_END_GAP_DAYS),
            current_first=current_first,
            current_last=current_last,
            prev_first=prev_first,
            prev_last=prev_last,
            next_first=next_first,
            next_last=next_last,
        )

    def in_prev_month(self, d: date | None) -> bool:
        return d is not None and self.prev_first <= d <= self.prev_last


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------
def _rand_date(rng: random.Random, start: date, end: date) -> date:
    """Uniform random date in [start, end] (inclusive)."""
    if end < start:
        raise ValueError(f"empty date range {start}..{end}")
    return start + timedelta(days=rng.randint(0, (end - start).days))


def _weighted(rng: random.Random, weights: dict[str, int]) -> str:
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def split_by_percent(total: int, percent: dict[Any, int]) -> dict[Any, int]:
    """Integer split of `total` by percentages (largest remainder; ties keep dict order)."""
    exact = {key: total * pct / 100 for key, pct in percent.items()}
    counts = {key: int(value) for key, value in exact.items()}
    by_remainder = sorted(exact, key=lambda key: exact[key] - counts[key], reverse=True)
    for key in by_remainder[: total - sum(counts.values())]:
        counts[key] += 1
    return counts


def client_deal_counts(total_deals: int) -> list[int]:
    """Deals per client following CLIENT_DEAL_COUNT_PERCENT, summing exactly to total_deals."""
    mean = sum(k * pct for k, pct in CLIENT_DEAL_COUNT_PERCENT.items()) / 100
    clients = split_by_percent(round(total_deals / mean), CLIENT_DEAL_COUNT_PERCENT)
    diff = total_deals - sum(k * n for k, n in clients.items())
    while diff > 0:  # move clients from 1 deal to 2 deals
        clients[1] -= 1
        clients[2] += 1
        diff -= 1
    while diff < 0:  # move clients from 2 deals to 1 deal
        clients[2] -= 1
        clients[1] += 1
        diff += 1
    return [k for k, n in clients.items() for _ in range(n)]


def _stage_dates(rng: random.Random, start: date, span_days: int, reached: int) -> list[date]:
    """`reached` strictly increasing dates in (start, start + span_days]."""
    offsets = sorted(rng.sample(range(1, span_days + 1), reached))
    return [start + timedelta(days=o) for o in offsets]


# ---------------------------------------------------------------------------
# Generation steps
# ---------------------------------------------------------------------------
def _build_deal_skeletons(rng: random.Random) -> list[_Deal]:
    """Closed deals per cell (exact won/closed), older history, then open deals."""
    deals: list[_Deal] = []

    def add_closed_cell(owner: str, domain: str, won: int, closed: int, kind: str) -> None:
        statuses = ["WON"] * won + ["LOST"] * (closed - won)
        rng.shuffle(statuses)
        for status in statuses:
            deals.append(_Deal(len(deals), owner, domain, status, kind))

    for profile in PROFILES:
        for domain in profile.window_domains:
            won, closed = profile.window[domain]
            add_closed_cell(profile.id, domain, won, closed, "window")
            won_old, closed_old = older_counts(won, closed)
            add_closed_cell(profile.id, domain, won_old, closed_old, "older")
        for domain in DOMAINS:  # extra older history (the window trap), fixed order
            if domain in profile.extra_older:
                won, closed = profile.extra_older[domain]
                add_closed_cell(profile.id, domain, won, closed, "older")

    for profile in PROFILES:  # open deals: round-robin over the rep's window domains
        domains = profile.window_domains
        for i in range(profile.open_deals):
            deals.append(_Deal(len(deals), profile.id, domains[i % len(domains)], "OPEN", "open"))
    return deals


def _assign_closed_dates(rng: random.Random, deals: list[_Deal], w: _Window) -> None:
    window = [d for d in deals if d.kind == "window"]
    won = [d for d in window if d.status == "WON"]
    lost = [d for d in window if d.status == "LOST"]
    rng.shuffle(won)
    rng.shuffle(lost)

    current_forced = won[:CURRENT_MONTH_FORCED_WON]
    prev_forced = (
        won[CURRENT_MONTH_FORCED_WON : CURRENT_MONTH_FORCED_WON + PREV_MONTH_FORCED_WON]
        + lost[:PREV_MONTH_FORCED_LOST]
    )
    forced_ids = {d.seq for d in current_forced + prev_forced}

    for d in current_forced:
        d.closed_at = _rand_date(rng, w.current_first, w.today)
    for d in prev_forced:
        d.closed_at = _rand_date(rng, w.prev_first, w.prev_last)
        d.forced_prev_month = True
    for d in window:
        if d.seq not in forced_ids:
            d.closed_at = _rand_date(rng, w.window_start + timedelta(days=1), w.today)
    for d in deals:
        if d.kind == "older":
            d.closed_at = _rand_date(rng, w.older_start, w.older_end)

    for d in deals:  # cycle, stages and expected close for every closed deal (seq order)
        if d.closed_at is None:
            continue
        low, high = WON_CYCLE_DAYS if d.status == "WON" else LOST_CYCLE_DAYS
        if d.forced_prev_month:
            low = max(low, (d.closed_at - w.prev_first).days + PREV_MONTH_CREATED_GAP_DAYS)
        cycle = rng.randint(low, high)
        d.created_at = d.closed_at - timedelta(days=cycle)
        d.stage = "NEGOTIATION" if d.status == "WON" else _weighted(rng, LOST_STAGE_WEIGHTS)
        # Strictly between created_at and closed_at.
        d.stage_dates = _stage_dates(rng, d.created_at, cycle - 1, STAGES.index(d.stage))
        month_first, month_last = month_bounds(d.closed_at)
        jitter = rng.randint(-EXPECTED_CLOSE_JITTER_DAYS, EXPECTED_CLOSE_JITTER_DAYS)
        expected = d.closed_at + timedelta(days=jitter)
        d.expected_close_date = min(max(expected, month_first), month_last)


def _assign_open_dates(rng: random.Random, deals: list[_Deal], w: _Window) -> None:
    open_deals = [d for d in deals if d.kind == "open"]
    stage_counts = split_by_percent(len(open_deals), OPEN_STAGE_PERCENT)
    stages = [stage for stage, n in stage_counts.items() for _ in range(n)]
    rng.shuffle(stages)
    months = ["current"] * OPEN_EXPECTED_CLOSE_CURRENT_MONTH
    months += ["next"] * (len(open_deals) - OPEN_EXPECTED_CLOSE_CURRENT_MONTH)
    rng.shuffle(months)

    for d, stage, month in zip(open_deals, stages, months, strict=True):
        age = rng.randint(*OPEN_AGE_DAYS)
        d.created_at = w.today - timedelta(days=age)
        d.stage = stage
        d.stage_dates = _stage_dates(rng, d.created_at, age, STAGES.index(stage))  # all <= T
        if month == "current":  # any day of this month, but not before the deal existed
            start = max(w.current_first, d.created_at + timedelta(days=1))
            d.expected_close_date = _rand_date(rng, start, w.current_last)
        else:
            d.expected_close_date = _rand_date(rng, w.next_first, w.next_last)


def _assign_clients(rng: random.Random, deals: Sequence[_Deal], w: _Window) -> int:
    """Spread deals (in chronological order) over clients. Returns the number of clients."""
    counts = client_deal_counts(len(deals))
    slots = [client for client, k in enumerate(counts) for _ in range(k)]
    rng.shuffle(slots)
    for d, client in zip(deals, slots, strict=True):
        d.client_idx = client

    # Every client that converted in the previous month must be distinct (so the back-test
    # sees >= 12 distinct converted clients). Swap clients with a deal outside that set.
    def prev_won(d: _Deal) -> bool:
        return d.status == "WON" and w.in_prev_month(d.closed_at)

    seen: set[int] = set()
    for d in deals:
        if not prev_won(d):
            continue
        if d.client_idx in seen:
            taken = {x.client_idx for x in deals if prev_won(x)}
            partner = next(x for x in deals if not prev_won(x) and x.client_idx not in taken)
            d.client_idx, partner.client_idx = partner.client_idx, d.client_idx
        seen.add(d.client_idx)
    return len(counts)


def _unique_company_names(fake: Faker, n: int) -> list[str]:
    names: list[str] = []
    used: set[str] = set()
    while len(names) < n:
        name = fake.company()
        if name not in used:
            used.add(name)
            names.append(name)
    return names


def _build_clients(
    rng: random.Random, fake: Faker, deals: Sequence[_Deal], n_clients: int
) -> list[dict[str, Any]]:
    """Clients numbered in order of their first deal; created_on before their first deal."""
    order: list[int] = []
    first_created: dict[int, date] = {}
    for d in deals:  # deals are in chronological order
        if d.client_idx not in first_created:
            first_created[d.client_idx] = d.created_at
            order.append(d.client_idx)
    assert len(order) == n_clients

    names = _unique_company_names(fake, n_clients)
    clients: list[dict[str, Any]] = [{} for _ in range(n_clients)]
    for number, (idx, name) in enumerate(zip(order, names, strict=True), start=1):
        before = rng.randint(*CLIENT_CREATED_BEFORE_FIRST_DEAL_DAYS)
        clients[idx] = {
            "id": f"CL-{number:04d}",
            "name": name,
            "industry": rng.choice(INDUSTRIES),
            "size": _weighted(rng, SIZE_WEIGHTS),
            "region": rng.choice(REGIONS),
            "created_on": first_created[idx] - timedelta(days=before),
        }
    return clients


def _deal_rows(
    rng: random.Random, deals: Sequence[_Deal], clients: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for d in deals:
        client = clients[d.client_idx]
        low, high = VALUE_RANGES_INR[client["size"]]
        value = rng.randint(low // VALUE_STEP_INR, high // VALUE_STEP_INR) * VALUE_STEP_INR
        template = rng.choice(TITLE_TEMPLATES[d.domain])
        stage_dates = d.stage_dates + [None] * (len(STAGE_DATE_FIELDS) - len(d.stage_dates))
        rows.append(
            {
                "id": d.id,
                "title": f"{template} - {client['name']}",
                "value": value,
                "status": d.status,
                "stage": d.stage,
                "created_at": d.created_at,
                **dict(zip(STAGE_DATE_FIELDS, stage_dates, strict=True)),
                "expected_close_date": d.expected_close_date,
                "closed_at": d.closed_at,
                "domain": d.domain,
                "client_id": client["id"],
                "owner_id": d.owner_id,
            }
        )
    return rows


def _activity_rows(rng: random.Random, deals: Sequence[_Deal], w: _Window) -> list[dict[str, Any]]:
    open_deals = [d for d in deals if d.status == "OPEN"]
    candidates = [
        d
        for d in open_deals
        if d.owner_id not in STALLED_EXCLUDED_REPS
        and (w.today - d.created_at).days >= STALLED_LAST_ACTIVITY_DAYS[0]
    ]
    stalled = {d.seq for d in rng.sample(candidates, STALLED_COUNT)}

    rows: list[dict[str, Any]] = []
    for d in deals:
        if d.closed_at is not None:
            n = rng.randint(*CLOSED_ACTIVITY_COUNT)
            dates = [_rand_date(rng, d.created_at, d.closed_at) for _ in range(n)]
        else:
            n = rng.randint(*OPEN_ACTIVITY_COUNT)
            if d.seq in stalled:
                newest, oldest = STALLED_LAST_ACTIVITY_DAYS
                latest = _rand_date(
                    rng,
                    max(d.created_at, w.today - timedelta(days=oldest)),
                    w.today - timedelta(days=newest),
                )
            else:
                start = max(d.created_at, w.today - timedelta(days=RECENT_ACTIVITY_DAYS))
                latest = _rand_date(rng, start, w.today)
            dates = [latest] + [_rand_date(rng, d.created_at, latest) for _ in range(n - 1)]
        for activity_date in sorted(dates):
            rows.append(
                {
                    "id": f"AC-{len(rows) + 1:05d}",
                    "type": _weighted(rng, ACTIVITY_TYPE_WEIGHTS),
                    "date": activity_date,
                    "outcome": _weighted(rng, OUTCOME_WEIGHTS),
                    "deal_id": d.id,
                    "sales_person_id": d.owner_id,
                }
            )
    return rows


def _sales_person_rows(
    rng: random.Random, deals: Sequence[_Deal], w: _Window, capacity: int
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    latest_join, earliest_join = (subtract_months(w.today, m) for m in REP_JOINED_MONTHS_AGO)
    for profile in PROFILES:
        first_deal = min(d.created_at for d in deals if d.owner_id == profile.id)
        upper = min(latest_join, first_deal - timedelta(days=REP_JOINED_BEFORE_FIRST_DEAL_DAYS))
        rows.append(
            {
                "id": profile.id,
                "name": profile.name,
                "email": profile.email,
                "region": profile.region,
                "joined_on": _rand_date(rng, earliest_join, max(upper, earliest_join)),
                "active": True,
                "capacity": capacity,
            }
        )
    return rows


def generate(*, seed: int, today: date, lookback_months: int, capacity: int) -> SeedDataset:
    """Build the whole dataset in memory. Pure: same inputs => identical output."""
    rng = random.Random(seed)
    fake = Faker("en_IN")
    fake.seed_instance(seed)
    w = _Window.build(today, lookback_months)

    deals = _build_deal_skeletons(rng)
    _assign_closed_dates(rng, deals, w)
    _assign_open_dates(rng, deals, w)

    deals.sort(key=lambda d: (d.created_at, d.seq))  # chronological order
    for number, d in enumerate(deals, start=1):
        d.id = f"DL-{number:04d}"

    n_clients = _assign_clients(rng, deals, w)
    clients = _build_clients(rng, fake, deals, n_clients)
    deal_rows = _deal_rows(rng, deals, clients)
    activities = _activity_rows(rng, deals, w)
    sales_people = _sales_person_rows(rng, deals, w, capacity)

    return SeedDataset(
        today=today,
        seed=seed,
        sales_people=sales_people,
        clients=sorted(clients, key=lambda c: c["id"]),
        deals=deal_rows,
        activities=activities,
    )
