"""Serving the frontend's static build from the API (`LOOPBOARD_STATIC_DIR`)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import create_app


@pytest.fixture
def web(tmp_path: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log('app')")
    (tmp_path / "_shell.html").write_text("<html>shell</html>")
    (tmp_path.parent / "secret.txt").write_text("nope")
    monkeypatch.setattr(settings, "static_dir", str(tmp_path))
    with TestClient(create_app()) as web_client:
        yield web_client


def test_serves_static_files(web: TestClient) -> None:
    response = web.get("/assets/app.js")
    assert response.status_code == 200
    assert response.text == "console.log('app')"


@pytest.mark.parametrize("path", ["/", "/signin", "/session/abc123", "/join/abc123"])
def test_client_routes_get_the_shell(web: TestClient, path: str) -> None:
    response = web.get(path)
    assert response.status_code == 200
    assert response.text == "<html>shell</html>"


def test_api_routes_still_win(web: TestClient) -> None:
    assert web.get("/health").json()["status"] == "ok"
    assert web.post("/auth/login", json={"email": "x@y.z", "password": "no"}).status_code == 401


@pytest.mark.parametrize("path", ["/sessions/nope/whatever", "/auth/nope", "/assets/missing.js"])
def test_api_misses_are_json_404s(web: TestClient, path: str) -> None:
    response = web.get(path)
    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


def test_does_not_escape_the_static_dir(web: TestClient) -> None:
    response = web.get("/..%2Fsecret.txt")
    assert "nope" not in response.text


def test_disabled_by_default(client: TestClient) -> None:
    assert client.get("/signin").status_code == 404
