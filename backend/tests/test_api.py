"""API-level tests for the FastAPI surface.

Uses a temp SQLite DB and disables the background poller so tests stay fast
and hermetic (no network calls).
"""

from __future__ import annotations

import os
import sys
import tempfile

import pytest

os.environ["ALFRED_DISABLE_POLLER"] = "1"
_tmpdir = tempfile.mkdtemp()
os.environ["ALFRED_DB_PATH"] = os.path.join(_tmpdir, "api-test.db")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from alfred.app import app  # noqa: E402


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def test_health(client: TestClient):
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    for key in ("groq_key", "github_token", "docker_available"):
        assert key in body
    # GitHub is per-request now: the health endpoint must not report a global token
    assert body["github_token"] != True


def test_watchlist_seeded_and_crud(client: TestClient):
    entries = client.get("/api/watchlist").json()
    assert isinstance(entries, list)

    res = client.post("/api/watchlist", json={"name": "httpx-test-pkg", "source": "pypi"})
    assert res.status_code == 200
    names = [w["name"] for w in client.get("/api/watchlist").json()]
    assert "httpx-test-pkg" in names

    res = client.request("DELETE", "/api/watchlist/httpx-test-pkg")
    assert res.status_code == 200
    names = [w["name"] for w in client.get("/api/watchlist").json()]
    assert "httpx-test-pkg" not in names


def test_watchlist_github_requires_repo(client: TestClient):
    res = client.post("/api/watchlist", json={"name": "some-lib", "source": "github"})
    assert res.status_code == 400


def test_investigations_empty_list(client: TestClient):
    res = client.get("/api/investigations")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_investigation_404(client: TestClient):
    res = client.get("/api/investigations/nonexistent")
    assert res.status_code == 404


def test_detected_changes_endpoint(client: TestClient):
    res = client.get("/api/detected-changes")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_live_events_endpoint(client: TestClient):
    res = client.get("/api/events?limit=5")
    assert res.status_code == 200
    assert isinstance(res.json(), list)
