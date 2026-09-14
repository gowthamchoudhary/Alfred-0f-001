-- Alfred schema — Postgres (Supabase).
-- This exact script is executed on startup by backend/alfred/db.py (idempotent:
-- IF NOT EXISTS everywhere, safe to re-run). A mirror of this schema for the
-- local SQLite fallback lives inline in db.py.
--
-- Credential model: GitHub tokens for auto-triggered investigations are
-- stored ONCE per watchlist entry as Fernet ciphertext (gh_token_enc, key from
-- ALFRED_ENCRYPTION_KEY) and are never returned by any API — read the comment
-- on watchlist. No plaintext token, GROQ_API_KEY, or ANAKIN_API_KEY is stored
-- anywhere; only results (issue URLs, verified flags, metrics, verdicts,
-- triage decisions) are stored.

CREATE TABLE IF NOT EXISTS investigations (
    id TEXT PRIMARY KEY,
    dependency_name TEXT NOT NULL,
    baseline_version TEXT NOT NULL,
    candidate_version TEXT NOT NULL,
    repo_source TEXT NOT NULL,
    trigger TEXT NOT NULL DEFAULT 'manual',       -- discovery | manual | system
    status TEXT NOT NULL DEFAULT 'pending',       -- pending|running|complete|failed
    current_step TEXT,
    verdict TEXT,
    confidence DOUBLE PRECISION,
    compatibility_score DOUBLE PRECISION,
    github_issue_url TEXT,
    error TEXT,
    created_at DOUBLE PRECISION NOT NULL,
    completed_at DOUBLE PRECISION,
    user_id TEXT                                  -- owning Alfred account (NULL = system/CLI run)
);

-- Migration for tables created before per-user scoping existed.
ALTER TABLE investigations ADD COLUMN IF NOT EXISTS user_id TEXT;
CREATE INDEX IF NOT EXISTS idx_investigations_user ON investigations (user_id, created_at);

CREATE TABLE IF NOT EXISTS agent_events (
    id BIGSERIAL PRIMARY KEY,
    investigation_id TEXT NOT NULL,
    step TEXT NOT NULL,
    message TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'info',
    created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_events_inv ON agent_events (investigation_id, created_at);

CREATE TABLE IF NOT EXISTS test_runs (
    id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL,
    environment TEXT NOT NULL,                    -- baseline | candidate
    container_name TEXT,
    build_success BOOLEAN NOT NULL DEFAULT TRUE,
    build_log TEXT,
    startup_success BOOLEAN NOT NULL DEFAULT TRUE,
    startup_log TEXT,
    tests_passed INTEGER,
    tests_failed INTEGER,
    tests_errors INTEGER,
    tests_total INTEGER,
    pytest_summary TEXT,
    workload_total_requests INTEGER,
    workload_successful_requests INTEGER,
    workload_error_rate DOUBLE PRECISION,
    latency_p50_ms DOUBLE PRECISION,
    latency_p95_ms DOUBLE PRECISION,
    latency_p99_ms DOUBLE PRECISION,
    throughput_rps DOUBLE PRECISION,
    raw_output TEXT,
    created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_test_runs_inv ON test_runs (investigation_id);

CREATE TABLE IF NOT EXISTS comparisons (
    id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL UNIQUE,
    payload TEXT NOT NULL,                        -- full compare object as JSON
    functional_score DOUBLE PRECISION,
    performance_score DOUBLE PRECISION,
    overall_score DOUBLE PRECISION,
    created_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL UNIQUE,
    verdict TEXT NOT NULL,
    confidence DOUBLE PRECISION,
    reasons TEXT NOT NULL,                        -- JSON array of strings
    recommendation TEXT,
    decided_by TEXT NOT NULL DEFAULT 'llm',       -- llm_groq | rule_based
    created_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS actions (
    id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL UNIQUE,
    action_type TEXT NOT NULL DEFAULT 'github_issue',
    success BOOLEAN NOT NULL DEFAULT FALSE,
    skipped BOOLEAN NOT NULL DEFAULT FALSE,       -- TRUE when the caller supplied no GitHub token
    skip_reason TEXT,
    issue_url TEXT,
    issue_number INTEGER,
    verified BOOLEAN NOT NULL DEFAULT FALSE,
    error TEXT,
    created_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS detected_changes (
    id TEXT PRIMARY KEY,
    dependency_name TEXT NOT NULL,
    source TEXT NOT NULL,                         -- pypi | github
    latest_version TEXT NOT NULL,
    release_notes TEXT,
    release_url TEXT,
    published_at TEXT,
    detected_at DOUBLE PRECISION NOT NULL,
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
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    last_checked_at DOUBLE PRECISION,
    last_seen_version TEXT,
    added_at DOUBLE PRECISION NOT NULL,
    -- One-time registration credential for unattended auto-investigations:
    -- the user's GitHub PAT for THIS dependency, encrypted at rest with
    -- Fernet (key: ALFRED_ENCRYPTION_KEY). Ciphertext only — the plaintext
    -- token never enters the database, any other table, or an API response.
    -- get_watchlist_credential() is the single reader; list_watchlist()
    -- projects these columns away so responses can never carry them.
    gh_token_enc TEXT,
    gh_owner TEXT,
    gh_repo TEXT,
    user_id TEXT                                  -- registering Alfred account, auto investigations inherit it
);

-- Migration for watchlist tables created before encrypted credentials existed.
ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS gh_token_enc TEXT;
ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS gh_owner TEXT;
ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS gh_repo TEXT;
ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS user_id TEXT;

-- Alfred accounts (email + password; no OAuth providers by design).
-- password_hash is a salted PBKDF2 hash — never a plaintext password, and
-- never a GitHub token (those stay per-request in memory).
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at DOUBLE PRECISION NOT NULL
);

-- Opaque session tokens. Only the SHA-256 hash of the token is stored, so a
-- database leak cannot be replayed as a login.
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at DOUBLE PRECISION NOT NULL,
    expires_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions (user_id);
