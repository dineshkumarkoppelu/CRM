"""HTTP client for the Postgres CRUD API (the source of truth).

One shared `httpx.AsyncClient`. Every call sends `X-API-Key`; failures become `AppError`s so
the UI gets the standard error shape (401 from the source is a 502 here: it is not the
caller's fault).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.errors import AppError
from app.core.settings import get_settings

logger = logging.getLogger(__name__)

PAGE_SIZE = 1000  # the source API's maximum
TIMEOUT_S = 20.0

_client: httpx.AsyncClient | None = None


def enabled() -> bool:
    return get_settings().source_enabled


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        settings = get_settings()
        _client = httpx.AsyncClient(
            base_url=(settings.SOURCE_API_URL or "").rstrip("/"),
            headers={
                "X-API-Key": settings.SOURCE_API_KEY or "",
                # ngrok's free tier otherwise answers some clients with an HTML warning page.
                "ngrok-skip-browser-warning": "true",
            },
            timeout=TIMEOUT_S,
        )
    return _client


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _unavailable(exc: Exception) -> AppError:
    return AppError(
        "SOURCE_UNAVAILABLE",
        "The data source (Postgres API) is not reachable right now",
        503,
        {"reason": type(exc).__name__},
    )


def _raise_for(table: str, response: httpx.Response) -> None:
    status = response.status_code
    if status < 400:
        return
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = response.text[:200]
    if status == 401:
        raise AppError("SOURCE_AUTH", "The data source rejected SOURCE_API_KEY", 502)
    if status == 404:
        raise AppError("NOT_FOUND", f"{table}: {detail}", 404)
    if status == 409:
        raise AppError("CONFLICT", f"{table}: {detail}", 409)
    if status == 422:
        raise AppError("VALIDATION_ERROR", f"{table}: {detail}", 422)
    raise AppError("SOURCE_ERROR", f"The data source answered {status}", 502, {"detail": detail})


async def _request(
    method: str, path: str, table: str, *, json: Any = None, params: dict[str, Any] | None = None
) -> Any:
    try:
        response = await _http().request(method, path, json=json, params=params)
    except httpx.HTTPError as exc:
        raise _unavailable(exc) from exc
    _raise_for(table, response)
    try:
        return response.json()
    except ValueError as exc:  # e.g. an HTML interstitial instead of JSON
        raise AppError("SOURCE_ERROR", "The data source did not answer with JSON", 502) from exc


async def list_all(table: str) -> list[dict[str, Any]]:
    """Every row of a table, paged, ordered by id."""
    rows: list[dict[str, Any]] = []
    while True:
        page = await _request(
            "GET",
            f"/{table}",
            table,
            params={"limit": PAGE_SIZE, "offset": len(rows), "order_by": "id"},
        )
        if not isinstance(page, list):
            raise AppError("SOURCE_ERROR", f"Unexpected answer listing {table}", 502)
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows


async def get(table: str, row_id: str) -> dict[str, Any] | None:
    try:
        return await _request("GET", f"/{table}/{row_id}", table)
    except AppError as exc:
        if exc.status == 404:
            return None
        raise


async def create(table: str, body: dict[str, Any]) -> dict[str, Any]:
    return await _request("POST", f"/{table}", table, json=body)


async def patch(table: str, row_id: str, body: dict[str, Any]) -> dict[str, Any]:
    return await _request("PATCH", f"/{table}/{row_id}", table, json=body)


async def delete(table: str, row_id: str) -> None:
    await _request("DELETE", f"/{table}/{row_id}", table)
