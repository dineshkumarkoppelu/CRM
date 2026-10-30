"""An in-memory stand-in for the Postgres CRUD API (same row shapes, errors and semantics)."""

from __future__ import annotations

import copy
from datetime import date
from typing import Any

from app.core.errors import AppError
from app.seed.generator import SeedDataset

TABLES = ("sales_people", "clients", "deals", "activities")


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, date) else value


class FakeSource:
    """Rows as the real API returns them: ISO date strings plus `inserted_at`."""

    def __init__(self, dataset: SeedDataset) -> None:
        self.tables: dict[str, dict[str, dict[str, Any]]] = {t: {} for t in TABLES}
        for table in TABLES:
            for row in getattr(dataset, table):
                self.tables[table][row["id"]] = {
                    **{k: _iso(v) for k, v in row.items()},
                    "inserted_at": "2026-10-29T11:10:55+00:00",
                }
        self.calls: list[tuple[str, str, str]] = []

    # --- the source_client surface -------------------------------------------------------
    async def list_all(self, table: str) -> list[dict[str, Any]]:
        self.calls.append(("LIST", table, ""))
        return [copy.deepcopy(r) for _, r in sorted(self.tables[table].items())]

    async def get(self, table: str, row_id: str) -> dict[str, Any] | None:
        self.calls.append(("GET", table, row_id))
        row = self.tables[table].get(row_id)
        return copy.deepcopy(row) if row else None

    async def create(self, table: str, body: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("POST", table, body["id"]))
        if body["id"] in self.tables[table]:
            raise AppError("CONFLICT", f"{table}: id already exists", 409)
        if table == "deals" and body["client_id"] not in self.tables["clients"]:
            raise AppError("CONFLICT", "Foreign key violation", 409)
        row = {**body, "inserted_at": "2026-10-29T12:00:00+00:00"}
        self.tables[table][body["id"]] = row
        return copy.deepcopy(row)

    async def patch(self, table: str, row_id: str, body: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("PATCH", table, row_id))
        if row_id not in self.tables[table]:
            raise AppError("NOT_FOUND", f"{table} '{row_id}' not found", 404)
        self.tables[table][row_id].update(body)
        return copy.deepcopy(self.tables[table][row_id])

    async def delete(self, table: str, row_id: str) -> None:
        self.calls.append(("DELETE", table, row_id))
        if self.tables[table].pop(row_id, None) is None:
            raise AppError("NOT_FOUND", f"{table} '{row_id}' not found", 404)

    # --- helpers for tests -----------------------------------------------------------------
    def put(self, table: str, row: dict[str, Any]) -> None:
        """Change the source behind the app's back (as an external API client would)."""
        self.tables[table][row["id"]] = {**{k: _iso(v) for k, v in row.items()}}

    def remove(self, table: str, row_id: str) -> None:
        self.tables[table].pop(row_id, None)
