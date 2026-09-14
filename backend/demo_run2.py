"""TEMP demo orchestrator #2 — full unattended lifecycle, longer watch window.

Same as demo_run.py but: cleans the previous demo artifacts, registers the two
entries with a REAL GitHub token when one exists in the project env (so ACTION
creates a real issue), watches 240s, then cleans up. Delete after running.
"""

from __future__ import annotations

import json
import os
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

from sqlalchemy import text  # noqa: E402

from alfred.crypto import encrypt_secret  # noqa: E402
from alfred.db import Database  # noqa: E402

LOG = Path("/tmp/alfred_demo3.log")
db = Database()

# ---- tidy the previous demo artifacts (killed mid-run) ----------------------
with db.engine.begin() as conn:
    conn.execute(
        text(
            "UPDATE investigations SET status='failed',"
            " error='demo sandbox stopped the run mid-pipeline'"
            " WHERE trigger='discovery' AND dependency_name LIKE 'demo-%' AND status='running'"
        )
    )
    conn.execute(text("DELETE FROM detected_changes WHERE dependency_name LIKE 'demo-%'"))

# ---- a real GitHub token for ACTION? ----------------------------------------
real_token = next(
    (os.environ[n] for n in ("GITHUB_TOKEN", "GH_TOKEN", "ALFRED_GITHUB_TOKEN") if os.environ.get(n)),
    None,
)
if real_token:
    print("real GitHub token found in project env — demo entries will post REAL issues")
    tok, owner, repo = real_token, "gowthamchoudhary", "Alfred-0f-001"
else:
    print("NO real GitHub token in env — demo tokens will be used; ACTION will fail honestly (401)")
    tok, owner, repo = "ghp_DEMO_TOKEN_X_0000", "owner", "demo-beta"

db.add_watchlist_entry(
    "demo-alpha", "github", f"{owner}/demo-alpha",
    gh_token_enc=encrypt_secret(tok), gh_owner=owner, gh_repo=repo,
)
db.add_watchlist_entry(
    "demo-beta", "github", f"{owner}/{repo if real_token else 'demo-beta'}",
    gh_token_enc=encrypt_secret(tok), gh_owner=owner, gh_repo=repo if real_token else "demo-beta",
)

# ---- dockerd (best-effort, single-command approach) --------------------------
def dockerd_up() -> bool:
    try:
        if subprocess.run(["docker", "ps"], capture_output=True, timeout=10).returncode == 0:
            print("dockerd: already up")
            return True
    except Exception:
        pass
    try:
        with open("/tmp/dockerd.log", "wb") as fh:
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
    except FileNotFoundError:
        pass
    print("dockerd: FAILED — pipelines will fail honestly at BUILD")
    return False


dockerd_up()

# ---- insert the two detected_changes rows EXACTLY as the poller writes them --
for dep, ver, notes in (("demo-alpha", "3.0.0", "Major release with breaking changes"),
                        ("demo-beta", "2.0.0", "Major version bump")):
    db.upsert_detected_change(
        {
            "dependency_name": dep,
            "source": "github",
            "latest_version": ver,
            "release_notes": notes,
            "release_url": f"https://github.com/{owner}/{dep}/releases/tag/v{ver}",
            "published_at": "2026-09-14T00:00:00Z",
        }
    )
print("two pending detected_changes rows inserted — hands off from here")

# ---- real server; poller starts itself via lifespan --------------------------
server = subprocess.Popen(  # noqa: S603
    [sys.executable, "-u", str(BACKEND / "demo_server.py")],
    stdout=open(LOG, "wb"),
    stderr=subprocess.STDOUT,
    cwd=str(BACKEND),
)
deadline = time.time() + 30
while time.time() < deadline and "background poller started" not in (LOG.read_text(errors="replace") if LOG.exists() else ""):
    time.sleep(1)
print("poller started line seen — watching 240s of unattended operation")
time.sleep(240)

out: dict = {"server_log_tail": LOG.read_text(errors="replace").splitlines()[-45:]}
with db.engine.connect() as conn:
    invs = conn.execute(
        text(
            "SELECT id, dependency_name, candidate_version, trigger, status, current_step,"
            " verdict, compatibility_score, github_issue_url, error"
            " FROM investigations WHERE trigger='discovery' AND dependency_name LIKE 'demo-%'"
            " ORDER BY created_at ASC"
        )
    ).mappings().fetchall()
    out["auto_investigations"] = [dict(r) for r in invs]
    evs = conn.execute(
        text(
            "SELECT e.investigation_id, e.step, e.message, e.level, e.created_at"
            " FROM agent_events e JOIN investigations i ON i.id = e.investigation_id"
            " WHERE i.trigger='discovery' AND i.dependency_name LIKE 'demo-%'"
            " ORDER BY e.created_at ASC, e.id ASC"
        )
    ).mappings().fetchall()
    out["events"] = [dict(r) for r in evs]
    acts = conn.execute(
        text(
            "SELECT a.investigation_id, a.success, a.skipped, a.skip_reason, a.issue_url,"
            " a.issue_number, a.verified, a.error FROM actions a"
            " JOIN investigations i ON i.id = a.investigation_id"
            " WHERE i.trigger='discovery' AND i.dependency_name LIKE 'demo-%'"
        )
    ).mappings().fetchall()
    out["actions"] = [dict(r) for r in acts]

print(json.dumps(out, indent=1, default=str))

server.terminate()
try:
    server.wait(timeout=10)
except Exception:
    server.kill()
db.remove_watchlist_entry("demo-alpha")
db.remove_watchlist_entry("demo-beta")
with db.engine.begin() as conn:
    conn.execute(
        text(
            "UPDATE investigations SET status='failed', error='demo watch window ended'"
            " WHERE trigger='discovery' AND dependency_name LIKE 'demo-%' AND status='running'"
        )
    )
print("server stopped; demo watchlist entries removed; evidence kept")
