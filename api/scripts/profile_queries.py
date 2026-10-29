"""Phase 9 query review: PROFILE every read query used by an endpoint, time every endpoint.

1. Runs each repository read query with PROFILE against the seeded database and records the
   total db hits, the operators used and two warnings: NodeByLabelScan on :Deal and
   CartesianProduct.
2. Calls every endpoint over HTTP (2 warm-up calls, then N timed calls) and records the median
   and the maximum. Write endpoints are timed too; the script reseeds at the end so the data
   is back to the planted state.
3. Writes the results as Markdown (default: crm-graph-poc-kiro/docs/QUERY_PROFILE.md).

Run from api/ with the venv active and the API running (it uses the API's own "today"):
    python scripts/profile_queries.py --api http://localhost:8000
Point --neo4j-uri at the same database the API uses (default: NEO4J_URI from api/.env).
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx
from neo4j import AsyncGraphDatabase

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.clock import month_bounds, subtract_months  # noqa: E402
from app.core.settings import get_settings  # noqa: E402
from app.repositories import (  # noqa: E402
    activities_repo,
    analytics_repo,
    clients_repo,
    deals_repo,
    forecast_repo,
    gds_repo,
    graph_repo,
    recommendation_repo,
    salespeople_repo,
)
from app.services.analytics_service import quarter_bounds  # noqa: E402

DEFAULT_OUT = (
    Path(__file__).resolve().parents[2] / "crm-graph-poc-kiro" / "docs" / "QUERY_PROFILE.md"
)
LIMIT_MS = 500


@dataclass
class QueryResult:
    endpoint: str
    name: str
    db_hits: int
    rows: int
    operators: list[str]
    warnings: list[str] = field(default_factory=list)


def _walk(plan: dict[str, Any]) -> Iterable[dict[str, Any]]:
    yield plan
    for child in plan.get("children", []):
        yield from _walk(child)


def analyse(plan: dict[str, Any]) -> tuple[int, list[str], list[str]]:
    hits, operators, warnings = 0, [], []
    for node in _walk(plan):
        hits += int(node.get("dbHits", 0))
        op = str(node.get("operatorType", "?")).split("@")[0]
        details = str((node.get("args") or node.get("arguments") or {}).get("Details", ""))
        if op not in operators:
            operators.append(op)
        if op == "NodeByLabelScan" and ":Deal" in details:
            warnings.append(f"NodeByLabelScan {details}")
        if op == "CartesianProduct":
            warnings.append("CartesianProduct")
    return hits, operators, warnings


def read_queries(
    today: date, lookback: int, stalled_days: int, min_deals: int
) -> list[tuple[str, str, str, dict]]:
    """(endpoint, name, cypher, params) for every read query an endpoint runs."""
    ws = subtract_months(today, lookback)
    mf, ml = month_bounds(today)
    pf, pl = month_bounds(subtract_months(mf, 1))
    qf, ql = quarter_bounds(today)
    win = {"window_start": ws, "today": today}
    deal_filters = {"status": None, "stage": None, "domain": None, "owner_id": None, "client_id": None,
                    "close_from": None, "close_to": None}  # fmt: skip
    a, f = analytics_repo, forecast_repo
    return [
        ("GET /analytics/kpis", "KPIS", a.KPIS, {**win, "month_first": mf, "month_last": ml}),
        ("GET /analytics/kpis, /stalled", "STALLED", a.STALLED, {"today": today, "stalled_days": stalled_days}),
        ("GET /analytics/pipeline", "PIPELINE_ACTIVE_REPS", a.PIPELINE_ACTIVE_REPS, {}),
        ("GET /analytics/pipeline", "UNASSIGNED_OPEN", a.UNASSIGNED_OPEN, {}),
        ("GET /analytics/win-rates", "WIN_RATES_BY_REP", a.WIN_RATES_BY_REP, win),
        ("GET /analytics/win-rates", "WIN_RATES_BY_DOMAIN", a.WIN_RATES_BY_DOMAIN, win),
        ("GET /analytics/heatmap", "ALL_REPS", a.ALL_REPS, {}),
        ("GET /analytics/heatmap", "HEATMAP_CELLS", a.HEATMAP_CELLS, win),
        ("GET /analytics/cycle", "CYCLE_BY_REP", a.CYCLE_BY_REP, win),
        ("GET /analytics/cycle", "CYCLE_BY_DOMAIN", a.CYCLE_BY_DOMAIN, win),
        ("GET /analytics/funnel", "FUNNEL", a.FUNNEL, win),
        ("GET /analytics/leaderboard", "LEADERBOARD (month)", a.LEADERBOARD, {"period_first": mf, "period_last": ml}),
        ("GET /analytics/leaderboard", "LEADERBOARD (quarter)", a.LEADERBOARD, {"period_first": qf, "period_last": ql}),
        ("GET /analytics/domain-trend", "DOMAIN_TREND", a.DOMAIN_TREND,
         {"from_date": month_bounds(subtract_months(mf, 11))[0], "to_date": ml}),
        ("GET /analytics/forecast", "CLOSED_HISTORY", f.CLOSED_HISTORY,
         {"window_start": ws, "window_end_exclusive": today + timedelta(days=1)}),
        ("GET /analytics/forecast", "IN_SCOPE_OPEN", f.IN_SCOPE_OPEN, {"month_first": mf, "month_last": ml}),
        ("GET /analytics/forecast", "CONVERSIONS_BY_REP", f.CONVERSIONS_BY_REP, {"from_date": mf, "to_date": today}),
        ("GET /analytics/forecast", "CONVERSIONS_TEAM", f.CONVERSIONS_TEAM, {"from_date": mf, "to_date": today}),
        ("GET /analytics/forecast", "ACTIVE_REPS", f.ACTIVE_REPS, {}),
        ("GET /analytics/forecast/backtest", "BACKTEST_PIPELINE", f.BACKTEST_PIPELINE,
         {"asof": pf, "month_first": pf, "month_last": pl}),
        ("GET /analytics/similarity-compare", "RULE_PAIRS", gds_repo.RULE_PAIRS, {}),
        ("GET /salespeople", "LIST", salespeople_repo.LIST, {"active": None, "limit": 50, "offset": 0}),
        ("GET /salespeople", "COUNT", salespeople_repo.COUNT, {"active": None}),
        ("GET /salespeople/{id}", "GET_WITH_OPEN_COUNT", salespeople_repo.GET_WITH_OPEN_COUNT, {"id": "SP-002"}),
        ("GET /salespeople/{id}", "LIST_EXPERTISE", salespeople_repo.LIST_EXPERTISE, {"id": "SP-002"}),
        ("GET /salespeople/{id}", "LIST_SIMILAR_PEERS", salespeople_repo.LIST_SIMILAR_PEERS, {"id": "SP-002"}),
        ("GET /clients", "LIST (search)", clients_repo.LIST, {"q": "group", "limit": 50, "offset": 0}),
        ("GET /clients", "COUNT (search)", clients_repo.COUNT, {"q": "group"}),
        ("GET /clients/{id}", "GET", clients_repo.GET, {"id": "CL-0001"}),
        ("GET /clients/{id}", "LIST_FOR_CLIENT", deals_repo.LIST_FOR_CLIENT, {"client_id": "CL-0001"}),
        ("GET /deals", "LIST (no filter)", deals_repo.LIST, {**deal_filters, "limit": 50, "offset": 0}),
        ("GET /deals", "COUNT (no filter)", deals_repo.COUNT, deal_filters),
        ("GET /deals?status=OPEN&closing_month", "LIST (filtered)", deals_repo.LIST,
         {**deal_filters, "status": "OPEN", "close_from": mf, "close_to": ml, "limit": 50, "offset": 0}),
        ("GET /deals/{id}", "GET", deals_repo.GET, {"id": "DL-0001"}),
        ("GET /deals/{id}", "LIST_RECOMMENDATIONS", deals_repo.LIST_RECOMMENDATIONS, {"id": "DL-0001"}),
        ("GET /deals/{id}/activities", "LIST_FOR_DEAL", activities_repo.LIST_FOR_DEAL, {"deal_id": "DL-0001"}),
        ("POST /recommendations/* (ranking)", "REPS_STATE", recommendation_repo.REPS_STATE, {}),
        ("POST /recommendations/* (ranking)", "ALL_EXPERTISE", recommendation_repo.ALL_EXPERTISE, {}),
        ("POST /recommendations/* (ranking)", "ALL_SIMILAR", recommendation_repo.ALL_SIMILAR, {}),
        ("GET /graph/subgraph", "REP", graph_repo.REP, {"rep_id": "SP-002"}),
        ("GET /graph/subgraph", "DEALS", graph_repo.DEALS, {"rep_id": "SP-002", "status": None, "limit": 100}),
        ("GET /graph/subgraph", "EXPERTISE", graph_repo.EXPERTISE, {"rep_id": "SP-002"}),
        ("GET /graph/subgraph", "PEERS", graph_repo.PEERS, {"rep_id": "SP-002"}),
    ]  # fmt: skip


async def profile_all(uri: str, queries: list[tuple[str, str, str, dict]]) -> list[QueryResult]:
    settings = get_settings()
    results = []
    async with AsyncGraphDatabase.driver(
        uri, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
    ) as driver:
        async with driver.session(database="neo4j", default_access_mode="READ") as session:
            for endpoint, name, cypher, params in queries:
                result = await session.run("PROFILE " + cypher, params)
                rows = len([r async for r in result])
                summary = await result.consume()
                hits, operators, warnings = analyse(summary.profile or {})
                results.append(QueryResult(endpoint, name, hits, rows, operators, warnings))
    return results


# --------------------------------------------------------------------------- endpoint timing


def _time(
    http: httpx.Client, method: str, path: str, runs: int, body: Any = None, warmup: int = 2
) -> tuple[float, float]:
    for _ in range(warmup):
        http.request(method, path, json=body).raise_for_status()
    samples = []
    for _ in range(runs):
        start = time.perf_counter()
        http.request(method, path, json=body).raise_for_status()
        samples.append((time.perf_counter() - start) * 1000)
    return statistics.median(samples), max(samples)


def time_endpoints(
    api: str, runs: int
) -> tuple[list[tuple[str, float, float]], list[tuple[str, float, float]], date]:
    with httpx.Client(base_url=api, timeout=180) as http:
        today = date.fromisoformat(http.get("/api/health").json()["as_of_date"])
        month = f"{today.year:04d}-{today.month:02d}"
        open_deal = http.get(
            "/api/deals", params={"status": "OPEN", "owner_id": "SP-004", "limit": 1}
        ).json()["items"][0]["id"]

        reads = [
            "/api/health", "/api/meta/config", "/api/meta/domains",
            "/api/salespeople", "/api/salespeople/SP-002", "/api/clients?q=group", "/api/clients/CL-0001",
            "/api/deals", f"/api/deals?status=OPEN&closing_month={month}", "/api/deals/DL-0001",
            "/api/deals/DL-0001/activities",
            "/api/analytics/kpis", "/api/analytics/pipeline", "/api/analytics/win-rates",
            "/api/analytics/heatmap", "/api/analytics/cycle", "/api/analytics/stalled",
            "/api/analytics/funnel", "/api/analytics/leaderboard", "/api/analytics/domain-trend",
            "/api/analytics/forecast", "/api/analytics/forecast/backtest",
            "/api/analytics/similarity-compare",
            f"/api/recommendations/{open_deal}", "/api/graph/subgraph?sales_person_id=SP-002",
            "/",
        ]  # fmt: skip
        read_rows = [(f"GET {p}", *_time(http, "GET", p, runs)) for p in reads]
        read_rows.append(
            (
                "POST /api/recommendations/{id}/preview",
                *_time(http, "POST", f"/api/recommendations/{open_deal}/preview", runs),
            )
        )

        # Writes: each call creates or changes data (reseeded afterwards).
        new_client = {
            "client": {
                "name": "Profile Probe",
                "industry": "Retail",
                "size": "SMB",
                "region": "East",
            },
            "deal": {
                "title": "Probe",
                "value": 500000,
                "domain": "AI",
                "expected_close_date": f"{month}-28",
            },
        }
        writes = [
            (
                "POST /api/clients (create + assign)",
                *_time(http, "POST", "/api/clients", runs, new_client, warmup=1),
            )
        ]
        created = http.post("/api/clients", json=new_client).json()
        deal_id = created["deal"]["id"]
        writes.append(
            (
                "PATCH /api/deals/{id}",
                *_time(
                    http, "PATCH", f"/api/deals/{deal_id}", runs, {"title": "Probe deal"}, warmup=1
                ),
            )
        )
        activity = {
            "deal_id": deal_id,
            "sales_person_id": "SP-004",
            "type": "CALL",
            "outcome": "NEUTRAL",
        }
        writes.append(
            (
                "POST /api/activities",
                *_time(http, "POST", "/api/activities", runs, activity, warmup=1),
            )
        )
        targets = [c["sales_person_id"] for c in created["assignment"]["candidates"][1:3]]
        for target in targets:  # warm-up, like every other endpoint
            http.post(
                f"/api/recommendations/{deal_id}/override", json={"sales_person_id": target}
            ).raise_for_status()
        samples = []
        for i in range(runs):
            start = time.perf_counter()
            http.post(
                f"/api/recommendations/{deal_id}/override", json={"sales_person_id": targets[i % 2]}
            ).raise_for_status()
            samples.append((time.perf_counter() - start) * 1000)
        writes.append(
            ("POST /api/recommendations/{id}/override", statistics.median(samples), max(samples))
        )
        writes.append(
            (
                "PATCH /api/salespeople/{id}",
                *_time(http, "PATCH", "/api/salespeople/SP-015", runs, {"capacity": 8}, warmup=1),
            )
        )
        stage_samples = []
        for _ in range(3):
            start = time.perf_counter()
            http.post(f"/api/deals/{deal_id}/stage", json={"action": "ADVANCE"}).raise_for_status()
            stage_samples.append((time.perf_counter() - start) * 1000)
        writes.append(
            ("POST /api/deals/{id}/stage", statistics.median(stage_samples), max(stage_samples))
        )

        admin = []
        for path in ("/api/admin/recompute", "/api/admin/seed"):  # exempt from the 500 ms target
            start = time.perf_counter()
            http.post(path).raise_for_status()
            admin.append((f"POST {path}", (time.perf_counter() - start) * 1000))
    return read_rows, writes + [(name, ms, ms) for name, ms in admin], today


# --------------------------------------------------------------------------- report


EXEMPT = {
    "GET /api/analytics/similarity-compare",
    "POST /api/admin/recompute",
    "POST /api/admin/seed",
}


def render(
    queries: list[QueryResult], reads: list, writes: list, today: date, api: str, runs: int
) -> str:
    flagged = [q for q in queries if q.warnings]
    slow = [r for r in reads + writes if r[0] not in EXEMPT and r[2] >= LIMIT_MS]
    lines = [
        "# Query profile and endpoint timings",
        "",
        f"Generated by `api/scripts/profile_queries.py` against `{api}` with the seeded dataset "
        f"(as of {today.isoformat()}; 695 deals, 366 clients, ~2.9k activities). Neo4j 5.26 Community "
        "on a Windows laptop.",
        "",
        "## Summary",
        "",
        f"- Read queries profiled: {len(queries)}. Label scans on `:Deal` or cartesian products: "
        f"{len(flagged)}{' (see below)' if flagged else ''}.",
        f"- Endpoints over {LIMIT_MS} ms (max of {runs} warm calls, excluding admin/diagnostic): "
        f"{len(slow)}{': ' + ', '.join(r[0] for r in slow) if slow else ''}.",
        "- Exempt from the target: `POST /api/admin/seed`, `POST /api/admin/recompute` (bulk work, "
        "also exempt from the 15 s transaction timeout) and `GET /api/analytics/similarity-compare` "
        "(GDS projection; a diagnostic for tuning, not part of the demo flow).",
        "",
        "## Endpoint timings",
        "",
        f"Median and maximum of {runs} calls after 2 warm-up calls, measured over HTTP (includes "
        "JSON serialisation).",
        "",
        "| Endpoint | Median ms | Max ms | < 500 ms |",
        "|---|---:|---:|:---:|",
    ]
    for name, median, worst in reads + writes:
        ok = "exempt" if name in EXEMPT else ("yes" if worst < LIMIT_MS else "**no**")
        lines.append(f"| `{name}` | {median:.0f} | {worst:.0f} | {ok} |")
    lines += [
        "",
        "## PROFILE of every read query",
        "",
        "| Endpoint | Query | DB hits | Rows | Operators | Warnings |",
        "|---|---|---:|---:|---|---|",
    ]
    for q in queries:
        ops = ", ".join(op for op in q.operators if op != "ProduceResults")
        lines.append(
            f"| `{q.endpoint}` | `{q.name}` | {q.db_hits:,} | {q.rows} | {ops} | {'; '.join(q.warnings) or '-'} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--neo4j-uri", default=None, help="default: NEO4J_URI from api/.env")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    with httpx.Client(base_url=args.api, timeout=60) as http:
        cfg = http.get("/api/meta/config").json()
        http.post("/api/admin/seed", timeout=180).raise_for_status()  # start from the planted state
        today = date.fromisoformat(http.get("/api/health").json()["as_of_date"])

    queries = read_queries(
        today,
        cfg["analytics"]["lookback_months"],
        cfg["analytics"]["stalled_days"],
        cfg["expertise"]["min_deals_per_domain"],
    )
    profiled = asyncio.run(profile_all(args.neo4j_uri or get_settings().NEO4J_URI, queries))
    reads, writes, today = time_endpoints(args.api, args.runs)

    args.out.write_text(
        render(profiled, reads, writes, today, args.api, args.runs), encoding="utf-8"
    )
    flagged = [q for q in profiled if q.warnings]
    slow = [r for r in reads + writes if r[0] not in EXEMPT and r[2] >= LIMIT_MS]
    print(f"Wrote {args.out}")
    print(
        f"{len(profiled)} queries profiled, {len(flagged)} flagged; {len(slow)} endpoints >= {LIMIT_MS} ms"
    )
    for q in flagged:
        print(f"  FLAG {q.endpoint} {q.name}: {'; '.join(q.warnings)}")
    for name, median, worst in slow:
        print(f"  SLOW {name}: median {median:.0f} ms, max {worst:.0f} ms")
    return 0 if not flagged and not slow else 1


if __name__ == "__main__":
    sys.exit(main())
