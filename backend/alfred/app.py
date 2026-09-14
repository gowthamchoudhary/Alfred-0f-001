"""FastAPI application — REST surface for the Alfred dashboard.

Endpoints (all JSON, polling-friendly; all dashboard data is scoped to the
authenticated user via the session cookie):
    GET  /api/health
    GET  /api/dashboard/summary             {counts, recent_investigations, activity, projects}
    GET  /api/investigations                list (newest first, user-scoped)
    POST /api/investigations                manual trigger (background thread)
    GET  /api/investigations/{id}           full detail: events, runs, compare, decision, action
    GET  /api/detected-changes              every discovered release, incl. skipped
    POST /api/discovery/poll                force one discovery poll now
    GET  /api/watchlist                     monitored dependencies (auth; credentials never included)
    POST /api/watchlist                     add {name, source, repo, github_token?} — token encrypted once, never returned
    DELETE /api/watchlist/{name}            stop watching (auth)
    GET  /api/events                        live tail of recent event lines

Serves the built frontend from ../frontend/dist when present.
"""

from __future__ import annotations

import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auth import create_auth_router, current_user
from .crypto import EncryptionKeyMissing, encrypt_secret
from .db import Database
from .discovery import poll_once, start_poller, stop_poller
from .events import recent_events
from .orchestrator import DockerUnavailableError, run_investigation

DEFAULT_WATCHLIST = ("openai", "anthropic", "groq")

db = Database()
_running: dict[str, str] = {}  # investigation_id -> repo_source (live registry)
_running_lock = threading.Lock()


def _seed_watchlist() -> None:
    existing = {w["name"] for w in db.list_watchlist()}
    for name in DEFAULT_WATCHLIST:
        if name not in existing:
            db.add_watchlist_entry(name, source="pypi")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _seed_watchlist()
    if os.environ.get("ALFRED_DISABLE_POLLER", "").lower() not in ("1", "true", "yes"):
        start_poller(db)
    yield
    stop_poller()


app = FastAPI(title="Alfred", version="0.1.0", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)
app.include_router(create_auth_router(db))


# --------------------------------------------------------------------- models
class TriggerRequest(BaseModel):
    repo_source: str = Field(..., description="Local path or git URL of a contract-compliant repo")
    target_version: str = Field(..., description="Dependency version to test as candidate")
    dependency_name: str | None = Field(None, description="Overrides alfred.yaml when set")
    github_token: str | None = Field(
        None,
        description="Caller's own GitHub PAT, used in-memory for this one investigation only — never stored or logged",
    )
    github_owner: str | None = Field(None, description="Owner of the repo the verdict issue is posted to")
    github_repo: str | None = Field(None, description="Repo the verdict issue is posted to")


class WatchlistRequest(BaseModel):
    name: str
    source: str = "pypi"
    repo: str | None = None
    # ONE-TIME registration credential for unattended auto-investigations.
    # Encrypted at rest immediately and never returned by any endpoint.
    github_token: str | None = Field(
        None,
        description="User's GitHub PAT, stored Fernet-encrypted on this entry so the poller can run unattended. Never returned by any API response.",
    )
    github_owner: str | None = Field(None, description="Owner of the repo the verdict issue is posted to")
    github_repo: str | None = Field(None, description="Repo the verdict issue is posted to")


# ------------------------------------------------------------------- helpers
def require_user(request: Request) -> dict[str, Any]:
    """Dashboard data is private: every data route requires a signed-in user."""
    user = current_user(db, request)
    if not user:
        raise HTTPException(status_code=401, detail="not signed in")
    return user


def _dispatch_investigation(
    repo_source: str,
    target_version: str,
    dependency_name: str | None,
    trigger: str,
    github_token: str | None = None,
    github_owner: str | None = None,
    github_repo: str | None = None,
    user_id: str | None = None,
) -> str:
    """Run the pipeline in a background thread; return the investigation id immediately.

    ``github_token``/``github_owner``/``github_repo`` are forwarded to the
    pipeline thread in memory only — never written to the database or logs.
    """
    inv_holder: dict[str, str] = {}

    def _run() -> None:
        try:
            inv_id = run_investigation(
                db,
                repo_source=repo_source,
                target_version=target_version,
                dependency_name=dependency_name,
                github_token=github_token,
                github_owner=github_owner,
                github_repo=github_repo,
                trigger=trigger,
                user_id=user_id,
            )
            inv_holder["id"] = inv_id
        except DockerUnavailableError as exc:
            inv_holder["error"] = str(exc)
        except Exception as exc:  # noqa: BLE001
            inv_holder["error"] = str(exc)
        finally:
            with _running_lock:
                _running.pop(inv_holder.get("id", ""), None)

    thread = threading.Thread(target=_run, name="alfred-pipeline", daemon=True)
    thread.start()
    # The investigation row is created inside PREPARE; wait briefly for it so
    # the caller gets a pollable id right away.
    deadline = time.time() + 15
    while time.time() < deadline:
        if "id" in inv_holder or "error" in inv_holder:
            break
        time.sleep(0.2)
    if "error" in inv_holder and "id" not in inv_holder:
        raise HTTPException(status_code=400, detail=inv_holder["error"])
    if "id" not in inv_holder:
        raise HTTPException(status_code=202, detail="investigation starting; poll /api/investigations shortly")
    return inv_holder["id"]


# -------------------------------------------------------------------- routes
@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "time": time.time(),
        "running": list(_running.keys()),
        "groq_key": bool(os.environ.get("GROQ_API_KEY")),
        "github_token": "per-request, or encrypted-at-rest on the watchlist entry (ALFRED_ENCRYPTION_KEY)",
        "anakin_key": bool(os.environ.get("ANAKIN_API_KEY")),
        "encryption_key": bool(os.environ.get("ALFRED_ENCRYPTION_KEY")),
        "persist_to_supabase": bool(getattr(db, "is_postgres", False)),
        "docker_available": _quick_docker_probe(),
    }


def _quick_docker_probe() -> bool:
    try:
        from .docker_runner import _docker_available

        return _docker_available()
    except Exception:  # noqa: BLE001
        return False


@app.get("/api/dashboard/summary")
def dashboard_summary(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    """One round-trip for the dashboard Overview tab — every value is real:
    counts from ``investigations``, cards from the latest persisted rows.
    """
    uid: str | None = user["id"]
    counts = db.investigations_summary_counts(uid)
    recent = db.list_investigations(limit=6, user_id=uid)
    runs_by_inv: dict[str, dict[str, Any]] = {}
    for inv in recent:
        runs = db.list_test_runs(inv["id"])
        if runs:
            runs_by_inv[inv["id"]] = {r["environment"]: r for r in runs}
    return {
        "user": {"id": user["id"], "email": user["email"]},
        "counts": counts,
        "recent_investigations": recent,
        "test_runs_by_investigation": runs_by_inv,
        "activity": db.recent_activity(limit=8, user_id=uid),
        "projects": db.monitored_projects(user_id=uid, limit=4),
        "watchlist_count": len(db.list_watchlist()),
    }


@app.get("/api/investigations")
def list_investigations(
    limit: int = 50, user: dict[str, Any] = Depends(require_user)
) -> list[dict[str, Any]]:
    return db.list_investigations(limit=limit, user_id=user["id"])


@app.post("/api/investigations")
def trigger_investigation(
    req: TriggerRequest, user: dict[str, Any] = Depends(require_user)
) -> dict[str, Any]:
    inv_id = _dispatch_investigation(
        req.repo_source,
        req.target_version,
        req.dependency_name,
        trigger="manual",
        github_token=req.github_token,
        github_owner=req.github_owner,
        github_repo=req.github_repo,
        user_id=user["id"],
    )
    return {"investigation_id": inv_id}


@app.get("/api/investigations/{inv_id}")
def investigation_detail(
    inv_id: str, user: dict[str, Any] = Depends(require_user)
) -> dict[str, Any]:
    inv = db.get_investigation(inv_id)
    if not inv:
        raise HTTPException(status_code=404, detail="investigation not found")
    if inv.get("user_id") and inv["user_id"] != user["id"]:
        # Another user's investigation — indistinguishable from missing.
        raise HTTPException(status_code=404, detail="investigation not found")
    return {
        "investigation": inv,
        "events": db.list_events(inv_id),
        "test_runs": db.list_test_runs(inv_id),
        "comparison": db.get_comparison(inv_id),
        "decision": db.get_decision(inv_id),
        "action": db.get_action(inv_id),
    }


@app.get("/api/detected-changes")
def list_detected_changes(status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    return db.list_detected_changes(status=status, limit=limit)


@app.post("/api/discovery/poll")
def discovery_poll() -> dict[str, Any]:
    new_count = poll_once(db)
    return {"new_changes": new_count}


@app.get("/api/watchlist")
def get_watchlist(user: dict[str, Any] = Depends(require_user)) -> list[dict[str, Any]]:
    # db.list_watchlist() projects credential columns away — the encrypted
    # token structurally cannot appear here even if future code changes the
    # row shape. Auth required: entries now carry credentials at rest.
    return db.list_watchlist()


@app.post("/api/watchlist")
def add_watch(req: WatchlistRequest, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    if req.source not in ("pypi", "github"):
        raise HTTPException(status_code=400, detail="source must be 'pypi' or 'github'")
    if req.source == "github" and not req.repo:
        raise HTTPException(status_code=400, detail="github watchlist entries need a repo (owner/name)")
    gh_token_enc: str | None = None
    if req.github_token:
        try:
            # Encrypt BEFORE the token touches any persistence layer. Only the
            # ciphertext is stored; the plaintext dies with this request.
            gh_token_enc = encrypt_secret(req.github_token)
        except EncryptionKeyMissing as exc:
            raise HTTPException(
                status_code=503,
                detail=f"cannot store credential: {exc}",
            ) from exc
    db.add_watchlist_entry(
        req.name,
        req.source,
        req.repo,
        gh_token_enc=gh_token_enc,
        gh_owner=req.github_owner,
        gh_repo=req.github_repo,
    )
    registered = bool(req.github_token)
    return {"ok": True, "name": req.name, "credential_registered": registered}


@app.delete("/api/watchlist/{name}")
def remove_watch(name: str, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    db.remove_watchlist_entry(name)
    return {"ok": True}


@app.get("/api/events")
def live_events(limit: int = 100) -> list[dict[str, Any]]:
    return recent_events(limit=limit)


# ------------------------------------------------------------- static frontend
_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str) -> FileResponse:
        candidate = _FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_FRONTEND_DIST / "index.html")


def main() -> None:  # pragma: no cover — dev entrypoint
    import uvicorn

    uvicorn.run(
        "alfred.app:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        reload=False,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
