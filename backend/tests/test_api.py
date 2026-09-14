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


@pytest.fixture(scope="module")
def auth_client(client: TestClient) -> TestClient:
    """A client with a signed-in Alfred account (cookie set)."""
    email = "cred-test@example.com"
    client.post("/api/auth/signup", json={"email": email, "password": "password123"})
    client.post("/api/auth/login", json={"email": email, "password": "password123"})
    return client


def test_health(client: TestClient):
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    for key in ("groq_key", "github_token", "docker_available"):
        assert key in body
    # GitHub is per-request now: the health endpoint must not report a global token
    assert body["github_token"] != True


def test_watchlist_seeded_and_crud(auth_client: TestClient):
    entries = auth_client.get("/api/watchlist").json()
    assert isinstance(entries, list)

    res = auth_client.post("/api/watchlist", json={"name": "httpx-test-pkg", "source": "pypi"})
    assert res.status_code == 200
    names = [w["name"] for w in auth_client.get("/api/watchlist").json()]
    assert "httpx-test-pkg" in names

    res = auth_client.request("DELETE", "/api/watchlist/httpx-test-pkg")
    assert res.status_code == 200
    names = [w["name"] for w in auth_client.get("/api/watchlist").json()]
    assert "httpx-test-pkg" not in names


def test_watchlist_requires_auth():
    """A cookie-less client must be rejected (watchlist now carries credentials)."""
    with TestClient(app) as fresh:
        assert fresh.get("/api/watchlist").status_code == 401
        assert fresh.post("/api/watchlist", json={"name": "x", "source": "pypi"}).status_code == 401


def test_watchlist_token_never_returned(auth_client: TestClient, monkeypatch):
    """THE credential-at-rest leak test.

    Registers a watchlist entry WITH a GitHub token, then asserts the
    plaintext token (and even the ciphertext) appear in NO response from ANY
    endpoint: the registration response, GET /api/watchlist, dashboard
    summary, investigation list/detail, detected-changes, and events.
    """
    import json as _json

    from alfred.app import db
    from alfred.crypto import decrypt_secret, generate_key

    os.environ["ALFRED_ENCRYPTION_KEY"] = generate_key()
    token = "ghp_NEVERLEAKTOKENVALUE123456"

    res = auth_client.post(
        "/api/watchlist",
        json={
            "name": "leak-probe-pkg",
            "source": "github",
            "repo": "owner/leak-probe",
            "github_token": token,
            "github_owner": "owner",
            "github_repo": "leak-probe",
        },
    )
    assert res.status_code == 200
    assert res.json()["credential_registered"] is True

    # The token was really stored — encrypted (ciphertext roundtrips, plaintext absent)
    stored = db.get_watchlist_credential("leak-probe-pkg")
    assert stored and stored["gh_token_enc"]
    assert decrypt_secret(stored["gh_token_enc"]) == token

    try:
        # EVERY read endpoint must be free of the plaintext AND the ciphertext
        responses = {
            "register": res.text,
            "watchlist": auth_client.get("/api/watchlist").text,
            "summary": auth_client.get("/api/dashboard/summary").text,
            "investigations": auth_client.get("/api/investigations").text,
            "changes": auth_client.get("/api/detected-changes").text,
            "events": auth_client.get("/api/events").text,
        }
        blob = _json.dumps(responses)
        assert token not in blob, "PLAINTEXT TOKEN LEAKED in an API response"
        assert stored["gh_token_enc"] not in blob, "CIPHERTEXT LEAKED in an API response"
        assert not any("gh_token_enc" in body for body in responses.values()), "credential column name leaked"
    finally:
        auth_client.request("DELETE", "/api/watchlist/leak-probe-pkg")
        os.environ.pop("ALFRED_ENCRYPTION_KEY", None)


def test_watchlist_github_requires_repo(auth_client: TestClient):
    res = auth_client.post("/api/watchlist", json={"name": "some-lib", "source": "github"})
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
