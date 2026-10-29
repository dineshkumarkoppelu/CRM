"""Independent pandas cross-check of the Phase 4 analytics API.

Exports Deal / Client / Activity / SalesPerson rows from Neo4j with ONE flat Cypher read per
label, recomputes the metrics with pandas (no app business code is used), calls the running
API and prints PASS/FAIL per metric. Exit code 0 only if everything matches.

"Today" and the tunables are taken from the API itself (/api/health, /api/meta/config), so the
script checks the API against the same inputs it used.

Run from api/ with the venv active:
    python scripts/crosscheck_kpis.py --api http://localhost:8000
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
from neo4j import AsyncGraphDatabase

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # so `app` is importable
from app.core.settings import get_settings  # noqa: E402  (connection settings only)

DOMAINS = ["AI", "Cybersecurity", "IoT", "DevOps", "Cloud Migration"]

# One simple, flat read per label.
EXPORTS = {
    "deals": """
        MATCH (d:Deal)
        OPTIONAL MATCH (d)-[:IN_DOMAIN]->(dom:Domain)
        OPTIONAL MATCH (d)-[:FOR_CLIENT]->(c:Client)
        OPTIONAL MATCH (s:SalesPerson)-[:OWNS]->(d)
        RETURN d.id AS id, d.status AS status, d.stage AS stage, d.value AS value,
               d.created_at AS created_at, d.closed_at AS closed_at,
               dom.name AS domain, c.id AS client_id, s.id AS owner_id
    """,
    "clients": "MATCH (c:Client) RETURN c.id AS id, c.name AS name",
    "activities": """
        MATCH (a:Activity)-[:ON_DEAL]->(d:Deal)
        RETURN a.id AS id, a.date AS date, d.id AS deal_id
    """,
    "reps": """
        MATCH (s:SalesPerson)
        RETURN s.id AS id, s.name AS name, s.active AS active, s.capacity AS capacity
    """,
}


# --------------------------------------------------------------------------- helpers
def half_up(value: float, ndigits: int) -> float:
    # float() first: repr() of a numpy float is "np.float64(...)", which Decimal can't parse.
    return float(Decimal(repr(float(value))).quantize(Decimal(1).scaleb(-ndigits), ROUND_HALF_UP))


def rate(won: int, handled: int) -> float | None:
    return None if handled == 0 else half_up(won / handled, 4)


def subtract_months(d: date, months: int) -> date:
    total = d.year * 12 + d.month - 1 - months
    year, month0 = divmod(total, 12)
    last_day = pd.Timestamp(year=year, month=month0 + 1, day=1).days_in_month
    return date(year, month0 + 1, min(d.day, last_day))


def month_bounds(d: date) -> tuple[date, date]:
    ts = pd.Timestamp(d)
    return date(d.year, d.month, 1), date(d.year, d.month, ts.days_in_month)


def to_date(series: pd.Series) -> pd.Series:
    return series.map(lambda v: v.to_native() if v is not None and hasattr(v, "to_native") else v)


async def export_frames() -> dict[str, pd.DataFrame]:
    settings = get_settings()
    auth = (settings.NEO4J_USER, settings.NEO4J_PASSWORD)
    frames: dict[str, pd.DataFrame] = {}
    async with AsyncGraphDatabase.driver(settings.NEO4J_URI, auth=auth) as driver:
        for name, query in EXPORTS.items():
            records, _, _ = await driver.execute_query(query)
            frames[name] = pd.DataFrame([r.data() for r in records])
    for column in ("created_at", "closed_at"):
        frames["deals"][column] = to_date(frames["deals"][column])
    frames["activities"]["date"] = to_date(frames["activities"]["date"])
    return frames


# --------------------------------------------------------------------------- recompute
def expected_metrics(f: dict[str, pd.DataFrame], today: date, cfg: dict) -> dict[str, Any]:
    deals, activities, reps = f["deals"], f["activities"], f["reps"]
    window_start = subtract_months(today, cfg["analytics"]["lookback_months"])
    month_first, month_last = month_bounds(today)

    closed = deals[deals["status"].isin(["WON", "LOST"])]
    in_window = closed[(closed["closed_at"] > window_start) & (closed["closed_at"] <= today)]
    won_window = in_window[in_window["status"] == "WON"]
    open_deals = deals[deals["status"] == "OPEN"]
    won = deals[deals["status"] == "WON"]
    won_month = won[(won["closed_at"] >= month_first) & (won["closed_at"] <= month_last)]

    # stalled
    last_activity = activities.groupby("deal_id")["date"].max()
    ref = open_deals["id"].map(last_activity).fillna(open_deals["created_at"])
    days_since = ref.map(lambda d: (today - d).days)
    stalled_ids = sorted(open_deals.loc[days_since > cfg["analytics"]["stalled_days"], "id"])

    cycle_days = won_window.apply(lambda r: (r["closed_at"] - r["created_at"]).days, axis=1)
    kpis = {
        "open_deals": len(open_deals),
        "open_value": int(open_deals["value"].sum()),
        "won_this_month": len(won_month),
        "clients_converted_this_month": won_month["client_id"].nunique(),
        "win_rate_window": rate(len(won_window), len(in_window)),
        "avg_cycle_days": half_up(cycle_days.mean(), 1) if len(won_window) else None,
        "avg_won_value": int(half_up(won_window["value"].mean(), 0)) if len(won_window) else None,
        "stalled_count": len(stalled_ids),
    }

    # win rates by rep (all reps, window)
    by_rep = []
    for rep in reps.sort_values("id").itertuples():
        mine = in_window[in_window["owner_id"] == rep.id]
        n_won = int((mine["status"] == "WON").sum())
        by_rep.append(
            {
                "sales_person_id": rep.id,
                "name": rep.name,
                "handled": len(mine),
                "won": n_won,
                "win_rate": rate(n_won, len(mine)),
            }
        )

    # heatmap (reps x domains, owned closed deals in window)
    min_deals = cfg["expertise"]["min_deals_per_domain"]
    cells = []
    for rep_id in sorted(reps["id"]):
        for domain in DOMAINS:
            cell = in_window[(in_window["owner_id"] == rep_id) & (in_window["domain"] == domain)]
            n_won = int((cell["status"] == "WON").sum())
            cells.append(
                {
                    "sales_person_id": rep_id,
                    "domain": domain,
                    "handled": len(cell),
                    "won": n_won,
                    "win_rate": rate(n_won, len(cell)),
                    "qualifies": len(cell) >= min_deals,
                }
            )

    # leaderboard (month)
    board = []
    for rep in reps.itertuples():
        mine = won_month[won_month["owner_id"] == rep.id]
        board.append(
            {
                "sales_person_id": rep.id,
                "name": rep.name,
                "clients_converted": mine["client_id"].nunique(),
                "won_value": int(mine["value"].sum()),
            }
        )
    board.sort(key=lambda r: (-r["clients_converted"], -r["won_value"], r["sales_person_id"]))

    return {
        "kpis": kpis,
        "win_rates.by_rep": by_rep,
        "heatmap.cells": cells,
        "stalled": stalled_ids,
        "leaderboard.month": board,
    }


def actual_metrics(api: str) -> tuple[dict[str, Any], date, dict]:
    with httpx.Client(base_url=api, timeout=60) as http:
        today = date.fromisoformat(http.get("/api/health").json()["as_of_date"])
        cfg = http.get("/api/meta/config").json()
        get = lambda path: http.get(f"/api/analytics/{path}").raise_for_status().json()  # noqa: E731
        actual = {
            "kpis": get("kpis"),
            "win_rates.by_rep": get("win-rates")["by_rep"],
            "heatmap.cells": get("heatmap")["cells"],
            "stalled": sorted(row["deal_id"] for row in get("stalled")),
            "leaderboard.month": get("leaderboard")["month"],
        }
    return actual, today, cfg


def diff(expected: Any, actual: Any, path: str = "") -> list[str]:
    """Readable list of differences (floats compared with a 1e-9 tolerance)."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        out: list[str] = []
        for key in sorted(set(expected) | set(actual)):
            out += diff(expected.get(key), actual.get(key), f"{path}.{key}")
        return out
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return [f"{path}: length expected {len(expected)}, got {len(actual)}"]
        out = []
        for i, (e, a) in enumerate(zip(expected, actual, strict=True)):
            out += diff(e, a, f"{path}[{i}]")
        return out
    if isinstance(expected, float) and isinstance(actual, (int, float)):
        return (
            [] if abs(expected - actual) <= 1e-9 else [f"{path}: expected {expected}, got {actual}"]
        )
    return [] if expected == actual else [f"{path}: expected {expected!r}, got {actual!r}"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://localhost:8000", help="API base URL")
    args = parser.parse_args()

    actual, today, cfg = actual_metrics(args.api)
    frames = asyncio.run(export_frames())
    expected = expected_metrics(frames, today, cfg)

    print(f"Cross-check against {args.api} (as of {today}, {len(frames['deals'])} deals)")
    failures = 0
    for metric, value in expected.items():
        problems = diff(value, actual[metric], metric)
        status = "PASS" if not problems else "FAIL"
        failures += bool(problems)
        print(f"  {status}  {metric}")
        for line in problems[:10]:
            print(f"        {line}")
        if len(problems) > 10:
            print(f"        ... {len(problems) - 10} more differences")
    print("ALL PASS" if failures == 0 else f"{failures} metric(s) FAILED")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
