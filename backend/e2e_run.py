"""E2E proof driver — NOT product code; removed after the proof run.

Replays the exact path the poll loop takes (triage_and_dispatch on a
poller-written detected_changes row) and streams every pipeline event to
stdout with timestamps, then dumps the final records as JSON.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

sys.path.insert(0, "/home/daytona/codebase/backend")

os.environ["ALFRED_REPO_TARGET"] = "/home/daytona/codebase/examples/sample-repo"
os.environ["ALFRED_DB_PATH"] = "/home/daytona/codebase/backend/alfred.db"
os.environ["ALFRED_DISABLE_POLLER"] = "1"  # single controlled run, no loop interference

# Credential model: GitHub credentials are PER-REQUEST. This driver acts as the
# user and supplies the Freebuff-managed credential (via its sanctioned accessor,
# `gh auth token`) as this one run's github_token — held in a local variable,
# never printed, never written to env, db, or logs.
GH_OWNER = "gowthamchoudhary"
GH_REPO = "Alfred-0f-001"
try:
    proc = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=15)
    tok = (proc.stdout or "").strip()
    GH_TOKEN = tok if (proc.returncode == 0 and tok and not tok.startswith("gh:")) else None
    print(f"[env] per-request github_token: {'acquired from managed credential (len ' + str(len(tok)) + ')' if GH_TOKEN else 'unavailable (' + (proc.stderr or '')[:80] + ') — ACTION will skip cleanly'}", flush=True)
except Exception as exc:  # noqa: BLE001
    GH_TOKEN = None
    print(f"[env] per-request github_token: gh accessor failed: {exc}", flush=True)

for key in ("GROQ_API_KEY", "ANAKIN_API_KEY"):
    print(f"[env] {key}: {'present in process env' if os.environ.get(key) else 'ABSENT'}", flush=True)


def ts(epoch: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(epoch))


from alfred.db import Database  # noqa: E402
from alfred.triage import triage_and_dispatch  # noqa: E402

db = Database(os.environ["ALFRED_DB_PATH"])

# ---- seed: use the REAL poller-written row (no fabricated data) ------------
pending = db.list_detected_changes(status="pending", limit=200)
row = next(
    (r for r in pending if r["dependency_name"] == "openai" and r["latest_version"] == "3.13.0"),
    None,
)
if row is None:
    print("[seed] FATAL: no real poller-written openai 3.13.0 row found", flush=True)
    sys.exit(2)
print(
    f"[seed] using real poller-detected row id={row['id']} "
    f"openai=={row['latest_version']} source={row['source']} "
    f"release_url={row['release_url']} detected_at={ts(row['detected_at'])}",
    flush=True,
)

# Align watchlist metadata with the target repo's actual baseline so triage
# evaluates the bump the repo would actually take (1.99.0 -> 3.13.0).
db.update_watchlist_status("openai", "1.99.0")
print("[seed] watchlist openai last_seen_version := 1.99.0 (target repo baseline)", flush=True)

# ---- dispatch through the exact triage path poll_once uses -----------------
holder: dict = {}


def _dispatch() -> None:
    try:
        holder["inv_id"] = triage_and_dispatch(
            db,
            row,
            repo_source=os.environ["ALFRED_REPO_TARGET"],
            github_token=GH_TOKEN,
            github_owner=GH_OWNER,
            github_repo=GH_REPO,
        )
    except Exception as exc:  # noqa: BLE001
        holder["error"] = repr(exc)


t0 = time.time()
threading.Thread(target=_dispatch, name="e2e-pipeline", daemon=True).start()

seen = 0
inv_id: str | None = None
deadline = time.time() + 540
while time.time() < deadline:
    if "inv_id" in holder and holder["inv_id"] and not inv_id:
        inv_id = holder["inv_id"]
        print(f"[dispatch] investigation id: {inv_id}", flush=True)
    if "error" in holder and "inv_id" not in holder:
        print(f"[dispatch] pipeline raised: {holder['error']}", flush=True)
        break

    if inv_id:
        events = db.list_events(inv_id)
        for e in events[seen:]:
            level = e.get("level") or "info"
            print(f"[{ts(e['created_at'])}] {e['step']:<9} [{level}] {e['message']}", flush=True)
        seen = len(events)
        inv = db.get_investigation(inv_id)
        if inv and inv["status"] in ("complete", "failed"):
            break
    elif "error" not in holder:
        # triage may still be deciding; show its progress
        cur = db.get_pending_change(row["id"])
        if cur and cur["triage_status"] != "pending" and cur["triage_status"] != row["triage_status"]:
            print(f"[triage] status -> {cur['triage_status']}: {cur['triage_reason']}", flush=True)
    time.sleep(1.5)

elapsed = time.time() - t0
print(f"\n[run] pipeline thread finished in {elapsed:.1f}s", flush=True)

# ---- dump final ground truth ------------------------------------------------
out: dict = {"inv_id": inv_id, "elapsed_s": round(elapsed, 1), "dispatch_error": holder.get("error")}
if inv_id:
    inv = db.get_investigation(inv_id)
    out["investigation"] = inv
    out["events"] = [
        {k: e[k] for k in ("created_at", "step", "level", "message")}
        for e in db.list_events(inv_id)
    ]
    out["test_runs"] = []
    for tr in db.list_test_runs(inv_id):
        out["test_runs"].append({
            k: tr[k] for k in (
                "environment", "container_name", "build_success", "startup_success",
                "tests_passed", "tests_failed", "tests_errors", "tests_total",
                "pytest_summary", "workload_total_requests", "workload_successful_requests",
                "workload_error_rate", "latency_p50_ms", "latency_p95_ms",
                "latency_p99_ms", "throughput_rps",
            )
        })
    out["comparison"] = db.get_comparison(inv_id)
    out["decision"] = db.get_decision(inv_id)
    action = db.get_action(inv_id)
    if action:
        action = dict(action)
        action.pop("id", None)
    out["action"] = action
    change = db.get_pending_change(row["id"])
    out["detected_change_final"] = {
        k: change[k] for k in (
            "id", "dependency_name", "latest_version", "triage_status",
            "triage_reason", "triage_mode", "investigation_id",
        )
    } if change else None

with open("/tmp/e2e_result.json", "w") as fh:
    json.dump(out, fh, indent=2, default=str)
print("[run] final records written to /tmp/e2e_result.json", flush=True)
