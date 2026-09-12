"""Persistence layer for Alfred — Supabase (hosted Postgres) via SQLAlchemy.

Every function shares one small engine pool, so the API layer stays simple and
thread-safe (FastAPI may call from any thread; SQLAlchemy serializes access).

Backend selection (in order):
    1. ``SUPABASE_DB_URL`` or ``DATABASE_URL`` — a Postgres connection string
       (Supabase dashboard → Project Settings → Database → Connection string).
       This is the production path: data lives in Supabase, outside the
       ephemeral sandbox, so investigation history survives workspace resets.
    2. ``sqlite:///{ALFRED_DB_PATH}`` — local fallback so dev and the unit
       tests keep working with zero credentials. When this fallback is active
       a single warning is logged at startup; the fallback is intentionally
       last-resort, not a supported deployment posture.

The Postgres schema lives in ``backend/db/schema.sql`` and is applied
idempotently on startup. The SQLite fallback keeps a functionally identical
schema inline below.

Tables (identical columns on both backends):
    investigations   one row per pipeline run (discovery-triggered or manual)
    agent_events     timestamped step log lines (feeds the dashboard timeline)
    test_runs        pytest summary per environment (baseline / candidate)
    comparisons      deterministic metric deltas + compatibility score
    decisions        verdict + reasons + recommendation (LLM or rule-based)
    actions          GitHub issue creation + verification result
    detected_changes every discovered release (investigated or skipped)
    watchlist        dependencies monitored by the discovery layer

Credential safety by construction: there is deliberately NO column anywhere in
this schema for GitHub tokens, GROQ_API_KEY, or EXA_API_KEY. GitHub tokens are
per-request and used in-memory only (see github_action.py); only results —
issue URLs, verified flags, metrics, verdicts, triage decisions — are stored.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
import warnings
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

_SCHEMA_SQL_PATH = Path(__file__).resolve().parents[1] / "db" / "schema.sql"

_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS investigations (
    id TEXT PRIMARY KEY,
    dependency_name TEXT NOT NULL,
    baseline_version TEXT NOT NULL,
    candidate_version TEXT NOT NULL,
    repo_source TEXT NOT NULL,
    trigger TEXT NOT NULL DEFAULT 'manual',
    status TEXT NOT NULL DEFAULT 'pending',
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
    environment TEXT NOT NULL,
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
    payload TEXT NOT NULL,
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
    reasons TEXT NOT NULL,
    recommendation TEXT,
    decided_by TEXT NOT NULL DEFAULT 'llm',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS actions (
    id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL UNIQUE,
    action_type TEXT NOT NULL DEFAULT 'github_issue',
    success INTEGER NOT NULL DEFAULT 0,
    skipped INTEGER NOT NULL DEFAULT 0,
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
    source TEXT NOT NULL,
    latest_version TEXT NOT NULL,
    release_notes TEXT,
    release_url TEXT,
    published_at TEXT,
    detected_at REAL NOT NULL,
    triage_status TEXT NOT NULL DEFAULT 'pending',
    triage_reason TEXT,
    triage_mode TEXT,
    investigation_id TEXT,
    UNIQUE (dependency_name, latest_version)
);
CREATE TABLE IF NOT EXISTS watchlist (
    name TEXT PRIMARY KEY,
    source TEXT NOT NULL DEFAULT 'pypi',
    repo TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_checked_at REAL,
    last_seen_version TEXT,
    added_at REAL NOT NULL
);
"""


_FALLBACK_WARNED = False


def _apply_schema(conn: Any, sql: str) -> None:
    """Execute a multi-statement schema script one statement at a time.

    Works on both drivers: sqlite3's ``execute`` refuses multi-statement
    strings, and splitting lets comment lines ride along safely on both.
    """
    for stmt in sql.split(";"):
        cleaned = "\n".join(
            ln for ln in stmt.splitlines() if not ln.strip().startswith("--")
        ).strip()
        if cleaned:
            conn.execute(text(cleaned))


def _resolve_database_url() -> tuple[str, bool]:
    """Return (sqlalchemy_url, is_postgres). Supabase wins when configured."""
    url = os.environ.get("SUPABASE_DB_URL") or os.environ.get("DATABASE_URL")
    if url:
        if url.startswith("postgres"):
            return url, True
        return url, False  # explicit non-postgres URL — honor it
    sqlite_path = os.environ.get(
        "ALFRED_DB_PATH",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "alfred.db"),
    )
    return f"sqlite:///{sqlite_path}", False


_ENGINES: dict[str, Engine] = {}
_ENGINE_LOCK = threading.Lock()


def _engine_for(url: str, is_postgres: bool) -> Engine:
    with _ENGINE_LOCK:
        engine = _ENGINES.get(url)
        if engine is not None:
            return engine
        kwargs: dict[str, Any] = {"pool_pre_ping": True, "future": True}
        if is_postgres:
            kwargs["pool_size"] = 5
            kwargs["max_overflow"] = 5
        else:
            kwargs["connect_args"] = {"check_same_thread": False}
        engine = create_engine(url, **kwargs)
        _ENGINES[url] = engine
        return engine


# Writes were serialized behind a lock for SQLite; harmless under Postgres MVCC,
# kept so both backends share one code path.
_WRITE_LOCK = threading.Lock()


class Database:
    """Thin repository over Supabase Postgres (SQLAlchemy) with a local
    SQLite fallback. All timestamps are unix epoch floats."""

    def __init__(self, db_path: str | None = None) -> None:
        if db_path:  # explicit path arg (tests) forces the local backend
            self.url = f"sqlite:///{db_path}"
            self.is_postgres = False
        else:
            self.url, self.is_postgres = _resolve_database_url()
        self.engine = _engine_for(self.url, self.is_postgres)
        schema_sql = _SCHEMA_SQL_PATH.read_text(encoding="utf-8") if self.is_postgres else _SQLITE_SCHEMA
        with _WRITE_LOCK:
            with self.engine.begin() as conn:
                _apply_schema(conn, schema_sql)
        global _FALLBACK_WARNED
        if not self.is_postgres and db_path is None and not _FALLBACK_WARNED:
            _FALLBACK_WARNED = True
            warnings.warn(
                "SUPABASE_DB_URL not set — falling back to local SQLite "
                f"({self.url}). Investigation history will NOT survive a "
                "workspace reset; set SUPABASE_DB_URL to persist to Supabase.",
                stacklevel=2,
            )

    # ------------------------------------------------------------------ util
    def _new_id(self) -> str:
        return uuid.uuid4().hex[:16]

    @staticmethod
    def _row_to_dict(row: Any | None) -> dict[str, Any] | None:
        return None if row is None else dict(row)

    @staticmethod
    def _rows_to_dicts(rows: Iterable[Any]) -> list[dict[str, Any]]:
        return [dict(r) for r in rows]

    @staticmethod
    def _as_bool(value: Any) -> bool:
        return bool(value)

    def log_event(
        self,
        investigation_id: str,
        step: str,
        message: str,
        level: str = "info",
    ) -> None:
        with _WRITE_LOCK:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO agent_events (investigation_id, step, message, level, created_at)"
                        " VALUES (:inv, :step, :message, :level, :created_at)"
                    ),
                    {
                        "inv": investigation_id,
                        "step": step,
                        "message": message,
                        "level": level,
                        "created_at": time.time(),
                    },
                )

    def list_events(self, investigation_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT * FROM agent_events WHERE investigation_id = :inv ORDER BY id ASC"
                ),
                {"inv": investigation_id},
            ).mappings().fetchall()
            return self._rows_to_dicts(rows)

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
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO investigations"
                        " (id, dependency_name, baseline_version, candidate_version, repo_source,"
                        "  trigger, status, created_at)"
                        " VALUES (:id, :dep, :base, :cand, :repo, :trigger, 'running', :created_at)"
                    ),
                    {
                        "id": inv_id,
                        "dep": dependency_name,
                        "base": baseline_version,
                        "cand": candidate_version,
                        "repo": repo_source,
                        "trigger": trigger,
                        "created_at": time.time(),
                    },
                )
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
        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        params = dict(updates)
        params["inv"] = inv_id
        with _WRITE_LOCK:
            with self.engine.begin() as conn:
                conn.execute(
                    text(f"UPDATE investigations SET {set_clause} WHERE id = :inv"),
                    params,
                )

    def get_investigation(self, inv_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM investigations WHERE id = :inv"), {"inv": inv_id}
            ).mappings().fetchone()
            return self._row_to_dict(row)

    def list_investigations(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT * FROM investigations ORDER BY created_at DESC LIMIT :limit"
                ),
                {"limit": limit},
            ).mappings().fetchall()
            return self._rows_to_dicts(rows)

    # -------------------------------------------------------------- test_runs
    def save_test_run(self, investigation_id: str, environment: str, data: dict[str, Any]) -> str:
        run_id = self._new_id()
        with _WRITE_LOCK:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO test_runs ("
                        " id, investigation_id, environment, container_name,"
                        " build_success, build_log, startup_success, startup_log,"
                        " tests_passed, tests_failed, tests_errors, tests_total, pytest_summary,"
                        " workload_total_requests, workload_successful_requests, workload_error_rate,"
                        " latency_p50_ms, latency_p95_ms, latency_p99_ms, throughput_rps,"
                        " raw_output, created_at)"
                        " VALUES (:id, :inv, :env, :container,"
                        " :build_success, :build_log, :startup_success, :startup_log,"
                        " :tests_passed, :tests_failed, :tests_errors, :tests_total, :pytest_summary,"
                        " :total_requests, :successful_requests, :error_rate,"
                        " :latency_p50_ms, :latency_p95_ms, :latency_p99_ms, :throughput_rps,"
                        " :raw_output, :created_at)"
                    ),
                    {
                        "id": run_id,
                        "inv": investigation_id,
                        "env": environment,
                        "container": data.get("container_name"),
                        "build_success": self._as_bool(data.get("build_success")),
                        "build_log": data.get("build_log"),
                        "startup_success": self._as_bool(data.get("startup_success")),
                        "startup_log": data.get("startup_log"),
                        "tests_passed": data.get("tests_passed"),
                        "tests_failed": data.get("tests_failed"),
                        "tests_errors": data.get("tests_errors"),
                        "tests_total": data.get("tests_total"),
                        "pytest_summary": data.get("pytest_summary"),
                        "total_requests": data.get("total_requests"),
                        "successful_requests": data.get("successful_requests"),
                        "error_rate": data.get("error_rate"),
                        "latency_p50_ms": data.get("latency_p50_ms"),
                        "latency_p95_ms": data.get("latency_p95_ms"),
                        "latency_p99_ms": data.get("latency_p99_ms"),
                        "throughput_rps": data.get("throughput_rps"),
                        "raw_output": data.get("raw_output"),
                        "created_at": time.time(),
                    },
                )
        return run_id

    def list_test_runs(self, investigation_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT * FROM test_runs WHERE investigation_id = :inv"
                    " ORDER BY created_at ASC"
                ),
                {"inv": investigation_id},
            ).mappings().fetchall()
            return self._rows_to_dicts(rows)

    # ------------------------------------------------------------ comparisons
    def save_comparison(self, investigation_id: str, comparison: dict[str, Any]) -> None:
        scores = comparison.get("scores") or {}
        with _WRITE_LOCK:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO comparisons"
                        " (id, investigation_id, payload, functional_score, performance_score,"
                        "  overall_score, created_at) VALUES (:id, :inv, :payload, :fs, :ps, :os, :created_at)"
                        " ON CONFLICT (investigation_id) DO UPDATE SET"
                        " payload = EXCLUDED.payload, functional_score = EXCLUDED.functional_score,"
                        " performance_score = EXCLUDED.performance_score,"
                        " overall_score = EXCLUDED.overall_score, created_at = EXCLUDED.created_at"
                    )
                    if self.is_postgres
                    else text(
                        "INSERT OR REPLACE INTO comparisons"
                        " (id, investigation_id, payload, functional_score, performance_score,"
                        "  overall_score, created_at) VALUES (:id, :inv, :payload, :fs, :ps, :os, :created_at)"
                    ),
                    {
                        "id": self._new_id(),
                        "inv": investigation_id,
                        "payload": json.dumps(comparison),
                        "fs": scores.get("functional_score"),
                        "ps": scores.get("performance_score"),
                        "os": scores.get("overall_score"),
                        "created_at": time.time(),
                    },
                )

    def get_comparison(self, investigation_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT payload FROM comparisons WHERE investigation_id = :inv"),
                {"inv": investigation_id},
            ).fetchone()
            return json.loads(row[0]) if row else None

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
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO decisions"
                        " (id, investigation_id, verdict, confidence, reasons, recommendation,"
                        "  decided_by, created_at) VALUES (:id, :inv, :verdict, :confidence,"
                        "  :reasons, :recommendation, :decided_by, :created_at)"
                        " ON CONFLICT (investigation_id) DO UPDATE SET"
                        " verdict = EXCLUDED.verdict, confidence = EXCLUDED.confidence,"
                        " reasons = EXCLUDED.reasons, recommendation = EXCLUDED.recommendation,"
                        " decided_by = EXCLUDED.decided_by, created_at = EXCLUDED.created_at"
                    )
                    if self.is_postgres
                    else text(
                        "INSERT OR REPLACE INTO decisions"
                        " (id, investigation_id, verdict, confidence, reasons, recommendation,"
                        "  decided_by, created_at) VALUES (:id, :inv, :verdict, :confidence,"
                        "  :reasons, :recommendation, :decided_by, :created_at)"
                    ),
                    {
                        "id": self._new_id(),
                        "inv": investigation_id,
                        "verdict": verdict,
                        "confidence": confidence,
                        "reasons": json.dumps(reasons),
                        "recommendation": recommendation,
                        "decided_by": decided_by,
                        "created_at": time.time(),
                    },
                )

    def get_decision(self, investigation_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM decisions WHERE investigation_id = :inv"),
                {"inv": investigation_id},
            ).mappings().fetchone()
            if row is None:
                return None
            data = self._row_to_dict(row)
            data["reasons"] = json.loads(data["reasons"])
            return data

    # ---------------------------------------------------------------- actions
    def save_action(self, investigation_id: str, data: dict[str, Any]) -> None:
        with _WRITE_LOCK:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO actions"
                        " (id, investigation_id, action_type, success, skipped, skip_reason,"
                        "  issue_url, issue_number, verified, error, created_at)"
                        " VALUES (:id, :inv, :action_type, :success, :skipped, :skip_reason,"
                        "  :issue_url, :issue_number, :verified, :error, :created_at)"
                        " ON CONFLICT (investigation_id) DO UPDATE SET"
                        " action_type = EXCLUDED.action_type, success = EXCLUDED.success,"
                        " skipped = EXCLUDED.skipped, skip_reason = EXCLUDED.skip_reason,"
                        " issue_url = EXCLUDED.issue_url, issue_number = EXCLUDED.issue_number,"
                        " verified = EXCLUDED.verified, error = EXCLUDED.error,"
                        " created_at = EXCLUDED.created_at"
                    )
                    if self.is_postgres
                    else text(
                        "INSERT OR REPLACE INTO actions"
                        " (id, investigation_id, action_type, success, skipped, skip_reason,"
                        "  issue_url, issue_number, verified, error, created_at)"
                        " VALUES (:id, :inv, :action_type, :success, :skipped, :skip_reason,"
                        "  :issue_url, :issue_number, :verified, :error, :created_at)"
                    ),
                    {
                        "id": self._new_id(),
                        "inv": investigation_id,
                        "action_type": data.get("action_type", "github_issue"),
                        "success": self._as_bool(data.get("success")),
                        "skipped": self._as_bool(data.get("skipped")),
                        "skip_reason": data.get("skip_reason"),
                        "issue_url": data.get("issue_url"),
                        "issue_number": data.get("issue_number"),
                        "verified": self._as_bool(data.get("verified")),
                        "error": data.get("error"),
                        "created_at": time.time(),
                    },
                )

    def get_action(self, investigation_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM actions WHERE investigation_id = :inv"),
                {"inv": investigation_id},
            ).mappings().fetchone()
            return self._row_to_dict(row)

    # ------------------------------------------------------- detected_changes
    def upsert_detected_change(self, change: dict[str, Any]) -> dict[str, Any] | None:
        """Insert a detected release. Returns the stored row, or None if known."""
        with _WRITE_LOCK:
            with self.engine.begin() as conn:
                result = conn.execute(
                    text(
                        "INSERT INTO detected_changes"
                        " (id, dependency_name, source, latest_version, release_notes, release_url,"
                        "  published_at, detected_at, triage_status)"
                        " VALUES (:id, :dep, :source, :version, :notes, :url, :published,"
                        "  :detected, 'pending')"
                        " ON CONFLICT (dependency_name, latest_version) DO NOTHING"
                    )
                    if self.is_postgres
                    else text(
                        "INSERT OR IGNORE INTO detected_changes"
                        " (id, dependency_name, source, latest_version, release_notes, release_url,"
                        "  published_at, detected_at, triage_status)"
                        " VALUES (:id, :dep, :source, :version, :notes, :url, :published, :detected, 'pending')"
                    ),
                    {
                        "id": self._new_id(),
                        "dep": change["dependency_name"],
                        "source": change["source"],
                        "version": change["latest_version"],
                        "notes": change.get("release_notes"),
                        "url": change.get("release_url"),
                        "published": change.get("published_at"),
                        "detected": time.time(),
                    },
                )
                if result.rowcount <= 0:
                    return None
                row = conn.execute(
                    text(
                        "SELECT * FROM detected_changes"
                        " WHERE dependency_name = :dep AND latest_version = :version"
                    ),
                    {"dep": change["dependency_name"], "version": change["latest_version"]},
                ).mappings().fetchone()
                return self._row_to_dict(row)

    def list_detected_changes(
        self,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            if status:
                rows = conn.execute(
                    text(
                        "SELECT * FROM detected_changes WHERE triage_status = :status"
                        " ORDER BY detected_at DESC LIMIT :limit"
                    ),
                    {"status": status, "limit": limit},
                ).mappings().fetchall()
            else:
                rows = conn.execute(
                    text(
                        "SELECT * FROM detected_changes ORDER BY detected_at DESC LIMIT :limit"
                    ),
                    {"limit": limit},
                ).mappings().fetchall()
            return self._rows_to_dicts(rows)

    def get_pending_change(self, change_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM detected_changes WHERE id = :id"), {"id": change_id}
            ).mappings().fetchone()
            return self._row_to_dict(row)

    def mark_change_triaged(
        self,
        change_id: str,
        status: str,
        reason: str,
        mode: str,
        investigation_id: str | None = None,
    ) -> None:
        with _WRITE_LOCK:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE detected_changes SET triage_status = :status,"
                        " triage_reason = :reason, triage_mode = :mode,"
                        " investigation_id = :inv WHERE id = :id"
                    ),
                    {
                        "status": status,
                        "reason": reason,
                        "mode": mode,
                        "inv": investigation_id,
                        "id": change_id,
                    },
                )

    # -------------------------------------------------------------- watchlist
    def add_watchlist_entry(self, name: str, source: str = "pypi", repo: str | None = None) -> None:
        with _WRITE_LOCK:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO watchlist (name, source, repo, enabled, added_at)"
                        " VALUES (:name, :source, :repo, TRUE, :added_at)"
                        " ON CONFLICT (name) DO NOTHING"
                    )
                    if self.is_postgres
                    else text(
                        "INSERT OR IGNORE INTO watchlist (name, source, repo, enabled, added_at)"
                        " VALUES (:name, :source, :repo, 1, :added_at)"
                    ),
                    {"name": name, "source": source, "repo": repo, "added_at": time.time()},
                )

    def remove_watchlist_entry(self, name: str) -> None:
        with _WRITE_LOCK:
            with self.engine.begin() as conn:
                conn.execute(text("DELETE FROM watchlist WHERE name = :name"), {"name": name})

    def list_watchlist(self) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text("SELECT * FROM watchlist ORDER BY name ASC")
            ).mappings().fetchall()
            return self._rows_to_dicts(rows)

    def update_watchlist_status(
        self, name: str, last_seen_version: str | None = None
    ) -> None:
        with _WRITE_LOCK:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE watchlist SET last_checked_at = :checked,"
                        " last_seen_version = COALESCE(:version, last_seen_version) WHERE name = :name"
                    ),
                    {"checked": time.time(), "version": last_seen_version, "name": name},
                )
