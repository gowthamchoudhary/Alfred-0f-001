"""SQLite persistence layer for Alfred.

Pure stdlib `sqlite3`. Every function opens a short-lived connection, so the
API layer stays simple and thread-safe (FastAPI may call from any thread).

Tables:
    investigations   one row per pipeline run (discovery-triggered or manual)
    agent_events     timestamped step log lines (feeds the dashboard timeline)
    test_runs        pytest summary per environment (baseline / candidate)
    comparisons      deterministic metric deltas + compatibility score
    decisions        verdict + reasons + recommendation (LLM or rule-based)
    actions          GitHub issue creation + verification result
    detected_changes every discovered release (investigated or skipped)
    watchlist        dependencies monitored by the discovery layer
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from typing import Any, Iterable

# SQLite connections are created per-call and writes are serialized behind a
# lock to avoid "database is locked" when the poller and API overlap.
_WRITE_LOCK = threading.Lock()

_SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS investigations (
    id TEXT PRIMARY KEY,
    dependency_name TEXT NOT NULL,
    baseline_version TEXT NOT NULL,
    candidate_version TEXT NOT NULL,
    repo_source TEXT NOT NULL,
    trigger TEXT NOT NULL DEFAULT 'manual',       -- discovery | manual
    status TEXT NOT NULL DEFAULT 'pending',       -- pending|running|complete|failed
    current_step TEXT,
    verdict TEXT,
    confidence REAL,
    compatibility_score REAL,
    github_issue_url TEXT,
    error TEXT,
    created_at REAL NOT NULL,
    completed_at REAL
);

CREATE TABLE IF NOT EXISTS agent_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    investigation_id TEXT NOT NULL,
    step TEXT NOT NULL,
    message TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'info',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_events_inv ON agent_events (investigation_id, created_at);

CREATE TABLE IF NOT EXISTS test_runs (
    id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL,
    environment TEXT NOT NULL,                    -- baseline | candidate
    container_name TEXT,
    build_success INTEGER NOT NULL DEFAULT 1,
    build_log TEXT,
    startup_success INTEGER NOT NULL DEFAULT 1,
    startup_log TEXT,
    tests_passed INTEGER,
    tests_failed INTEGER,
    tests_errors INTEGER,
    tests_total INTEGER,
    pytest_summary TEXT,
    workload_total_requests INTEGER,
    workload_successful_requests INTEGER,
    workload_error_rate REAL,
    latency_p50_ms REAL,
    latency_p95_ms REAL,
    latency_p99_ms REAL,
    throughput_rps REAL,
    raw_output TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_test_runs_inv ON test_runs (investigation_id);

CREATE TABLE IF NOT EXISTS comparisons (
    id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL UNIQUE,
    payload TEXT NOT NULL,                        -- full compare object as JSON
    functional_score REAL,
    performance_score REAL,
    overall_score REAL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL UNIQUE,
    verdict TEXT NOT NULL,
    confidence REAL,
    reasons TEXT NOT NULL,                        -- JSON array of strings
    recommendation TEXT,
    decided_by TEXT NOT NULL DEFAULT 'llm',       -- llm | rule_based
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS actions (
    id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL UNIQUE,
    action_type TEXT NOT NULL DEFAULT 'github_issue',
    success INTEGER NOT NULL DEFAULT 0,
    skipped INTEGER NOT NULL DEFAULT 0,           -- 1 when the caller supplied no GitHub token
    skip_reason TEXT,
    issue_url TEXT,
    issue_number INTEGER,
    verified INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS detected_changes (
    id TEXT PRIMARY KEY,
    dependency_name TEXT NOT NULL,
    source TEXT NOT NULL,                         -- pypi | github
    latest_version TEXT NOT NULL,
    release_notes TEXT,
    release_url TEXT,
    published_at TEXT,
    detected_at REAL NOT NULL,
    triage_status TEXT NOT NULL DEFAULT 'pending', -- pending|accepted|skipped
    triage_reason TEXT,
    triage_mode TEXT,                              -- deterministic | llm
    investigation_id TEXT,
    UNIQUE (dependency_name, latest_version)
);

CREATE TABLE IF NOT EXISTS watchlist (
    name TEXT PRIMARY KEY,
    source TEXT NOT NULL DEFAULT 'pypi',          -- pypi | github
    repo TEXT,                                    -- owner/repo when source=github
    enabled INTEGER NOT NULL DEFAULT 1,
    last_checked_at REAL,
    last_seen_version TEXT,
    added_at REAL NOT NULL
);
"""


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


class Database:
    """Thin repository over SQLite. All timestamps are unix epoch floats."""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or os.environ.get(
            "ALFRED_DB_PATH",
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "alfred.db"),
        )
        with _WRITE_LOCK:
            conn = _connect(self.db_path)
            try:
                conn.executescript(_SCHEMA)
                conn.commit()
            finally:
                conn.close()

    # ------------------------------------------------------------------ util
    def _new_id(self) -> str:
        return uuid.uuid4().hex[:16]

    @staticmethod
    def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return None if row is None else {key: row[key] for key in row.keys()}

    @staticmethod
    def _rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
        return [{key: row[key] for key in row.keys()} for row in rows]

    def log_event(
        self,
        investigation_id: str,
        step: str,
        message: str,
        level: str = "info",
    ) -> None:
        with _WRITE_LOCK:
            conn = _connect(self.db_path)
            try:
                conn.execute(
                    "INSERT INTO agent_events (investigation_id, step, message, level, created_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (investigation_id, step, message, level, time.time()),
                )
                conn.commit()
            finally:
                conn.close()

    def list_events(self, investigation_id: str) -> list[dict[str, Any]]:
        conn = _connect(self.db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM agent_events WHERE investigation_id = ? ORDER BY id ASC",
                (investigation_id,),
            ).fetchall()
            return self._rows_to_dicts(rows)
        finally:
            conn.close()

    # --------------------------------------------------------- investigations
    def create_investigation(
        self,
        dependency_name: str,
        baseline_version: str,
        candidate_version: str,
        repo_source: str,
        trigger: str = "manual",
    ) -> str:
        inv_id = self._new_id()
        with _WRITE_LOCK:
            conn = _connect(self.db_path)
            try:
                conn.execute(
                    "INSERT INTO investigations"
                    " (id, dependency_name, baseline_version, candidate_version, repo_source,"
                    "  trigger, status, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, 'running', ?)",
                    (
                        inv_id,
                        dependency_name,
                        baseline_version,
                        candidate_version,
                        repo_source,
                        trigger,
                        time.time(),
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        return inv_id

    def update_investigation(self, inv_id: str, **fields: Any) -> None:
        if not fields:
            return
        allowed = {
            "status",
            "current_step",
            "verdict",
            "confidence",
            "compatibility_score",
            "github_issue_url",
            "error",
            "completed_at",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [inv_id]
        with _WRITE_LOCK:
            conn = _connect(self.db_path)
            try:
                conn.execute(
                    f"UPDATE investigations SET {set_clause} WHERE id = ?", values
                )
                conn.commit()
            finally:
                conn.close()

    def get_investigation(self, inv_id: str) -> dict[str, Any] | None:
        conn = _connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM investigations WHERE id = ?", (inv_id,)
            ).fetchone()
            return self._row_to_dict(row)
        finally:
            conn.close()

    def list_investigations(self, limit: int = 50) -> list[dict[str, Any]]:
        conn = _connect(self.db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM investigations ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return self._rows_to_dicts(rows)
        finally:
            conn.close()

    # -------------------------------------------------------------- test_runs
    def save_test_run(self, investigation_id: str, environment: str, data: dict[str, Any]) -> str:
        run_id = self._new_id()
        with _WRITE_LOCK:
            conn = _connect(self.db_path)
            try:
                conn.execute(
                    "INSERT INTO test_runs ("
                    " id, investigation_id, environment, container_name,"
                    " build_success, build_log, startup_success, startup_log,"
                    " tests_passed, tests_failed, tests_errors, tests_total, pytest_summary,"
                    " workload_total_requests, workload_successful_requests, workload_error_rate,"
                    " latency_p50_ms, latency_p95_ms, latency_p99_ms, throughput_rps,"
                    " raw_output, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        investigation_id,
                        environment,
                        data.get("container_name"),
                        1 if data.get("build_success") else 0,
                        data.get("build_log"),
                        1 if data.get("startup_success") else 0,
                        data.get("startup_log"),
                        data.get("tests_passed"),
                        data.get("tests_failed"),
                        data.get("tests_errors"),
                        data.get("tests_total"),
                        data.get("pytest_summary"),
                        data.get("total_requests"),
                        data.get("successful_requests"),
                        data.get("error_rate"),
                        data.get("latency_p50_ms"),
                        data.get("latency_p95_ms"),
                        data.get("latency_p99_ms"),
                        data.get("throughput_rps"),
                        data.get("raw_output"),
                        time.time(),
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        return run_id

    def list_test_runs(self, investigation_id: str) -> list[dict[str, Any]]:
        conn = _connect(self.db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM test_runs WHERE investigation_id = ? ORDER BY created_at ASC",
                (investigation_id,),
            ).fetchall()
            return self._rows_to_dicts(rows)
        finally:
            conn.close()

    # ------------------------------------------------------------ comparisons
    def save_comparison(self, investigation_id: str, comparison: dict[str, Any]) -> None:
        with _WRITE_LOCK:
            conn = _connect(self.db_path)
            try:
                scores = comparison.get("scores") or {}
                conn.execute(
                    "INSERT OR REPLACE INTO comparisons"
                    " (id, investigation_id, payload, functional_score, performance_score,"
                    "  overall_score, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        self._new_id(),
                        investigation_id,
                        json.dumps(comparison),
                        scores.get("functional_score"),
                        scores.get("performance_score"),
                        scores.get("overall_score"),
                        time.time(),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def get_comparison(self, investigation_id: str) -> dict[str, Any] | None:
        conn = _connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT payload FROM comparisons WHERE investigation_id = ?",
                (investigation_id,),
            ).fetchone()
            return json.loads(row["payload"]) if row else None
        finally:
            conn.close()

    # -------------------------------------------------------------- decisions
    def save_decision(
        self,
        investigation_id: str,
        verdict: str,
        confidence: float,
        reasons: list[str],
        recommendation: str,
        decided_by: str,
    ) -> None:
        with _WRITE_LOCK:
            conn = _connect(self.db_path)
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO decisions"
                    " (id, investigation_id, verdict, confidence, reasons, recommendation,"
                    "  decided_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        self._new_id(),
                        investigation_id,
                        verdict,
                        confidence,
                        json.dumps(reasons),
                        recommendation,
                        decided_by,
                        time.time(),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def get_decision(self, investigation_id: str) -> dict[str, Any] | None:
        conn = _connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM decisions WHERE investigation_id = ?", (investigation_id,)
            ).fetchone()
            if row is None:
                return None
            data = self._row_to_dict(row)
            data["reasons"] = json.loads(data["reasons"])
            return data
        finally:
            conn.close()

    # ---------------------------------------------------------------- actions
    def save_action(self, investigation_id: str, data: dict[str, Any]) -> None:
        with _WRITE_LOCK:
            conn = _connect(self.db_path)
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO actions"
                    " (id, investigation_id, action_type, success, skipped, skip_reason,"
                    "  issue_url, issue_number, verified, error, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        self._new_id(),
                        investigation_id,
                        data.get("action_type", "github_issue"),
                        1 if data.get("success") else 0,
                        1 if data.get("skipped") else 0,
                        data.get("skip_reason"),
                        data.get("issue_url"),
                        data.get("issue_number"),
                        1 if data.get("verified") else 0,
                        data.get("error"),
                        time.time(),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def get_action(self, investigation_id: str) -> dict[str, Any] | None:
        conn = _connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM actions WHERE investigation_id = ?", (investigation_id,)
            ).fetchone()
            return self._row_to_dict(row)
        finally:
            conn.close()

    # ------------------------------------------------------- detected_changes
    def upsert_detected_change(self, change: dict[str, Any]) -> dict[str, Any] | None:
        """Insert a detected release. Returns the stored row, or None if known."""
        with _WRITE_LOCK:
            conn = _connect(self.db_path)
            try:
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO detected_changes"
                    " (id, dependency_name, source, latest_version, release_notes, release_url,"
                    "  published_at, detected_at, triage_status)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        self._new_id(),
                        change["dependency_name"],
                        change["source"],
                        change["latest_version"],
                        change.get("release_notes"),
                        change.get("release_url"),
                        change.get("published_at"),
                        time.time(),
                        "pending",
                    ),
                )
                conn.commit()
                if cursor.rowcount <= 0:
                    return None
                row = conn.execute(
                    "SELECT * FROM detected_changes WHERE dependency_name = ? AND latest_version = ?",
                    (change["dependency_name"], change["latest_version"]),
                ).fetchone()
                return self._row_to_dict(row)
            finally:
                conn.close()

    def list_detected_changes(
        self,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        conn = _connect(self.db_path)
        try:
            if status:
                rows = conn.execute(
                    "SELECT * FROM detected_changes WHERE triage_status = ?"
                    " ORDER BY detected_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM detected_changes ORDER BY detected_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return self._rows_to_dicts(rows)
        finally:
            conn.close()

    def get_pending_change(self, change_id: str) -> dict[str, Any] | None:
        conn = _connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM detected_changes WHERE id = ?", (change_id,)
            ).fetchone()
            return self._row_to_dict(row)
        finally:
            conn.close()

    def mark_change_triaged(
        self,
        change_id: str,
        status: str,
        reason: str,
        mode: str,
        investigation_id: str | None = None,
    ) -> None:
        with _WRITE_LOCK:
            conn = _connect(self.db_path)
            try:
                conn.execute(
                    "UPDATE detected_changes SET triage_status = ?, triage_reason = ?,"
                    " triage_mode = ?, investigation_id = ? WHERE id = ?",
                    (status, reason, mode, investigation_id, change_id),
                )
                conn.commit()
            finally:
                conn.close()

    # -------------------------------------------------------------- watchlist
    def add_watchlist_entry(self, name: str, source: str = "pypi", repo: str | None = None) -> None:
        with _WRITE_LOCK:
            conn = _connect(self.db_path)
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO watchlist (name, source, repo, enabled, added_at)"
                    " VALUES (?, ?, ?, 1, ?)",
                    (name, source, repo, time.time()),
                )
                conn.commit()
            finally:
                conn.close()

    def remove_watchlist_entry(self, name: str) -> None:
        with _WRITE_LOCK:
            conn = _connect(self.db_path)
            try:
                conn.execute("DELETE FROM watchlist WHERE name = ?", (name,))
                conn.commit()
            finally:
                conn.close()

    def list_watchlist(self) -> list[dict[str, Any]]:
        conn = _connect(self.db_path)
        try:
            rows = conn.execute("SELECT * FROM watchlist ORDER BY name ASC").fetchall()
            return self._rows_to_dicts(rows)
        finally:
            conn.close()

    def update_watchlist_status(
        self, name: str, last_seen_version: str | None = None
    ) -> None:
        with _WRITE_LOCK:
            conn = _connect(self.db_path)
            try:
                conn.execute(
                    "UPDATE watchlist SET last_checked_at = ?,"
                    " last_seen_version = COALESCE(?, last_seen_version) WHERE name = ?",
                    (time.time(), last_seen_version, name),
                )
                conn.commit()
            finally:
                conn.close()
