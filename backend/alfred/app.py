"""FastAPI application — REST surface for the Alfred dashboard.

Endpoints (all JSON, polling-friendly, no auth by design — single project scope):
    GET  /api/health
    GET  /api/investigations                list (newest first)
    POST /api/investigations                manual trigger (background thread)
    GET  /api/investigations/{id}           full detail: events, runs, compare, decision, action
    GET  /api/detected-changes              every discovered release, incl. skipped
    POST /api/discovery/poll                force one discovery poll now
    GET  /api/watchlist                     monitored dependencies
    POST /api/watchlist                     add {name, source, repo}
    DELETE /api/watchlist/{name}            stop watching
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

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

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
)


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


# ------------------------------------------------------------------- helpers
def _dispatch_investigation(
    repo_source: str,
    target_version: str,
    dependency_name: str | None,
    trigger: str,
    github_token: str | None = None,
    github_owner: str | None = None,
    github_repo: str | None = None,
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
        "github_token": "per-request (supplied by each investigation trigger)",
        "exa_key": bool(os.environ.get("EXA_API_KEY")),
        "persist_to_supabase": bool(getattr(db, "is_postgres", False)),
        "docker_available": _quick_docker_probe(),
    }


def _quick_docker_probe() -> bool:
    try:
        from .docker_runner import _docker_available

        return _docker_available()
    except Exception:  # noqa: BLE001
        return False


@app.get("/api/investigations")
def list_investigations(limit: int = 50) -> list[dict[str, Any]]:
    return db.list_investigations(limit=limit)


@app.post("/api/investigations")
def trigger_investigation(req: TriggerRequest) -> dict[str, Any]:
    inv_id = _dispatch_investigation(
        req.repo_source,
        req.target_version,
        req.dependency_name,
        trigger="manual",
        github_token=req.github_token,
        github_owner=req.github_owner,
        github_repo=req.github_repo,
    )
    return {"investigation_id": inv_id}


@app.get("/api/investigations/{inv_id}")
def investigation_detail(inv_id: str) -> dict[str, Any]:
    inv = db.get_investigation(inv_id)
    if not inv:
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
def get_watchlist() -> list[dict[str, Any]]:
    return db.list_watchlist()


@app.post("/api/watchlist")
def add_watch(req: WatchlistRequest) -> dict[str, Any]:
    if req.source not in ("pypi", "github"):
        raise HTTPException(status_code=400, detail="source must be 'pypi' or 'github'")
    if req.source == "github" and not req.repo:
        raise HTTPException(status_code=400, detail="github watchlist entries need a repo (owner/name)")
    db.add_watchlist_entry(req.name, req.source, req.repo)
    return {"ok": True, "name": req.name}


@app.delete("/api/watchlist/{name}")
def remove_watch(name: str) -> dict[str, Any]:
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
