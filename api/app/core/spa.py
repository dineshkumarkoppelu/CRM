"""Serves the built React UI (ui/dist) with an SPA fallback (Phase 8).

Implemented as a fallback inside the 404 handler (not a catch-all route), so API behaviour is
untouched: unknown `/api/...` paths keep the JSON 404 for every method.
- `/assets/*` -> static files from ui/dist/assets.
- A GET/HEAD that matched no route and is not `/api/...`, `/docs`, `/redoc`, `/openapi.json`
  -> the file in ui/dist if it exists (e.g. favicon.svg), otherwise index.html.
- If ui/dist does not exist the API still works; UI paths return a JSON 404 `UI_NOT_BUILT`.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import error_response, http_exception_handler

# <repo>/ui/dist, resolved from this file: api/app/core/spa.py -> parents[3] = <repo>
DEFAULT_UI_DIST = Path(__file__).resolve().parents[3] / "ui" / "dist"

# A missing /assets/* file must stay a 404 (never index.html served as JavaScript).
_NON_UI_PREFIXES = ("/api/", "/assets/", "/docs", "/redoc", "/openapi.json")


def _is_ui_request(request: Request) -> bool:
    path = request.url.path
    return (
        request.method in ("GET", "HEAD")
        and path != "/api"
        and not path.startswith(_NON_UI_PREFIXES)
    )


def mount_spa(app: FastAPI, ui_dist: Path = DEFAULT_UI_DIST) -> None:
    """Mount /assets and install the SPA fallback. Call after register_exception_handlers."""
    dist = ui_dist.resolve()
    index = dist / "index.html"
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    async def not_found_or_spa(request: Request, exc: Exception) -> Response:
        assert isinstance(exc, StarletteHTTPException)
        if exc.status_code != 404 or not _is_ui_request(request):
            return await http_exception_handler(request, exc)
        if not index.is_file():
            return error_response(
                404,
                "UI_NOT_BUILT",
                "The web UI has not been built. Run: cd ui; npm ci; npm run build",
            )
        relative = request.url.path.lstrip("/")
        candidate = (dist / relative).resolve()
        if relative and candidate.is_file() and candidate.is_relative_to(dist):
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    app.add_exception_handler(StarletteHTTPException, not_found_or_spa)
