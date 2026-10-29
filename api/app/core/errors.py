"""Standard error shape and exception handlers.

Every failure returns: {"error": {"code": "<UPPER_SNAKE>", "message": "<text>", "details": {}}}
"""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from neo4j.exceptions import Neo4jError, ServiceUnavailable, SessionExpired
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Business/application error rendered with the standard error shape."""

    def __init__(
        self,
        code: str,
        message: str,
        status: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details or {}


def error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def error_response(
    status: int, code: str, message: str, details: dict[str, Any] | None = None
) -> JSONResponse:
    content = jsonable_encoder(error_body(code, message, details))
    return JSONResponse(status_code=status, content=content)


def _code_for_status(status: int) -> str:
    try:
        return HTTPStatus(status).name  # e.g. 404 -> NOT_FOUND, 405 -> METHOD_NOT_ALLOWED
    except ValueError:
        return f"HTTP_{status}"


async def _app_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return error_response(exc.status, exc.code, exc.message, exc.details)


async def http_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    message = exc.detail if isinstance(exc.detail, str) else HTTPStatus(exc.status_code).phrase
    response = error_response(exc.status_code, _code_for_status(exc.status_code), message)
    if exc.headers:
        response.headers.update(exc.headers)
    return response


async def _validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return error_response(
        422, "VALIDATION_ERROR", "Request validation failed", {"errors": exc.errors()}
    )


async def _neo4j_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Database failures get a clear code instead of a generic 500."""
    if isinstance(exc, Neo4jError) and "TransactionTimedOut" in (exc.code or ""):
        logger.warning("Query timed out on %s %s: %s", request.method, request.url.path, exc)
        return error_response(504, "QUERY_TIMEOUT", "The database query took too long")
    if isinstance(exc, (ServiceUnavailable, SessionExpired)):
        logger.warning("Neo4j unavailable on %s %s: %s", request.method, request.url.path, exc)
        return error_response(503, "NEO4J_UNAVAILABLE", "Neo4j is not reachable")
    logger.error("Database error on %s %s", request.method, request.url.path, exc_info=exc)
    return error_response(500, "DATABASE_ERROR", "The database rejected the request")


async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    return error_response(500, "INTERNAL_ERROR", "An unexpected error occurred")


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(Neo4jError, _neo4j_error_handler)
    app.add_exception_handler(ServiceUnavailable, _neo4j_error_handler)
    app.add_exception_handler(SessionExpired, _neo4j_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)
