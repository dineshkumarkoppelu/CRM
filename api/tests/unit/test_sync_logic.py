"""Unit tests for the Postgres -> Neo4j sync helpers (no database, no network)."""

from __future__ import annotations

import asyncio
import json
from datetime import date

import pytest

from app.core.settings import Settings
from app.sync import events
from app.sync.service import (
    canonical_domain,
    normalize,
    parse_notification,
    select_changed,
)


def test_normalize_turns_iso_dates_into_dates_and_drops_inserted_at() -> None:
    raw = {
        "id": "DL-1",
        "title": "t",
        "value": 100,
        "status": "OPEN",
        "stage": "LEAD",
        "created_at": "2026-10-01",
        "qualified_at": None,
        "expected_close_date": "2026-11-20",
        "closed_at": None,
        "domain": "AI",
        "client_id": "CL-1",
        "owner_id": None,
        "inserted_at": "2026-10-29T11:10:55.930883+00:00",
    }
    row = normalize("deals", raw)
    assert row["created_at"] == date(2026, 10, 1)
    assert row["expected_close_date"] == date(2026, 11, 20)
    assert row["qualified_at"] is None and row["owner_id"] is None
    assert "inserted_at" not in row
    assert row["proposal_at"] is None  # absent columns become None


def test_normalize_activity_date_column() -> None:
    row = normalize(
        "activities",
        {"id": "AC-1", "type": "CALL", "date": "2026-10-02", "outcome": "NEUTRAL",
         "deal_id": "DL-1", "sales_person_id": "SP-1"},
    )  # fmt: skip
    assert row["date"] == date(2026, 10, 2)


def test_rows_differing_only_in_inserted_at_compare_equal() -> None:
    a = normalize(
        "clients", {"id": "C", "name": "n", "created_on": "2026-01-01", "inserted_at": "x"}
    )
    b = normalize(
        "clients", {"id": "C", "name": "n", "created_on": "2026-01-01", "inserted_at": "y"}
    )
    assert a == b


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ('{"table": "deals", "op": "UPDATE", "id": "DL-1"}', ("deals", "UPDATE", "DL-1")),
        (
            '{"table": "sales_people", "op": "DELETE", "id": "SP-9"}',
            ("sales_people", "DELETE", "SP-9"),
        ),
        ('{"table": "unknown", "op": "INSERT", "id": "X"}', None),
        ('{"table": "deals", "op": "INSERT"}', None),
        ('{"table": "deals", "op": "INSERT", "id": 5}', None),
        ("not json", None),
        ("[1, 2]", None),
    ],
)
def test_parse_notification(payload: str, expected: tuple[str, str, str] | None) -> None:
    assert parse_notification(payload) == expected


def test_select_changed_picks_new_changed_and_missing_rows() -> None:
    rows = [{"id": "1", "v": 1}, {"id": "2", "v": 2}, {"id": "3", "v": 3}, {"id": "4", "v": 4}]
    cache = {"1": {"id": "1", "v": 1}, "2": {"id": "2", "v": 99}, "3": {"id": "3", "v": 3}}
    present = {"1", "2"}  # 3 was applied once but is gone from Neo4j; 4 never was
    assert [r["id"] for r in select_changed(rows, cache, present)] == ["2", "3", "4"]


def test_select_changed_is_empty_when_nothing_differs() -> None:
    rows = [{"id": "1", "v": 1}]
    assert select_changed(rows, {"1": {"id": "1", "v": 1}}, {"1"}) == []


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("AI", "AI"),
        ("ai", "AI"),
        ("  cloud migration ", "Cloud Migration"),
        ("Quantum", None),
        ("", None),
        (None, None),
    ],
)
def test_canonical_domain(name: str | None, expected: str | None) -> None:
    assert canonical_domain(name, ["AI", "IoT", "Cloud Migration"]) == expected


def test_source_enabled_needs_url_and_key(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("SOURCE_API_URL", "SOURCE_API_KEY", "SOURCE_PG_DSN"):
        monkeypatch.delenv(name, raising=False)
    base = {"NEO4J_PASSWORD": "x" * 8, "_env_file": None}
    assert Settings(**base).source_enabled is False  # type: ignore[arg-type]
    assert Settings(SOURCE_API_URL="http://x", **base).source_enabled is False  # type: ignore[arg-type]
    assert Settings(SOURCE_API_URL="http://x", SOURCE_API_KEY="k", **base).source_enabled is True  # type: ignore[arg-type]
    # an empty value in .env means "not set"
    assert Settings(SOURCE_API_URL="", SOURCE_API_KEY="k", **base).source_enabled is False  # type: ignore[arg-type]


async def test_event_bus_fans_out_to_subscribers_and_cleans_up() -> None:
    first, second = events.stream(), events.stream()
    assert "hello" in await anext(first)
    assert "hello" in await anext(second)
    assert events.subscriber_count() == 2

    events.publish({"table": "deals", "op": "UPDATE", "id": "DL-1"})
    for stream in (first, second):
        frame = await asyncio.wait_for(anext(stream), timeout=2)
        assert frame.startswith("event: change\n")
        assert json.loads(frame.split("data: ", 1)[1]) == {
            "table": "deals",
            "op": "UPDATE",
            "id": "DL-1",
        }

    await first.aclose()
    await second.aclose()
    assert events.subscriber_count() == 0
