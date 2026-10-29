"""Logging setup and the per-request log line (request id, method, path, status, duration_ms).

Every request gets an id: the caller's `X-Request-ID` if it is a safe token, otherwise a new
one. It is returned in the `X-Request-ID` response header and added to every log line written
while the request is handled, so one request can be followed through the log.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from fastapi import FastAPI, Request, Response

REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_FORMAT = "%(asctime)s %(levelname)s %(name)s [%(request_id)s]: %(message)s"

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
request_logger = logging.getLogger("app.request")
logger = logging.getLogger(__name__)


class RequestIdFilter(logging.Filter):
    """Adds `record.request_id` (the current request's id, or '-')."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def configure_logging(level: str) -> None:
    """Configure the root logger from LOG_LEVEL (idempotent)."""
    logging.basicConfig(level=level, format=_FORMAT, force=True)
    for handler in logging.getLogger().handlers:
        handler.addFilter(RequestIdFilter())
    # Keep the neo4j driver quiet unless something is wrong.
    logging.getLogger("neo4j").setLevel(max(logging.getLevelName(level), logging.WARNING))


def new_request_id(incoming: str | None) -> str:
    if incoming and _SAFE_REQUEST_ID.match(incoming):
        return incoming
    return uuid.uuid4().hex[:16]


def add_request_logging(app: FastAPI) -> None:
    # Imported here to avoid a circular import (errors -> logging is not needed elsewhere).
    from app.core.errors import error_response

    @app.middleware("http")
    async def log_request(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = new_request_id(request.headers.get(REQUEST_ID_HEADER))
        token = request_id_var.set(request_id)
        start = time.perf_counter()
        try:
            try:
                response = await call_next(request)
            except Exception:
                # Unhandled error: answer with the standard shape (and the request id) here,
                # instead of Starlette's bare 500.
                logger.exception("Unhandled error on %s %s", request.method, request.url.path)
                response = error_response(500, "INTERNAL_ERROR", "An unexpected error occurred")
            response.headers[REQUEST_ID_HEADER] = request_id
            duration_ms = (time.perf_counter() - start) * 1000
            request_logger.info(
                "%s %s %d %.1fms",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
            )
            return response
        finally:
            request_id_var.reset(token)
