export type Verdict =
  | "SAFE"
  | "SAFE_WITH_REVIEW"
  | "MODERATE_RISK"
  | "HIGH_RISK"
  | "INCOMPATIBLE";

export interface Investigation {
  id: string;
  dependency_name: string;
  baseline_version: string;
  candidate_version: string;
  repo_source: string;
  trigger: string;
  status: string;
  current_step: string | null;
  verdict: string | null;
  confidence: number | null;
  compatibility_score: number | null;
  github_issue_url: string | null;
  error: string | null;
  created_at: number;
  completed_at: number | null;
  user_id?: string | null;
}

export interface AgentEvent {
  id: number;
  investigation_id: string;
  step: string;
  message: string;
  level: string;
  created_at: number;
}

export interface TestRun {
  environment: string;
  container_name: string | null;
  build_success: boolean;
  startup_success: boolean;
  tests_passed: number | null;
  tests_failed: number | null;
  tests_errors: number | null;
  tests_total: number | null;
  pytest_summary: string | null;
  workload_total_requests: number | null;
  workload_successful_requests: number | null;
  workload_error_rate: number | null;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
  latency_p99_ms: number | null;
  throughput_rps: number | null;
}

export interface MetricDelta {
  baseline: number;
  candidate: number;
  absolute_delta: number;
  percentage_delta: number | null;
}

export interface Comparison {
  metrics: Record<string, MetricDelta>;
  environment_health: Record<
    string,
    { build_success: boolean; startup_success: boolean }
  >;
  scores: {
    functional_score: number;
    performance_score: number;
    overall_score: number;
  };
}

export interface Decision {
  verdict: string;
  confidence: number;
  reasons: string[];
  recommendation: string;
  decided_by: string;
}

export interface Action {
  success: boolean;
  skipped: boolean;
  skip_reason: string | null;
  issue_url: string | null;
  issue_number: number | null;
  verified: boolean;
  error: string | null;
}

export interface InvestigationDetail {
  investigation: Investigation;
  events: AgentEvent[];
  test_runs: TestRun[];
  comparison: Comparison | null;
  decision: Decision | null;
  action: Action | null;
}

export interface DetectedChange {
  id: string;
  dependency_name: string;
  source: string;
  latest_version: string;
  release_notes: string | null;
  release_url: string | null;
  published_at: string | null;
  detected_at: number;
  triage_status: "pending" | "accepted" | "skipped";
  triage_reason: string | null;
  triage_mode: string | null;
  investigation_id: string | null;
}

export interface WatchlistEntry {
  name: string;
  source: string;
  repo: string | null;
  enabled: boolean;
  last_checked_at: number | null;
  last_seen_version: string | null;
  user_id?: string | null;
}

export interface DashboardSummary {
  user: { id: string; email: string };
  counts: {
    investigations: number;
    running: number;
    high_risk: number;
    safe: number;
    moderate: number;
  };
  recent_investigations: Investigation[];
  test_runs_by_investigation: Record<string, Record<string, TestRun>>;
  activity: AgentEvent[];
  projects: {
    repo_source: string;
    investigation_count: number;
    last_investigation_at: number;
    decided_count: number;
  }[];
  watchlist_count: number;
}

// Backend API base URL. Empty default = relative paths (same-origin), which is
// how Alfred is normally served: FastAPI serves frontend/dist itself, so the
// dashboard and the API share one origin and the session cookie just works.
// Deploying the frontend SEPARATELY? Set VITE_API_URL at build time to the
// backend's origin (e.g. VITE_API_URL=https://api.example.com bun run build).
// No trailing slash, no /api suffix — endpoints below already start with /api.
const API_BASE = (import.meta.env.VITE_API_URL ?? "").replace(/\/$/, "");

// ngrok's free tier serves a browser-warning interstitial (an HTML page with no
// CORS headers) unless requests carry this header. Other hosts ignore it.
const EXTRA_HEADERS: Record<string, string> = { "ngrok-skip-browser-warning": "true" };

async function get<T>(url: string): Promise<T> {
  const res = await fetch(`${API_BASE}${url}`, {
    credentials: "include",
    headers: EXTRA_HEADERS,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function post<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${url}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", ...EXTRA_HEADERS },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

async function del<T>(url: string): Promise<T> {
  const res = await fetch(`${API_BASE}${url}`, {
    method: "DELETE",
    credentials: "include",
    headers: EXTRA_HEADERS,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export interface AuthUser {
  id: string;
  email: string;
}

export const api = {
  // ---- auth (email + password; session cookie set by the server) ----
  signup: (email: string, password: string) =>
    post<{ user: AuthUser }>("/api/auth/signup", { email, password }),
  login: (email: string, password: string) =>
    post<{ user: AuthUser }>("/api/auth/login", { email, password }),
  logout: () => post<{ ok: boolean }>("/api/auth/logout", {}),
  me: () =>
    fetch(`${API_BASE}/api/auth/me`, { credentials: "include", headers: EXTRA_HEADERS })
      .then((r) => (r.ok ? (r.json() as Promise<{ user: AuthUser }>) : null))
      .catch(() => null),
  health: () => get<{ status: string; docker_available: boolean }>("/api/health"),
  dashboardSummary: () => get<DashboardSummary>("/api/dashboard/summary"),
  investigations: () => get<Investigation[]>("/api/investigations"),
  investigationDetail: (id: string) => get<InvestigationDetail>(`/api/investigations/${id}`),
  trigger: (
    repoSource: string,
    targetVersion: string,
    dependencyName?: string,
    github?: { token?: string; owner?: string; repo?: string },
  ) =>
    post<{ investigation_id: string }>("/api/investigations", {
      repo_source: repoSource,
      target_version: targetVersion,
      dependency_name: dependencyName || null,
      // Per-request credentials: used in-memory for this one investigation,
      // never stored server-side.
      github_token: github?.token || null,
      github_owner: github?.owner || null,
      github_repo: github?.repo || null,
    }),
  detectedChanges: () => get<DetectedChange[]>("/api/detected-changes"),
  watchlist: () => get<WatchlistEntry[]>("/api/watchlist"),
  addWatch: (
    name: string,
    source: string,
    repo?: string,
    credential?: { token: string; owner: string; repo: string },
  ) =>
    post<{ ok: boolean; credential_registered?: boolean }>("/api/watchlist", {
      name,
      source,
      repo: repo || null,
      // One-time registration: the token is stored Fernet-encrypted on this
      // watchlist entry so the background poller can run unattended. It is
      // never returned by any endpoint afterwards.
      github_token: credential?.token || null,
      github_owner: credential?.owner || null,
      github_repo: credential?.repo || null,
    }),
  removeWatch: (name: string) =>
    fetch(`${API_BASE}/api/watchlist/${encodeURIComponent(name)}`, {
      method: "DELETE",
      credentials: "include",
      headers: EXTRA_HEADERS,
    }).then((r) => r.json()),
  clearWatchlist: () =>
    del<{ ok: boolean; removed: number }>("/api/watchlist"),
  clearChanges: () =>
    del<{ ok: boolean; removed: number }>("/api/detected-changes"),
  pollDiscovery: () => post<{ new_changes: number }>("/api/discovery/poll", {}),
};

export const VERDICT_STYLES: Record<string, string> = {
  SAFE: "bg-signal-green/15 text-signal-green border-signal-green/40",
  SAFE_WITH_REVIEW: "bg-signal-amber/15 text-signal-amber border-signal-amber/40",
  MODERATE_RISK: "bg-signal-orange/15 text-signal-orange border-signal-orange/40",
  HIGH_RISK: "bg-signal-red/15 text-signal-red border-signal-red/40",
  INCOMPATIBLE: "bg-signal-red/25 text-red-300 border-red-500/50",
};

export const STATUS_STYLES: Record<string, string> = {
  running: "bg-signal-blue/15 text-signal-blue border-signal-blue/40 animate-pulse",
  complete: "bg-signal-green/10 text-signal-green border-signal-green/30",
  failed: "bg-signal-red/10 text-signal-red border-signal-red/30",
  pending: "bg-slate-500/10 text-slate-400 border-slate-500/30",
};
