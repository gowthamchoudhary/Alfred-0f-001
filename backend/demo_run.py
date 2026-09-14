"""TEMP demo orchestrator — the FULL unattended lifecycle in one command.

Sequence (no human input at any point after start):
  1. best-effort dockerd startup (single-command approach)
  2. launch the REAL server (demo_server.py -> uvicorn("alfred.app:app") ->
     lifespan -> start_poller) as a subprocess
  3. wait for the poller's startup line, then let it tick on its 10s cadence —
     it finds the two pending detected_changes rows (seeded earlier, exactly
     as poll_once writes them), triages both, auto-invokes BOTH pipelines
     using each entry's stored encrypted token
  4. harvest the timestamped event log + investigation rows from Supabase
  5. stop the server, remove the two demo watchlist entries (so the poller
     stops spending Anakin credits on fake deps), keep the evidence rows

Delete after running.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
BACKEND = Path(__file__).resolve().parent

for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

os.environ.setdefault("ALFRED_ENCRYPTION_KEY", "aDHmsp9IvGfKZubuI13Zz0F2lEcEMsCscn_YBmO5cSY=")
os.environ.setdefault("ALFRED_REPO_TARGET", str(ROOT / "examples" / "sample-repo"))
os.environ.setdefault("ALFRED_POLL_INTERVAL", "10")

sys.path.insert(0, str(BACKEND))

LOG = Path("/tmp/alfred_demo2.log")
DOCKERD_LOG = Path("/tmp/dockerd.log")


def start_dockerd() -> bool:
    try:
        r = subprocess.run(["docker", "ps"], capture_output=True, timeout=10)
        if r.returncode == 0:
            print("dockerd: already up")
            return True
    except Exception:
        pass
    try:
        with open(DOCKERD_LOG, "wb") as fh:
            subprocess.Popen(["dockerd"], stdout=fh, stderr=fh)  # noqa: S603,S607
        deadline = time.time() + 40
        while time.time() < deadline:
            try:
                if subprocess.run(["docker", "ps"], capture_output=True, timeout=10).returncode == 0:
                    print("dockerd: started")
                    return True
            except Exception:
                pass
            time.sleep(2)
        print(f"dockerd: FAILED to start (see {DOCKERD_LOG}) — pipeline will fail honestly at BUILD")
    except FileNotFoundError:
        print("dockerd: binary not found — pipeline will fail honestly at BUILD")
    return False


def log_tail() -> str:
    return LOG.read_text(encoding="utf-8", errors="replace") if LOG.exists() else ""


start_dockerd()

server = subprocess.Popen(  # noqa: S603
    [sys.executable, "-u", str(BACKEND / "demo_server.py")],
    stdout=open(LOG, "wb"),
    stderr=subprocess.STDOUT,
    cwd=str(BACKEND),
)
print(f"server pid {server.pid} — waiting for poller startup line...")
deadline = time.time() + 30
while time.time() < deadline and "background poller started" not in log_tail():
    time.sleep(1)
tail = log_tail()
print("--- poller startup ---")
print("\n".join(tail.splitlines()[-3:]))

# Unattended watch window: poller ticks every 10s, dispatches pending rows,
# pipelines run concurrently. Harvest at the end of the window.
WATCH = 115
print(f"--- watching {WATCH}s of fully unattended operation ---")
time.sleep(WATCH)

from alfred.db import Database  # noqa: E402
from sqlalchemy import text  # noqa: E402

db = Database()
out: dict = {"server_log": log_tail().splitlines()[-40:]}

with db.engine.connect() as conn:
    invs = conn.execute(
        text(
            "SELECT id, dependency_name, baseline_version, candidate_version, trigger,"
            " status, current_step, verdict, error, created_at, user_id"
            " FROM investigations WHERE trigger='discovery' ORDER BY created_at ASC"
        )
    ).mappings().fetchall()
    out["auto_investigations"] = [dict(r) for r in invs]
    evs = conn.execute(
        text(
            "SELECT e.investigation_id, e.step, e.message, e.level, e.created_at"
            " FROM agent_events e JOIN investigations i ON i.id = e.investigation_id"
            " WHERE i.trigger='discovery' ORDER BY e.created_at ASC, e.id ASC"
        )
    ).mappings().fetchall()
    out["events"] = [dict(r) for r in evs]
    acts = conn.execute(
        text(
            "SELECT a.investigation_id, a.success, a.skipped, a.skip_reason, a.issue_url,"
            " a.issue_number, a.verified, a.error FROM actions a"
            " JOIN investigations i ON i.id = a.investigation_id WHERE i.trigger='discovery'"
        )
    ).mappings().fetchall()
    out["actions"] = [dict(r) for r in acts]
    chs = conn.execute(
        text(
            "SELECT dependency_name, latest_version, triage_status, triage_reason,"
            " investigation_id FROM detected_changes WHERE dependency_name LIKE 'demo-%'"
        )
    ).mappings().fetchall()
    out["changes"] = [dict(r) for r in chs]

print(json.dumps(out, indent=1, default=str))

# Stop the server; remove demo watchlist entries (stop future Anakin spend);
# keep evidence rows (investigations/events/changes) for the report.
server.terminate()
try:
    server.wait(timeout=10)
except Exception:
    server.kill()
db.remove_watchlist_entry("demo-alpha")
db.remove_watchlist_entry("demo-beta")
print("server stopped; demo watchlist entries removed; evidence rows kept")
