"""TEMP demo seeding — inserts two detected_changes rows EXACTLY as the real
discovery poller would write them (same shape, same upsert call), for TWO
different dependencies, each backed by its own registered watchlist entry with
its own encrypted token. After this script exits, NO further action is taken
by anyone — the running server's poller must pick these up on its next tick,
triage them, and auto-invoke both pipelines using the stored credentials.

Delete after the demo.
"""

from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

for line in Path(__file__).resolve().parents[1].joinpath(".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

os.environ.setdefault("ALFRED_ENCRYPTION_KEY", "aDHmsp9IvGfKZubuI13Zz0F2lEcEMsCscn_YBmO5cSY=")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from alfred.crypto import encrypt_secret  # noqa: E402
from alfred.db import Database  # noqa: E402

db = Database()

# Two DIFFERENT dependencies, registered independently, each with its own
# (demo) token + issue destination. user_id omitted: no Alfred signup in this
# sandboxed demo, so auto runs attribute to system (user_id NULL).
db.add_watchlist_entry(
    "demo-alpha", "github", "owner/demo-alpha",
    gh_token_enc=encrypt_secret("ghp_DEMO_TOKEN_ALPHA_4f2a"),
    gh_owner="owner", gh_repo="demo-alpha",
)
db.add_watchlist_entry(
    "demo-beta", "github", "owner/demo-beta",
    gh_token_enc=encrypt_secret("ghp_DEMO_TOKEN_BETA_9c71"),
    gh_owner="owner", gh_repo="demo-beta",
)

# Rows written EXACTLY like discovery.poll_once writes them (upsert_detected_change).
c1 = db.upsert_detected_change(
    {
        "dependency_name": "demo-alpha",
        "source": "github",
        "latest_version": "3.0.0",  # major bump -> deterministic triage accepts
        "release_notes": "Major release with breaking changes",
        "release_url": "https://github.com/owner/demo-alpha/releases/tag/v3.0.0",
        "published_at": "2026-09-14T00:00:00Z",
    }
)
c2 = db.upsert_detected_change(
    {
        "dependency_name": "demo-beta",
        "source": "github",
        "latest_version": "2.0.0",  # major bump -> deterministic triage accepts
        "release_notes": "Major version bump",
        "release_url": "https://github.com/owner/demo-beta/releases/tag/v2.0.0",
        "published_at": "2026-09-14T00:00:00Z",
    }
)
print(f"seeded: alpha={c1['id'] if c1 else 'dup!'} beta={c2['id'] if c2 else 'dup!'}")
