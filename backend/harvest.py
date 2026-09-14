"""TEMP: harvest demo evidence already persisted in Supabase. Delete after."""

from __future__ import annotations

import json
import os
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sqlalchemy import text  # noqa: E402
from alfred.db import Database  # noqa: E402

db = Database()
out: dict = {}
with db.engine.connect() as conn:
    invs = conn.execute(
        text(
            "SELECT id, dependency_name, candidate_version, trigger, status, current_step,"
            " verdict, compatibility_score, github_issue_url, error, created_at"
            " FROM investigations WHERE trigger='discovery' AND dependency_name LIKE 'demo-%'"
            " ORDER BY created_at ASC"
        )
    ).mappings().fetchall()
    out["auto_investigations"] = [dict(r) for r in invs]
    ids = [r["id"] for r in invs]
    evs = conn.execute(
        text(
            "SELECT e.investigation_id, e.step, e.message, e.level, e.created_at"
            " FROM agent_events e"
            " WHERE e.investigation_id = ANY(:ids)"
            " ORDER BY e.created_at ASC, e.id ASC"
        ),
        {"ids": ids},
    ).mappings().fetchall()
    out["events"] = [dict(r) for r in evs]
    acts = conn.execute(
        text(
            "SELECT a.investigation_id, a.success, a.skipped, a.skip_reason, a.issue_url,"
            " a.issue_number, a.verified, a.error"
            " FROM actions a WHERE a.investigation_id = ANY(:ids)"
        ),
        {"ids": ids},
    ).mappings().fetchall()
    out["actions"] = [dict(r) for r in acts]

print(json.dumps(out, indent=1, default=str))
