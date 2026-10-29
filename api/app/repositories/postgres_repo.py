"""Postgres storage for the raw CRM rows (sales people, clients, deals, activities).

Rows go in and come out as the same dicts the seed generator produces, so the Neo4j loaders in
`seed_repo` work unchanged. `inserted_at` is set by the database and is not part of those dicts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.pg import get_pool
from app.seed.generator import SeedDataset

# Insert order matters: deals reference clients and sales people, activities reference deals.
SALES_PEOPLE_COLUMNS = ("id", "name", "email", "region", "joined_on", "active", "capacity")
CLIENTS_COLUMNS = ("id", "name", "industry", "size", "region", "created_on")
DEALS_COLUMNS = (
    "id", "title", "value", "status", "stage", "created_at", "qualified_at", "proposal_at",
    "negotiation_at", "expected_close_date", "closed_at", "domain", "client_id", "owner_id",
)  # fmt: skip
ACTIVITIES_COLUMNS = ("id", "type", "date", "outcome", "deal_id", "sales_person_id")

TABLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sales_people", SALES_PEOPLE_COLUMNS),
    ("clients", CLIENTS_COLUMNS),
    ("deals", DEALS_COLUMNS),
    ("activities", ACTIVITIES_COLUMNS),
)

CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS sales_people (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT NOT NULL,
    region      TEXT NOT NULL,
    joined_on   DATE NOT NULL,
    active      BOOLEAN NOT NULL,
    capacity    INTEGER NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS clients (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    industry    TEXT NOT NULL,
    size        TEXT NOT NULL,
    region      TEXT NOT NULL,
    created_on  DATE NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS deals (
    id                  TEXT PRIMARY KEY,
    title               TEXT NOT NULL,
    value               BIGINT NOT NULL,
    status              TEXT NOT NULL,
    stage               TEXT NOT NULL,
    created_at          DATE NOT NULL,
    qualified_at        DATE,
    proposal_at         DATE,
    negotiation_at      DATE,
    expected_close_date DATE NOT NULL,
    closed_at           DATE,
    domain              TEXT NOT NULL,
    client_id           TEXT NOT NULL REFERENCES clients (id),
    owner_id            TEXT,
    inserted_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS activities (
    id              TEXT PRIMARY KEY,
    type            TEXT NOT NULL,
    date            DATE NOT NULL,
    outcome         TEXT NOT NULL,
    deal_id         TEXT NOT NULL,
    sales_person_id TEXT NOT NULL,
    inserted_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Tables created by an earlier version had a required, enforced owner. A deal made in the UI
-- has no owner until the assignment runs, and its owner may be a rep that exists only in Neo4j.
ALTER TABLE deals ALTER COLUMN owner_id DROP NOT NULL;
ALTER TABLE deals DROP CONSTRAINT IF EXISTS deals_owner_id_fkey;
-- Same for activities: the deal or rep may have been created in the UI and exist only in Neo4j.
ALTER TABLE activities DROP CONSTRAINT IF EXISTS activities_deal_id_fkey;
ALTER TABLE activities DROP CONSTRAINT IF EXISTS activities_sales_person_id_fkey;

-- Tell the app about every change NOT made by the app itself (psql, another tool, a script) so
-- it can push it to Neo4j at once. Changes made by the app (application_name 'crm-app') are
-- skipped: the app writes those to Neo4j itself. The payload is only {table, op, id}.
CREATE OR REPLACE FUNCTION crm_notify_change() RETURNS trigger AS $$
DECLARE
    changed RECORD;
BEGIN
    IF current_setting('application_name', true) = 'crm-app' THEN
        RETURN NULL;
    END IF;
    IF TG_OP = 'DELETE' THEN changed := OLD; ELSE changed := NEW; END IF;
    PERFORM pg_notify(
        'crm_changes',
        json_build_object('table', TG_TABLE_NAME, 'op', TG_OP, 'id', changed.id)::text
    );
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER crm_sales_people_notify
    AFTER INSERT OR UPDATE OR DELETE ON sales_people
    FOR EACH ROW EXECUTE FUNCTION crm_notify_change();
CREATE OR REPLACE TRIGGER crm_clients_notify
    AFTER INSERT OR UPDATE OR DELETE ON clients
    FOR EACH ROW EXECUTE FUNCTION crm_notify_change();
CREATE OR REPLACE TRIGGER crm_deals_notify
    AFTER INSERT OR UPDATE OR DELETE ON deals
    FOR EACH ROW EXECUTE FUNCTION crm_notify_change();
CREATE OR REPLACE TRIGGER crm_activities_notify
    AFTER INSERT OR UPDATE OR DELETE ON activities
    FOR EACH ROW EXECUTE FUNCTION crm_notify_change();
"""

CHANNEL = "crm_changes"
COLUMNS_BY_TABLE = dict(TABLES)


@dataclass(frozen=True)
class StoredDataset:
    """All rows currently in Postgres, shaped like the generator's output."""

    sales_people: list[dict[str, Any]]
    clients: list[dict[str, Any]]
    deals: list[dict[str, Any]]
    activities: list[dict[str, Any]]


async def ensure_tables() -> None:
    """Create the four tables if they are missing (safe to run on every start)."""
    pool = await get_pool()
    await pool.execute(CREATE_TABLES)


async def is_empty() -> bool:
    """True when none of the four tables has a row."""
    pool = await get_pool()
    for table, _ in TABLES:
        if await pool.fetchval(f"SELECT EXISTS (SELECT 1 FROM {table})"):
            return False
    return True


async def counts() -> dict[str, int]:
    pool = await get_pool()
    return {table: await pool.fetchval(f"SELECT count(*) FROM {table}") for table, _ in TABLES}


async def insert_dataset(dataset: SeedDataset) -> None:
    """Bulk-insert a generated dataset in one transaction (all rows or none)."""
    rows_by_table = {
        "sales_people": dataset.sales_people,
        "clients": dataset.clients,
        "deals": dataset.deals,
        "activities": dataset.activities,
    }
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        for table, columns in TABLES:
            records = [tuple(row[column] for column in columns) for row in rows_by_table[table]]
            await conn.copy_records_to_table(table, records=records, columns=list(columns))


async def insert_client_with_deal(client: dict[str, Any], deal: dict[str, Any]) -> None:
    """Insert a UI-created client and its first deal in one transaction (all or nothing)."""
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        for table, columns, row in (
            ("clients", CLIENTS_COLUMNS, client),
            ("deals", DEALS_COLUMNS, deal),
        ):
            await conn.copy_records_to_table(
                table, records=[tuple(row.get(column) for column in columns)], columns=list(columns)
            )


async def delete_client_with_deal(client_id: str, deal_id: str) -> None:
    """Undo `insert_client_with_deal` (used when the matching Neo4j write fails)."""
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM deals WHERE id = $1", deal_id)
        await conn.execute("DELETE FROM clients WHERE id = $1", client_id)


async def insert_row(table: str, row: dict[str, Any]) -> None:
    """Insert one UI-created row (missing columns become NULL)."""
    columns = COLUMNS_BY_TABLE[table]
    pool = await get_pool()
    await pool.copy_records_to_table(
        table, records=[tuple(row.get(column) for column in columns)], columns=list(columns)
    )


async def delete_row(table: str, row_id: str) -> None:
    """Undo `insert_row` (used when the matching Neo4j write fails)."""
    if table not in COLUMNS_BY_TABLE:
        raise ValueError(f"unknown table {table}")
    pool = await get_pool()
    await pool.execute(f"DELETE FROM {table} WHERE id = $1", row_id)


async def update_row(table: str, row_id: str, changes: dict[str, Any]) -> None:
    """Change columns of one row. Only real data columns are accepted."""
    if not changes:
        return
    allowed = set(COLUMNS_BY_TABLE[table]) - {"id"}
    unknown = set(changes) - allowed
    if unknown:
        raise ValueError(f"cannot update {table} columns {sorted(unknown)}")
    assignments = ", ".join(f'"{column}" = ${i}' for i, column in enumerate(changes, start=2))
    pool = await get_pool()
    await pool.execute(f"UPDATE {table} SET {assignments} WHERE id = $1", row_id, *changes.values())


async def set_deal_owner(deal_id: str, owner_id: str | None) -> None:
    """Record who owns a deal (the assignment engine or a manager decided it in Neo4j)."""
    await update_row("deals", deal_id, {"owner_id": owner_id})


async def fetch_rows(table: str, ids: list[str]) -> list[dict[str, Any]]:
    """The current rows with these ids, as generator-shaped dicts."""
    quoted = ", ".join(f'"{column}"' for column in COLUMNS_BY_TABLE[table])
    pool = await get_pool()
    records = await pool.fetch(f"SELECT {quoted} FROM {table} WHERE id = ANY($1::text[])", ids)
    return [dict(record) for record in records]


async def read_dataset() -> StoredDataset:
    """Read every row back, ordered by id, as generator-shaped dicts."""
    pool = await get_pool()
    out: dict[str, list[dict[str, Any]]] = {}
    for table, columns in TABLES:
        quoted = ", ".join(f'"{column}"' for column in columns)
        records = await pool.fetch(f"SELECT {quoted} FROM {table} ORDER BY id")
        out[table] = [dict(record) for record in records]
    return StoredDataset(
        sales_people=out["sales_people"],
        clients=out["clients"],
        deals=out["deals"],
        activities=out["activities"],
    )


async def truncate_all() -> None:
    """Delete every row (tests only: gives a fresh database to generate into)."""
    pool = await get_pool()
    await pool.execute("TRUNCATE activities, deals, clients, sales_people")
