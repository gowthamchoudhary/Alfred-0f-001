"""TEMP demo server — the real `alfred.cli serve` startup path, unmodified.

Runs uvicorn("alfred.app:app"), whose lifespan calls start_poller(db) — the
exact code path production uses. Demo-only env (key/repo-target/interval) is
set here so the unattended loop can run in this sandbox; deleted after.
"""

from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

# Load project .env (presence only — values never printed)
for line in Path(__file__).resolve().parents[1].joinpath(".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

# Demo-only configuration for THIS unattended proof run (not committed anywhere):
# a demo encryption key, a poll interval of 15s so the background loop visibly
# ticks, and the sample repo as the auto-investigation target.
os.environ.setdefault("ALFRED_ENCRYPTION_KEY", "aDHmsp9IvGfKZubuI13Zz0F2lEcEMsCscn_YBmO5cSY=")
os.environ.setdefault("ALFRED_REPO_TARGET", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "examples", "sample-repo"))
os.environ.setdefault("ALFRED_POLL_INTERVAL", "15")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run(
        "alfred.app:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8123")),
        reload=False,
        log_level="warning",
    )
