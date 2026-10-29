"""SPA serving of ui/dist (no database needed: the app is used without its lifespan)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from app.main import create_app

INDEX_HTML = "<!doctype html><html><body><div id='root'></div></body></html>"


def _client(ui_dist: Path) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=create_app(ui_dist))
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
async def ui(tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    async with _client(dist) as client:
        yield client


async def test_root_returns_index_html(ui: httpx.AsyncClient) -> None:
    response = await ui.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "id='root'" in response.text


@pytest.mark.parametrize("path", ["/clients", "/deals/DL-0001", "/reps/SP-002", "/heatmap"])
async def test_deep_links_return_index_html(ui: httpx.AsyncClient, path: str) -> None:
    response = await ui.get(path)
    assert response.status_code == 200 and "id='root'" in response.text


async def test_static_files(ui: httpx.AsyncClient) -> None:
    assert (await ui.get("/assets/app.js")).text == "console.log('ok')"
    assert (await ui.get("/favicon.svg")).text == "<svg/>"
    assert (await ui.get("/assets/missing.js")).status_code == 404


@pytest.mark.parametrize("method", ["GET", "POST", "PATCH"])
async def test_unknown_api_path_stays_json_404(ui: httpx.AsyncClient, method: str) -> None:
    response = await ui.request(method, "/api/unknown")
    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "NOT_FOUND", "message": "Not Found", "details": {}}
    }


async def test_path_traversal_is_not_served(ui: httpx.AsyncClient, tmp_path: Path) -> None:
    (tmp_path / "secret.txt").write_text("nope", encoding="utf-8")
    response = await ui.get("/..%2Fsecret.txt")
    assert "nope" not in response.text


async def test_docs_still_served(ui: httpx.AsyncClient) -> None:
    assert (await ui.get("/openapi.json")).status_code == 200
    assert (await ui.get("/docs")).status_code == 200


async def test_without_build_ui_paths_explain_how_to_build(tmp_path: Path) -> None:
    async with _client(tmp_path / "not-built") as client:
        response = await client.get("/clients")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "UI_NOT_BUILT"
        assert (await client.get("/api/unknown")).json()["error"]["code"] == "NOT_FOUND"
