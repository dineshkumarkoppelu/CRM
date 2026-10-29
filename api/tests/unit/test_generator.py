"""Unit tests for the synthetic data generator (no database). AS_OF_DATE = 2026-10-06."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any

import pytest

from app.core.clock import month_bounds, subtract_months
from app.core.domains import DOMAINS
from app.seed import generator as gen
from app.seed.generator import SeedDataset, client_deal_counts, generate, split_by_percent
from app.seed.profiles import (
    EXPECTED_OLDER_CLOSED,
    EXPECTED_OPEN,
    EXPECTED_TOTAL_DEALS,
    EXPECTED_WINDOW_CLOSED,
    PROFILES,
    older_counts,
)

T = date(2026, 10, 6)
SEED = 42
LOOKBACK = 12
CAPACITY = 8
STALLED_DAYS = 21  # config.yaml analytics.stalled_days

WINDOW_START = subtract_months(T, LOOKBACK)  # exclusive
OLDER_START = subtract_months(T, LOOKBACK + 6)
OLDER_END = WINDOW_START - timedelta(days=7)
CUR_FIRST, CUR_LAST = month_bounds(T)
PREV_FIRST, PREV_LAST = month_bounds(subtract_months(CUR_FIRST, 1))
NEXT_FIRST, NEXT_LAST = month_bounds(CUR_LAST + timedelta(days=1))
EXCLUDED_FROM_STALLED = {"SP-001", "SP-002", "SP-005", "SP-006"}


def _generate(seed: int = SEED, today: date = T) -> SeedDataset:
    return generate(seed=seed, today=today, lookback_months=LOOKBACK, capacity=CAPACITY)


@pytest.fixture(scope="module")
def ds() -> SeedDataset:
    return _generate()


def in_window(d: dict[str, Any]) -> bool:
    return d["closed_at"] is not None and WINDOW_START < d["closed_at"] <= T


def is_older(d: dict[str, Any]) -> bool:
    return d["closed_at"] is not None and d["closed_at"] <= WINDOW_START


def open_deals(ds: SeedDataset) -> list[dict[str, Any]]:
    return [d for d in ds.deals if d["status"] == "OPEN"]


def last_activity(ds: SeedDataset) -> dict[str, date]:
    latest: dict[str, date] = {}
    for a in ds.activities:
        latest[a["deal_id"]] = max(latest.get(a["deal_id"], a["date"]), a["date"])
    return latest


# ---------------------------------------------------------------- determinism


def test_same_seed_and_date_give_identical_dataset(ds: SeedDataset) -> None:
    again = _generate()
    assert again == ds
    assert repr(again) == repr(ds)  # byte-identical representation


def test_different_seed_gives_different_details(ds: SeedDataset) -> None:
    other = _generate(seed=SEED + 1)
    assert [d["value"] for d in other.deals] != [d["value"] for d in ds.deals]
    assert len(other.deals) == len(ds.deals)


# ---------------------------------------------------------------- profile table


def test_totals(ds: SeedDataset) -> None:
    assert sum(in_window(d) for d in ds.deals) == EXPECTED_WINDOW_CLOSED == 430
    assert sum(is_older(d) for d in ds.deals) == EXPECTED_OLDER_CLOSED == 185
    assert len(open_deals(ds)) == EXPECTED_OPEN == 80
    assert len(ds.deals) == EXPECTED_TOTAL_DEALS == 695


def test_window_cells_match_profile_table_exactly(ds: SeedDataset) -> None:
    cells: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])  # won, closed
    for d in ds.deals:
        if in_window(d):
            cell = cells[(d["owner_id"], d["domain"])]
            cell[0] += d["status"] == "WON"
            cell[1] += 1
    for p in PROFILES:
        for domain in DOMAINS:
            expected = list(p.window.get(domain, (0, 0)))
            assert cells.get((p.id, domain), [0, 0]) == expected, (p.id, domain)


def test_older_history_matches_formulas_and_trap(ds: SeedDataset) -> None:
    cells: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for d in ds.deals:
        if is_older(d):
            assert OLDER_START <= d["closed_at"] <= OLDER_END
            cell = cells[(d["owner_id"], d["domain"])]
            cell[0] += d["status"] == "WON"
            cell[1] += 1
    expected: dict[tuple[str, str], list[int]] = {}
    for p in PROFILES:
        for domain, (won, closed) in p.window.items():
            expected[(p.id, domain)] = list(older_counts(won, closed))
        for domain, (won, closed) in p.extra_older.items():
            expected[(p.id, domain)] = [won, closed]
    assert dict(cells) == expected
    assert expected[("SP-003", "Cybersecurity")] == [4, 5]  # the window trap


@pytest.mark.parametrize(
    ("won", "closed", "expected"),
    [(7, 10, (3, 4)), (9, 10, (4, 4)), (3, 10, (1, 4)), (5, 10, (2, 4)),
     (2, 4, (1, 2)), (1, 4, (1, 2))],
)  # fmt: skip
def test_older_counts_half_up(won: int, closed: int, expected: tuple[int, int]) -> None:
    assert older_counts(won, closed) == expected


def test_older_counts_rejects_unknown_cell_size() -> None:
    with pytest.raises(ValueError):
        older_counts(3, 7)


def test_rohan_has_no_cybersecurity_in_window(ds: SeedDataset) -> None:
    rohan_cyber = [
        d for d in ds.deals if d["owner_id"] == "SP-003" and d["domain"] == "Cybersecurity"
    ]
    assert len(rohan_cyber) == 5
    assert not any(in_window(d) for d in rohan_cyber)
    assert sum(d["status"] == "WON" for d in rohan_cyber) == 4


def test_bhavna_has_no_iot_deals_ever(ds: SeedDataset) -> None:
    assert not [d for d in ds.deals if d["owner_id"] == "SP-002" and d["domain"] == "IoT"]


# ---------------------------------------------------------------- open deals


def test_open_deal_loads_per_rep(ds: SeedDataset) -> None:
    loads = Counter(d["owner_id"] for d in open_deals(ds))
    assert dict(loads) == {p.id: p.open_deals for p in PROFILES}
    assert loads["SP-001"] == 8 and loads["SP-002"] == 2 and loads["SP-005"] == 8


def test_open_deals_round_robin_over_window_domains(ds: SeedDataset) -> None:
    for p in PROFILES:
        domains = Counter(d["domain"] for d in open_deals(ds) if d["owner_id"] == p.id)
        expected = Counter(p.window_domains[i % len(p.window_domains)] for i in range(p.open_deals))
        assert domains == expected, p.id
    bhavna = sorted(d["domain"] for d in open_deals(ds) if d["owner_id"] == "SP-002")
    assert bhavna == ["AI", "DevOps"]


def test_open_expected_close_split_55_25(ds: SeedDataset) -> None:
    current = [d for d in open_deals(ds) if CUR_FIRST <= d["expected_close_date"] <= CUR_LAST]
    nxt = [d for d in open_deals(ds) if NEXT_FIRST <= d["expected_close_date"] <= NEXT_LAST]
    assert (len(current), len(nxt)) == (55, 25)


def test_open_stage_mix_and_dates(ds: SeedDataset) -> None:
    stages = Counter(d["stage"] for d in open_deals(ds))
    assert stages == {"LEAD": 16, "QUALIFIED": 20, "PROPOSAL": 24, "NEGOTIATION": 20}
    for d in open_deals(ds):
        assert 10 <= (T - d["created_at"]).days <= 120
        assert d["closed_at"] is None
        for f in gen.STAGE_DATE_FIELDS:
            assert d[f] is None or d[f] <= T


# ---------------------------------------------------------------- R2.3 constraints


def test_previous_month_has_30_closed_12_won_12_distinct_clients(ds: SeedDataset) -> None:
    prev = [d for d in ds.deals if in_window(d) and PREV_FIRST <= d["closed_at"] <= PREV_LAST]
    won = [d for d in prev if d["status"] == "WON"]
    assert len(prev) >= 30
    assert len(won) >= 12
    assert len({d["client_id"] for d in won}) >= 12
    # The forced ones were created at least 5 days before the previous month began.
    early = [d for d in prev if d["created_at"] <= PREV_FIRST - timedelta(days=5)]
    assert len(early) >= 30
    assert sum(d["status"] == "WON" for d in early) >= 12


def test_current_month_has_8_won_on_or_before_today(ds: SeedDataset) -> None:
    won = [d for d in ds.deals if d["status"] == "WON" and CUR_FIRST <= d["closed_at"] <= T]
    assert len(won) >= 8


def test_cycle_lengths(ds: SeedDataset) -> None:
    for d in ds.deals:
        if d["closed_at"] is None:
            continue
        cycle = (d["closed_at"] - d["created_at"]).days
        low, high = (30, 150) if d["status"] == "WON" else (15, 120)
        assert low <= cycle <= high, d["id"]


def test_stage_rules_and_strict_date_order(ds: SeedDataset) -> None:
    for d in ds.deals:
        reached = gen.STAGES.index(d["stage"])
        stage_dates = [d[f] for f in gen.STAGE_DATE_FIELDS]
        assert all(x is not None for x in stage_dates[:reached]), d["id"]
        assert all(x is None for x in stage_dates[reached:]), d["id"]
        chain = [d["created_at"], *stage_dates[:reached]]
        if d["closed_at"] is not None:
            chain.append(d["closed_at"])
        assert all(a < b for a, b in zip(chain, chain[1:], strict=False)), d["id"]
        if d["status"] == "WON":
            assert d["stage"] == "NEGOTIATION"


def test_lost_deals_use_all_stages(ds: SeedDataset) -> None:
    lost_stages = Counter(d["stage"] for d in ds.deals if d["status"] == "LOST")
    assert set(lost_stages) == set(gen.STAGES)


def test_expected_close_clamped_to_closing_month(ds: SeedDataset) -> None:
    for d in ds.deals:
        if d["closed_at"] is None:
            continue
        first, last = month_bounds(d["closed_at"])
        assert first <= d["expected_close_date"] <= last, d["id"]
        assert abs((d["expected_close_date"] - d["closed_at"]).days) <= 10, d["id"]


def test_values_by_client_size(ds: SeedDataset) -> None:
    sizes = {c["id"]: c["size"] for c in ds.clients}
    for d in ds.deals:
        low, high = gen.VALUE_RANGES_INR[sizes[d["client_id"]]]
        assert low <= d["value"] <= high and d["value"] % 10_000 == 0, d["id"]


def test_titles_use_domain_templates_and_client_name(ds: SeedDataset) -> None:
    names = {c["id"]: c["name"] for c in ds.clients}
    for domain, templates in gen.TITLE_TEMPLATES.items():
        assert len(templates) >= 6, domain
    for d in ds.deals:
        template, client_name = d["title"].split(" - ", 1)
        assert template in gen.TITLE_TEMPLATES[d["domain"]]
        assert client_name == names[d["client_id"]]


# ---------------------------------------------------------------- clients


def test_clients_count_distribution_and_dates(ds: SeedDataset) -> None:
    assert 320 <= len(ds.clients) <= 400
    per_client = Counter(d["client_id"] for d in ds.deals)
    assert set(per_client) == {c["id"] for c in ds.clients}  # every client has >= 1 deal
    distribution = Counter(per_client.values())
    n = len(ds.clients)
    for k, pct in {1: 40, 2: 35, 3: 20, 4: 5}.items():
        assert abs(distribution[k] / n * 100 - pct) < 1.5, (k, distribution)
    created_on = {c["id"]: c["created_on"] for c in ds.clients}
    first_deal: dict[str, date] = {}
    for d in ds.deals:
        first_deal[d["client_id"]] = min(
            first_deal.get(d["client_id"], d["created_at"]), d["created_at"]
        )
    for cid, first in first_deal.items():
        assert 0 <= (first - created_on[cid]).days <= 30


def test_client_attributes(ds: SeedDataset) -> None:
    assert len({c["name"] for c in ds.clients}) == len(ds.clients)  # unique names
    assert {c["industry"] for c in ds.clients} <= set(gen.INDUSTRIES)
    assert {c["region"] for c in ds.clients} <= set(gen.REGIONS)
    sizes = Counter(c["size"] for c in ds.clients)
    assert set(sizes) == {"SMB", "MID_MARKET", "ENTERPRISE"}
    assert sizes["SMB"] > sizes["MID_MARKET"] > sizes["ENTERPRISE"]


@pytest.mark.parametrize("total", [695, 694, 700, 100])
def test_client_deal_counts_sum_exactly(total: int) -> None:
    assert sum(client_deal_counts(total)) == total


def test_split_by_percent() -> None:
    assert split_by_percent(80, gen.OPEN_STAGE_PERCENT) == {
        "LEAD": 16, "QUALIFIED": 20, "PROPOSAL": 24, "NEGOTIATION": 20,
    }  # fmt: skip
    assert sum(split_by_percent(7, {"a": 50, "b": 50}).values()) == 7


# ---------------------------------------------------------------- activities


def test_exactly_6_stalled_open_deals_not_owned_by_demo_reps(ds: SeedDataset) -> None:
    latest = last_activity(ds)
    stalled = [d for d in open_deals(ds) if (T - latest[d["id"]]).days > STALLED_DAYS]
    assert len(stalled) == 6
    assert not {d["owner_id"] for d in stalled} & EXCLUDED_FROM_STALLED
    for d in stalled:
        assert 25 <= (T - latest[d["id"]]).days <= 60
    for d in open_deals(ds):
        if d not in stalled:
            assert (T - latest[d["id"]]).days <= 14


def test_activity_rules(ds: SeedDataset) -> None:
    deals = {d["id"]: d for d in ds.deals}
    per_deal = Counter(a["deal_id"] for a in ds.activities)
    for deal_id, deal in deals.items():
        low, high = (2, 6) if deal["closed_at"] is not None else (2, 8)
        assert low <= per_deal[deal_id] <= high, deal_id
    for a in ds.activities:
        deal = deals[a["deal_id"]]
        assert deal["created_at"] <= a["date"] <= (deal["closed_at"] or T)
        assert a["sales_person_id"] == deal["owner_id"]
        assert a["type"] in gen.ACTIVITY_TYPE_WEIGHTS
        assert a["outcome"] in gen.OUTCOME_WEIGHTS
    assert set(Counter(a["type"] for a in ds.activities)) == set(gen.ACTIVITY_TYPE_WEIGHTS)


# ---------------------------------------------------------------- reps and ids


def test_sales_people(ds: SeedDataset) -> None:
    assert [r["id"] for r in ds.sales_people] == [p.id for p in PROFILES]
    first_deal = {
        r["id"]: min(d["created_at"] for d in ds.deals if d["owner_id"] == r["id"])
        for r in ds.sales_people
    }
    for r in ds.sales_people:
        assert r["active"] is True and r["capacity"] == 8
        assert subtract_months(T, 60) <= r["joined_on"] <= subtract_months(T, 12)
        assert r["joined_on"] <= first_deal[r["id"]]
        first, last = r["name"].lower().split(" ", 1)
        assert r["email"] == f"{first}.{last}@democrm.local"


def test_ids_are_unique_and_zero_padded(ds: SeedDataset) -> None:
    for rows, prefix, width in [
        (ds.deals, "DL-", 4), (ds.clients, "CL-", 4), (ds.activities, "AC-", 5),
    ]:  # fmt: skip
        ids = [r["id"] for r in rows]
        assert len(ids) == len(set(ids))
        assert all(i.startswith(prefix) and len(i) == len(prefix) + width for i in ids)
    assert [d["created_at"] for d in ds.deals] == sorted(d["created_at"] for d in ds.deals)


# ---------------------------------------------------------------- other dates


@pytest.mark.parametrize("today", [date(2026, 11, 1), date(2026, 3, 31), date(2027, 1, 15)])
def test_constraints_hold_for_other_dates(today: date) -> None:
    other = _generate(today=today)
    cur_first, _ = month_bounds(today)
    prev_first, prev_last = month_bounds(subtract_months(cur_first, 1))
    won_now = [
        d for d in other.deals if d["status"] == "WON" and cur_first <= d["closed_at"] <= today
    ]
    prev_won = [
        d
        for d in other.deals
        if d["status"] == "WON" and d["closed_at"] and prev_first <= d["closed_at"] <= prev_last
    ]
    assert len(other.deals) == 695
    assert len(won_now) >= 8
    assert len({d["client_id"] for d in prev_won}) >= 12
