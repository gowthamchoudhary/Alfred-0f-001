import { useCallback, useEffect, useState } from "react";
import {
  api,
  type AgentEvent,
  type DashboardSummary,
  type Investigation,
  type TestRun,
  type WatchlistEntry,
} from "../api";

/* ------------------------------------------------------------------ helpers */

function relTime(t: number): string {
  const s = Math.max(0, Date.now() / 1000 - t);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

/** Real orchestrator steps → readable labels (underlying value preserved). */
const STEP_LABELS: Record<string, string> = {
  PREPARE: "Preparing environments",
  BUILD: "Building environments",
  RUN: "Running environments",
  TEST: "Running tests",
  WORKLOAD: "Collecting metrics",
  COMPARE: "Comparing results",
  REASON: "Analyzing impact",
  ACTION: "Creating GitHub issue",
  VERIFY: "Verifying action",
  CLEANUP: "Cleaning up",
};

function StatusChip({ inv }: { inv: Investigation }) {
  if (inv.status === "running") {
    const label = inv.current_step
      ? (STEP_LABELS[inv.current_step] ?? inv.current_step.toLowerCase())
      : "Queued";
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-[#E1DFDC] bg-[#F0EFEB] px-2.5 py-1 text-[11px] font-medium text-[#3C3C3B]">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[#8A877E]" />
        {label}
      </span>
    );
  }
  if (inv.status === "failed") {
    return (
      <span className="inline-flex items-center rounded-full border border-[#E4C4C0] bg-[#F7E9E7] px-2.5 py-1 text-[11px] font-medium text-[#A94B43]">
        Failed
      </span>
    );
  }
  if (inv.status === "complete") {
    return (
      <span className="inline-flex items-center rounded-full border border-[#C9D6C6] bg-[#EAEFE7] px-2.5 py-1 text-[11px] font-medium text-[#4A6B45]">
        Complete
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded-full border border-[#E1DFDC] bg-[#F1EFEC] px-2.5 py-1 text-[11px] font-medium text-[#7A7873]">
      {inv.status}
    </span>
  );
}

function VerdictChip({ verdict }: { verdict: string | null }) {
  if (!verdict) return null;
  const styles: Record<string, string> = {
    SAFE: "border-[#C9D6C6] bg-[#EAEFE7] text-[#4A6B45]",
    SAFE_WITH_REVIEW: "border-[#DFD9BC] bg-[#F4F0E1] text-[#8A7020]",
    MODERATE_RISK: "border-[#E4D3B2] bg-[#F6EDE0] text-[#96652A]",
    HIGH_RISK: "border-[#E4C4C0] bg-[#F7E9E7] text-[#A94B43]",
    INCOMPATIBLE: "border-[#E4C4C0] bg-[#F3DEDC] text-[#96382F]",
  };
  const label = verdict.replace(/_/g, " ").toLowerCase();
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-medium capitalize ${styles[verdict] ?? "border-[#E1DFDC] bg-[#F1EFEC] text-[#7A7873]"}`}>
      {label}
    </span>
  );
}

function pct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

/** Real delta between the two persisted test runs, or nothing. */
function metricDelta(
  runs: Record<string, TestRun> | undefined,
  pick: (r: TestRun) => number | null,
  fmt: (v: number) => string,
): { text: string; worse: boolean } | null {
  const base = runs?.baseline ? pick(runs.baseline) : null;
  const cand = runs?.candidate ? pick(runs.candidate) : null;
  if (base === null || cand === null) return null;
  const delta = cand - base;
  const worse = delta > 0;
  const sign = delta > 0 ? "+" : "";
  return { text: `${sign}${fmt(delta)}`, worse };
}

/* ------------------------------------------------------------- design bits */

function SkeletonCard() {
  return (
    <div className="rounded-2xl border border-[#EAE9E6] bg-[#F9F8F6] p-5">
      <div className="h-3 w-24 animate-pulse rounded bg-[#EAE9E6]" />
      <div className="mt-3 h-7 w-14 animate-pulse rounded bg-[#EAE9E6]" />
    </div>
  );
}

function SummaryCard({
  label,
  value,
  loading,
}: {
  label: string;
  value: number | null;
  loading: boolean;
}) {
  return (
    <div className="rounded-2xl border border-[#EAE9E6] bg-[#F9F8F6] p-5">
      <p className="text-xs text-[#7A7873]">{label}</p>
      {loading ? (
        <div className="mt-2.5 h-7 w-14 animate-pulse rounded bg-[#EAE9E6]" />
      ) : (
        <p className="mt-1 text-3xl font-normal tracking-tight text-[#2F2F2E]">{value}</p>
      )}
    </div>
  );
}

function EmptyBlock({
  title,
  body,
  action,
}: {
  title: string;
  body: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center rounded-2xl border border-dashed border-[#E1DFDC] bg-[#F1EFEC]/50 px-6 py-10 text-center">
      <p className="text-sm font-medium text-[#3C3C3B]">{title}</p>
      <p className="mt-1 max-w-sm text-xs leading-relaxed text-[#7A7873]">{body}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

/* -------------------------------------------------------- github integration */

interface GhState {
  owner: string;
  repo: string;
  token: string;
}

function GithubCard({
  gh,
  onConnect,
  onDisconnect,
}: {
  gh: GhState | null;
  onConnect: (g: GhState) => void;
  onDisconnect: () => void;
}) {
  const [owner, setOwner] = useState("");
  const [repo, setRepo] = useState("");
  const [token, setToken] = useState("");

  if (gh) {
    return (
      <div className="rounded-2xl border border-[#EAE9E6] bg-[#F9F8F6] p-5">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-xs text-[#7A7873]">GitHub</p>
            <p className="mt-1 font-mono text-sm text-[#3C3C3B]">
              {gh.owner}/{gh.repo}
            </p>
            <p className="mt-1 text-[11px] text-[#7A7873]">
              connected — token held in memory for this session only, never stored
            </p>
          </div>
          <button
            onClick={onDisconnect}
            className="rounded-full border border-[#E1DFDC] bg-[#F9F8F6] px-4 py-1.5 text-xs text-[#3C3C3B] transition-colors hover:bg-[#F1F0EC]"
          >
            Disconnect
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-[#EAE9E6] bg-[#F9F8F6] p-5">
      <p className="text-xs text-[#7A7873]">GitHub</p>
      <p className="mt-1 text-sm font-medium text-[#3C3C3B]">
        Connect your repositories to start testing updates.
      </p>
      <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_1fr_1.4fr_auto]">
        <input
          className="rounded-full border border-[#E1DFDC] bg-white px-4 py-2 text-sm text-[#3C3C3B] placeholder-[#A6A49E] outline-none focus:border-[#B8B6B0]"
          placeholder="owner"
          value={owner}
          onChange={(e) => setOwner(e.target.value)}
          autoComplete="off"
        />
        <input
          className="rounded-full border border-[#E1DFDC] bg-white px-4 py-2 text-sm text-[#3C3C3B] placeholder-[#A6A49E] outline-none focus:border-[#B8B6B0]"
          placeholder="repo"
          value={repo}
          onChange={(e) => setRepo(e.target.value)}
          autoComplete="off"
        />
        <input
          className="rounded-full border border-[#E1DFDC] bg-white px-4 py-2 text-sm text-[#3C3C3B] placeholder-[#A6A49E] outline-none focus:border-[#B8B6B0]"
          type="password"
          placeholder="Personal access token"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          autoComplete="off"
        />
        <button
          onClick={() => {
            if (owner.trim() && repo.trim() && token.trim()) {
              onConnect({ owner: owner.trim(), repo: repo.trim(), token: token.trim() });
              setToken("");
            }
          }}
          className="rounded-full bg-[#2F2F2E] px-5 py-2 text-sm text-[#F9F8F6] transition-all hover:bg-black"
        >
          Connect GitHub
        </button>
      </div>
      <p className="mt-2 text-[11px] leading-relaxed text-[#A6A49E]">
        GitHub is an integration, not a login. Your token is used in-memory to post verdict
        issues and is never written to the database or logs.
      </p>
    </div>
  );
}

/* ------------------------------------------------------------ trigger form */

function TriggerForm({
  onTriggered,
  gh,
}: {
  onTriggered: (id: string) => void;
  gh: GhState | null;
}) {
  const [repo, setRepo] = useState("");
  const [version, setVersion] = useState("");
  const [dep, setDep] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api.trigger(
        repo.trim(),
        version.trim(),
        dep.trim() || undefined,
        gh ? { token: gh.token, owner: gh.owner, repo: gh.repo } : undefined,
      );
      onTriggered(res.investigation_id);
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="rounded-2xl border border-[#EAE9E6] bg-[#F9F8F6] p-5">
      <p className="text-xs text-[#7A7873]">Run an investigation</p>
      <p className="mt-1 text-sm text-[#7A7873]">
        Point Alfred at a contract-compliant repo — it builds baseline and candidate, runs your
        tests, and reports real metrics. GitHub destination comes from your connection when set.
      </p>
      <div className="mt-3 grid gap-2 sm:grid-cols-[2fr_auto_auto_auto]">
        <input
          className="rounded-full border border-[#E1DFDC] bg-white px-4 py-2 text-sm text-[#3C3C3B] placeholder-[#A6A49E] outline-none focus:border-[#B8B6B0]"
          placeholder="Repo path or git URL"
          value={repo}
          onChange={(e) => setRepo(e.target.value)}
          required
        />
        <input
          className="w-28 rounded-full border border-[#E1DFDC] bg-white px-4 py-2 text-sm text-[#3C3C3B] placeholder-[#A6A49E] outline-none focus:border-[#B8B6B0]"
          placeholder="target ver"
          value={version}
          onChange={(e) => setVersion(e.target.value)}
          required
        />
        <input
          className="w-36 rounded-full border border-[#E1DFDC] bg-white px-4 py-2 text-sm text-[#3C3C3B] placeholder-[#A6A49E] outline-none focus:border-[#B8B6B0]"
          placeholder="dep (optional)"
          value={dep}
          onChange={(e) => setDep(e.target.value)}
        />
        <button
          type="submit"
          disabled={busy}
          className="rounded-full bg-[#2F2F2E] px-5 py-2 text-sm text-[#F9F8F6] transition-all hover:bg-black disabled:opacity-50"
        >
          {busy ? "Starting…" : "Investigate"}
        </button>
      </div>
      {error && <p className="mt-2 px-1 text-xs text-[#A94B43]">{error}</p>}
    </form>
  );
}

/* ------------------------------------------------------------ investigations */

function InvestigationCard({
  inv,
  runs,
  onOpen,
}: {
  inv: Investigation;
  runs?: Record<string, TestRun>;
  onOpen: (id: string) => void;
}) {
  const compat =
    inv.compatibility_score !== null && inv.compatibility_score !== undefined
      ? pct(inv.compatibility_score)
      : null;
  const cand = runs?.candidate;
  const base = runs?.baseline;

  // Only real numbers: each metric renders only when both runs measured it.
  const tests =
    cand?.tests_passed !== null && cand?.tests_passed !== undefined && cand?.tests_total
      ? `${cand.tests_passed} / ${cand.tests_total}`
      : null;
  const p95 = metricDelta(runs, (r) => r.latency_p95_ms, (v) => `${v.toFixed(1)}ms`);
  const errDelta = metricDelta(
    runs,
    (r) => (r.workload_error_rate === null ? null : r.workload_error_rate * 100),
    (v) => `${v.toFixed(1)}pp`,
  );
  const baseP95 = base?.latency_p95_ms;
  const candP95 = cand?.latency_p95_ms;

  return (
    <button
      onClick={() => onOpen(inv.id)}
      className="group flex flex-col rounded-2xl border border-[#EAE9E6] bg-[#F9F8F6] p-5 text-left transition-colors hover:border-[#D8D6D0] hover:bg-[#F1F0EC]"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-[#3C3C3B]">{inv.dependency_name}</p>
          <p className="mt-0.5 font-mono text-xs text-[#7A7873]">
            {inv.baseline_version} → {inv.candidate_version}
          </p>
        </div>
        <StatusChip inv={inv} />
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        {inv.verdict ? <VerdictChip verdict={inv.verdict} /> : null}
        {compat ? (
          <span className="font-mono text-xs text-[#7A7873]">
            compatibility <span className="text-[#3C3C3B]">{compat}</span>
          </span>
        ) : null}
      </div>

      <div className="mt-4 grid grid-cols-3 gap-3 border-t border-[#EAE9E6] pt-3">
        <div>
          <p className="text-[10px] uppercase tracking-wide text-[#A6A49E]">Tests</p>
          <p className="mt-0.5 font-mono text-xs text-[#3C3C3B]">{tests ?? "Pending"}</p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wide text-[#A6A49E]">P95</p>
          <p className="mt-0.5 font-mono text-xs text-[#3C3C3B]">
            {p95 ? (
              <span className={p95.worse ? "text-[#A94B43]" : "text-[#4A6B45]"}>{p95.text}</span>
            ) : baseP95 && candP95 === null ? (
              "Pending"
            ) : (
              "—"
            )}
          </p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wide text-[#A6A49E]">Error rate</p>
          <p className="mt-0.5 font-mono text-xs text-[#3C3C3B]">
            {errDelta ? (
              <span className={errDelta.worse ? "text-[#A94B43]" : "text-[#4A6B45]"}>
                {errDelta.text}
              </span>
            ) : (
              "Pending"
            )}
          </p>
        </div>
      </div>

      <div className="mt-3 flex items-center justify-between text-[11px] text-[#A6A49E]">
        <span>{relTime(inv.created_at)}</span>
        <span className="opacity-0 transition-opacity group-hover:opacity-100">
          View details →
        </span>
      </div>
    </button>
  );
}

/* ------------------------------------------------------------------- activity */

const ACTIVITY_ICONS: Record<string, string> = {
  DISCOVERY: "◍",
  TRIAGE: "◆",
  PREPARE: "◇",
  BUILD: "▪",
  RUN: "●",
  TEST: "✓",
  WORKLOAD: "≈",
  COMPARE: "⇄",
  REASON: "◈",
  ACTION: "↗",
  VERIFY: "✓",
  CLEANUP: "○",
};

function ActivityItem({ e }: { e: AgentEvent }) {
  return (
    <li className="flex gap-3">
      <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-[#E1DFDC] bg-[#F1EFEC] text-[10px] text-[#7A7873]">
        {ACTIVITY_ICONS[e.step] ?? "•"}
      </span>
      <div className="min-w-0 pb-4">
        <p className="text-xs leading-relaxed text-[#3C3C3B]">{e.message}</p>
        <p className="mt-0.5 text-[10px] uppercase tracking-wide text-[#A6A49E]">
          {e.step} · {relTime(e.created_at)}
        </p>
      </div>
    </li>
  );
}

/* -------------------------------------------------------------------- shell */

const NAV_ITEMS = ["Overview", "Projects", "Investigations", "Changes", "Watchlist", "Settings"] as const;
type NavItem = (typeof NAV_ITEMS)[number];

export default function DashboardPage({
  user,
  onSelect,
  onTriggered,
  onSignOut,
}: {
  user: { id: string; email: string };
  onSelect: (id: string) => void;
  onTriggered: (id: string) => void;
  onSignOut: () => void;
}) {
  const [nav, setNav] = useState<NavItem>("Overview");
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [gh, setGh] = useState<GhState | null>(null);
  const [search, setSearch] = useState("");

  // Polling — the dashboard reflects real pipeline state as it progresses.
  useEffect(() => {
    let alive = true;
    let first = true;
    const refresh = async () => {
      try {
        const s = await api.dashboardSummary();
        if (!alive) return;
        setSummary(s);
        setLoadError(null);
      } catch (err) {
        if (alive && first) setLoadError(String(err instanceof Error ? err.message : err));
      } finally {
        first = false;
      }
    };
    refresh();
    const t = setInterval(refresh, 4000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  const initials = user.email.slice(0, 2).toUpperCase();
  const loading = summary === null && !loadError;

  const investigations = summary?.recent_investigations ?? [];
  const filteredInv = search.trim()
    ? investigations.filter((i) =>
        `${i.dependency_name} ${i.baseline_version} ${i.candidate_version}`
          .toLowerCase()
          .includes(search.trim().toLowerCase()),
      )
    : investigations;
  const activity = summary?.activity ?? [];
  const projects = summary?.projects ?? [];
  const counts = summary?.counts;

  return (
    <div className="alfred-shell min-h-screen px-2.5 py-4 sm:px-4 sm:py-6 lg:px-6">
      <div className="mx-auto max-w-[1200px] overflow-hidden rounded-[2rem] border border-[#EAE9E6] bg-[#F1F0EC] shadow-[0_30px_80px_-48px_rgba(60,60,59,0.28)]">
        <div className="flex min-h-[720px]">
          {/* ---------------------------------------------------- sidebar */}
          <aside className="hidden w-56 shrink-0 flex-col justify-between border-r border-[#EAE9E6] bg-[#F1F0EC] px-4 py-6 sm:flex">
            <div>
              <div className="flex items-center gap-2 px-2">
                <img
                  src="/logos/alfred.png"
                  alt="Alfred logo"
                  className="h-7 w-7 rounded-full object-cover"
                />
                <span className="text-sm font-medium text-[#3C3C3B]">Alfred</span>
              </div>
              <nav className="mt-8 space-y-1">
                {NAV_ITEMS.map((item) => (
                  <button
                    key={item}
                    onClick={() => setNav(item)}
                    className={`w-full rounded-full px-4 py-2 text-left text-sm transition-colors ${
                      nav === item
                        ? "bg-[#2F2F2E] text-[#F9F8F6]"
                        : "text-[#3C3C3B] hover:bg-[#EAE9E6]"
                    }`}
                  >
                    {item}
                  </button>
                ))}
              </nav>
            </div>
            <div className="px-2">
              <div className="flex items-center gap-2 border-t border-[#E1DFDC] pt-4">
                <span className="flex h-7 w-7 items-center justify-center rounded-full bg-[#E1DFDC] text-[10px] font-medium text-[#3C3C3B]">
                  {initials}
                </span>
                <span className="min-w-0 flex-1 truncate text-xs text-[#7A7873]">
                  {user.email}
                </span>
              </div>
              <button
                onClick={onSignOut}
                className="mt-2 w-full rounded-full px-4 py-1.5 text-left text-xs text-[#7A7873] transition-colors hover:bg-[#EAE9E6] hover:text-[#3C3C3B]"
              >
                Sign out
              </button>
            </div>
          </aside>

          {/* ----------------------------------------------- main column */}
          <div className="min-w-0 flex-1 bg-[#F9F8F6]">
            {/* header */}
            <div className="flex items-center gap-3 border-b border-[#EAE9E6] px-6 py-4">
              <input
                className="min-w-0 flex-1 rounded-full border border-[#E1DFDC] bg-[#F1F0EC] px-4 py-2 text-sm text-[#3C3C3B] placeholder-[#A6A49E] outline-none focus:border-[#B8B6B0]"
                placeholder="Search investigations, projects, or dependencies..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              <span className="hidden h-8 w-8 items-center justify-center rounded-full bg-[#E1DFDC] text-[10px] font-medium text-[#3C3C3B] sm:flex">
                {initials}
              </span>
            </div>

            <div className="px-6 py-6">
              {loadError && (
                <div className="mb-5 flex items-center justify-between rounded-2xl border border-[#E4C4C0] bg-[#F7E9E7] px-4 py-3">
                  <p className="text-sm text-[#A94B43]">Unable to load dashboard — {loadError}</p>
                  <button
                    onClick={() => api.dashboardSummary().then(setSummary).catch(() => undefined)}
                    className="rounded-full border border-[#E1DFDC] bg-[#F9F8F6] px-4 py-1.5 text-xs text-[#3C3C3B]"
                  >
                    Retry
                  </button>
                </div>
              )}

              {nav === "Overview" && (
                <div className="space-y-6">
                  {/* welcome / connect */}
                  {loading ? null : investigations.length === 0 ? (
                    <div className="rounded-2xl border border-dashed border-[#E1DFDC] bg-[#F1EFEC]/60 px-6 py-10 text-center">
                      <p className="text-lg font-normal text-[#2F2F2E]">Welcome to Alfred.</p>
                      <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-[#7A7873]">
                        Connect a GitHub repository and Alfred will detect the software your
                        project depends on and begin tracking release impact — with real tests,
                        not guesses.
                      </p>
                      <div className="mt-4">
                        <GithubCardInline gh={gh} onConnect={setGh} onDisconnect={() => setGh(null)} />
                      </div>
                    </div>
                  ) : (
                    <GithubCard gh={gh} onConnect={setGh} onDisconnect={() => setGh(null)} />
                  )}

                  {/* summary cards */}
                  <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                    <SummaryCard label="Projects" value={projects.length || (loading ? null : 0)} loading={loading} />
                    <SummaryCard label="Investigations" value={counts?.investigations ?? (loading ? null : 0)} loading={loading} />
                    <SummaryCard label="High Risk" value={counts?.high_risk ?? (loading ? null : 0)} loading={loading} />
                    <SummaryCard label="Safe" value={counts?.safe ?? (loading ? null : 0)} loading={loading} />
                  </div>

                  {/* recent investigations */}
                  <section>
                    <div className="flex items-baseline justify-between">
                      <div>
                        <h2 className="text-base font-medium text-[#3C3C3B]">
                          Recent Investigations
                        </h2>
                        <p className="mt-0.5 text-xs text-[#7A7873]">
                          Latest release-impact tests across your projects.
                        </p>
                      </div>
                    </div>
                    <div className="mt-4">
                      {loading ? (
                        <div className="grid gap-4 sm:grid-cols-2">
                          <SkeletonCard />
                          <SkeletonCard />
                        </div>
                      ) : filteredInv.length === 0 ? (
                        <EmptyBlock
                          title="No investigations yet."
                          body="Connect a project to run your first release-impact investigation, or trigger one below — Alfred builds both versions and measures the real difference."
                        />
                      ) : (
                        <div className="grid gap-4 sm:grid-cols-2">
                          {filteredInv.map((inv) => (
                            <InvestigationCard
                              key={inv.id}
                              inv={inv}
                              runs={summary?.test_runs_by_investigation?.[inv.id]}
                              onOpen={onSelect}
                            />
                          ))}
                        </div>
                      )}
                    </div>
                  </section>

                  {/* trigger */}
                  <TriggerForm onTriggered={onTriggered} gh={gh} />

                  {/* activity + projects */}
                  <div className="grid gap-6 lg:grid-cols-2">
                    <section>
                      <h2 className="text-base font-medium text-[#3C3C3B]">Activity</h2>
                      <p className="mt-0.5 text-xs text-[#7A7873]">
                        Live agent events from the pipeline.
                      </p>
                      <div className="mt-4 rounded-2xl border border-[#EAE9E6] bg-[#F9F8F6] p-5">
                        {loading ? (
                          <div className="space-y-3">
                            <div className="h-3 w-3/4 animate-pulse rounded bg-[#EAE9E6]" />
                            <div className="h-3 w-2/3 animate-pulse rounded bg-[#EAE9E6]" />
                            <div className="h-3 w-1/2 animate-pulse rounded bg-[#EAE9E6]" />
                          </div>
                        ) : activity.length === 0 ? (
                          <p className="text-xs text-[#7A7873]">No agent activity yet.</p>
                        ) : (
                          <ul className="max-h-80 overflow-y-auto">
                            {activity.map((e) => (
                              <ActivityItem key={e.id} e={e} />
                            ))}
                          </ul>
                        )}
                      </div>
                    </section>

                    <section>
                      <h2 className="text-base font-medium text-[#3C3C3B]">Monitored Projects</h2>
                      <p className="mt-0.5 text-xs text-[#7A7873]">
                        Repositories Alfred has investigated for you.
                      </p>
                      <div className="mt-4 space-y-3">
                        {loading ? (
                          <SkeletonCard />
                        ) : projects.length === 0 ? (
                          <EmptyBlock
                            title="No projects connected."
                            body="Projects appear here after your first investigation. Connect GitHub and run one against your repo."
                          />
                        ) : (
                          projects.map((p) => (
                            <div
                              key={p.repo_source}
                              className="flex items-center justify-between rounded-2xl border border-[#EAE9E6] bg-[#F9F8F6] px-5 py-4"
                            >
                              <div className="min-w-0">
                                <p className="truncate font-mono text-xs text-[#3C3C3B]" title={p.repo_source}>
                                  {p.repo_source}
                                </p>
                                <p className="mt-0.5 text-[11px] text-[#7A7873]">
                                  {p.investigation_count} investigation
                                  {p.investigation_count === 1 ? "" : "s"} · last{" "}
                                  {relTime(p.last_investigation_at)}
                                </p>
                              </div>
                              <span className="shrink-0 rounded-full border border-[#E1DFDC] bg-[#F1EFEC] px-2.5 py-1 text-[10px] text-[#7A7873]">
                                {p.decided_count} decided
                              </span>
                            </div>
                          ))
                        )}
                      </div>
                    </section>
                  </div>
                </div>
              )}

              {nav === "Investigations" && (
                <div className="space-y-4">
                  <h2 className="text-base font-medium text-[#3C3C3B]">Investigations</h2>
                  {loading ? (
                    <div className="grid gap-4 sm:grid-cols-2">
                      <SkeletonCard />
                      <SkeletonCard />
                    </div>
                  ) : filteredInv.length === 0 ? (
                    <EmptyBlock
                      title="No investigations yet."
                      body="Run your first release-impact investigation to see it here."
                    />
                  ) : (
                    <div className="grid gap-4 sm:grid-cols-2">
                      {filteredInv.map((inv) => (
                        <InvestigationCard
                          key={inv.id}
                          inv={inv}
                          runs={summary?.test_runs_by_investigation?.[inv.id]}
                          onOpen={onSelect}
                        />
                      ))}
                    </div>
                  )}
                </div>
              )}

              {nav === "Projects" && (
                <div className="space-y-4">
                  <h2 className="text-base font-medium text-[#3C3C3B]">Projects</h2>
                  {loading ? (
                    <SkeletonCard />
                  ) : projects.length === 0 ? (
                    <EmptyBlock
                      title="No projects connected."
                      body="Projects appear here after your first investigation."
                    />
                  ) : (
                    projects.map((p) => (
                      <div
                        key={p.repo_source}
                        className="flex items-center justify-between rounded-2xl border border-[#EAE9E6] bg-[#F9F8F6] px-5 py-4"
                      >
                        <p className="truncate font-mono text-xs text-[#3C3C3B]">{p.repo_source}</p>
                        <span className="text-xs text-[#7A7873]">
                          {p.investigation_count} investigations
                        </span>
                      </div>
                    ))
                  )}
                </div>
              )}

              {nav === "Changes" && <ChangesPanel loading={loading} />}

              {nav === "Watchlist" && <WatchlistPanel />}

              {nav === "Settings" && (
                <div className="space-y-4">
                  <h2 className="text-base font-medium text-[#3C3C3B]">Settings</h2>
                  <GithubCard gh={gh} onConnect={setGh} onDisconnect={() => setGh(null)} />
                  <div className="rounded-2xl border border-[#EAE9E6] bg-[#F9F8F6] p-5">
                    <p className="text-xs text-[#7A7873]">Account</p>
                    <p className="mt-1 text-sm text-[#3C3C3B]">{user.email}</p>
                    <p className="mt-3 text-[11px] leading-relaxed text-[#A6A49E]">
                      Alfred authenticates with email + password only. GitHub is an integration —
                      your token is supplied per-investigation and never stored.
                    </p>
                    <button
                      onClick={onSignOut}
                      className="mt-4 rounded-full border border-[#E1DFDC] bg-[#F9F8F6] px-4 py-1.5 text-xs text-[#3C3C3B] transition-colors hover:bg-[#F1F0EC]"
                    >
                      Sign out
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ----------------------------------------------------------- changes panel */

function ChangesPanel({ loading }: { loading: boolean }) {
  const [changes, setChanges] = useState<DetectedChangeLite[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [clearing, setClearing] = useState(false);

  const refresh = useCallback(() => {
    api
      .detectedChanges()
      .then((c) => setChanges(c))
      .catch((e) => setError(String(e instanceof Error ? e.message : e)));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const clearAll = async () => {
    if (!window.confirm("Clear every detected change from this feed? Past investigations are kept."))
      return;
    setClearing(true);
    try {
      await api.clearChanges();
      refresh();
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setClearing(false);
    }
  };

  if (loading) return <SkeletonCard />;
  if (error) return <p className="text-sm text-[#A94B43]">Unable to load changes — {error}</p>;
  if (changes.length === 0)
    return (
      <EmptyBlock
        title="No changes detected yet."
        body="Alfred's discovery poller watches PyPI/GitHub for new releases of your dependencies and records every change it finds here."
      />
    );

  return (
    <div className="space-y-2">
      <div className="flex justify-end">
        <button
          onClick={clearAll}
          disabled={clearing}
          className="rounded-full border border-[#E1DFDC] bg-[#F9F8F6] px-3 py-1 text-[11px] text-[#7A7873] transition-colors hover:bg-[#F1EFEC] hover:text-[#A94B43] disabled:opacity-50"
        >
          {clearing ? "clearing…" : "clear all"}
        </button>
      </div>
      {changes.map((c) => (
        <div
          key={c.id}
          className="flex items-center justify-between rounded-2xl border border-[#EAE9E6] bg-[#F9F8F6] px-5 py-3"
        >
          <div className="min-w-0">
            <p className="truncate text-sm text-[#3C3C3B]">
              <span className="font-medium">{c.dependency_name}</span>{" "}
              <span className="font-mono text-xs text-[#7A7873]">{c.latest_version}</span>
            </p>
            <p className="text-[11px] text-[#A6A49E]">
              {c.source} · detected {relTime(c.detected_at)}
              {c.triage_reason ? ` · ${c.triage_reason}` : ""}
            </p>
          </div>
          <span
            className={`shrink-0 rounded-full border px-2.5 py-1 text-[10px] capitalize ${
              c.triage_status === "accepted"
                ? "border-[#C9D6C6] bg-[#EAEFE7] text-[#4A6B45]"
                : c.triage_status === "skipped"
                  ? "border-[#E1DFDC] bg-[#F1EFEC] text-[#7A7873]"
                  : "border-[#DFD9BC] bg-[#F4F0E1] text-[#8A7020]"
            }`}
          >
            {c.triage_status}
          </span>
        </div>
      ))}
    </div>
  );
}

interface DetectedChangeLite {
  id: string;
  dependency_name: string;
  source: string;
  latest_version: string;
  triage_status: string;
  triage_reason: string | null;
  detected_at: number;
}

/* ----------------------------------------------------------- watchlist panel */

function WatchlistPanel() {
  const [entries, setEntries] = useState<WatchlistEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [clearing, setClearing] = useState(false);

  const refresh = useCallback(() => {
    setLoading(true);
    api
      .watchlist()
      .then((w) => {
        setEntries(w);
        setError(null);
      })
      .catch((e) => setError(String(e instanceof Error ? e.message : e)))
      .finally(() => setLoading(false));
  }, []);

  const clearAll = async () => {
    if (
      !window.confirm(
        "Remove every watched dependency? Stored GitHub credentials on these entries are deleted too.",
      )
    )
      return;
    setClearing(true);
    try {
      await api.clearWatchlist();
      refresh();
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setClearing(false);
    }
  };

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <div className="space-y-6">
      <section>
        <div className="flex items-start justify-between gap-3">
          <h2 className="text-base font-medium text-[#3C3C3B]">Monitored dependencies</h2>
          {entries.length > 0 && (
            <button
              onClick={clearAll}
              disabled={clearing}
              className="shrink-0 rounded-full border border-[#E1DFDC] bg-[#F9F8F6] px-3 py-1 text-[11px] text-[#7A7873] transition-colors hover:bg-[#F1EFEC] hover:text-[#A94B43] disabled:opacity-50"
            >
              {clearing ? "clearing…" : "clear all"}
            </button>
          )}
        </div>
        <p className="mt-0.5 text-xs text-[#7A7873]">
          What the background poller checks every {"ALFRED_POLL_INTERVAL"} seconds. A new release
          here is detected, triaged, and — if accepted — investigated automatically with zero human
          action.
        </p>
        <div className="mt-4 space-y-2">
          {loading ? (
            <SkeletonCard />
          ) : error ? (
            <p className="text-sm text-[#A94B43]">Unable to load watchlist — {error}</p>
          ) : entries.length === 0 ? (
            <EmptyBlock
              title="Nothing on the watchlist yet."
              body="Add a dependency below — Alfred polls its release feed on a schedule and investigates accepted updates on its own."
            />
          ) : (
            entries.map((w) => (
              <div
                key={w.name}
                className="flex items-center justify-between rounded-2xl border border-[#EAE9E6] bg-[#F9F8F6] px-5 py-3"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm text-[#3C3C3B]">
                    <span className="font-medium">{w.name}</span>{" "}
                    <span className="rounded-full border border-[#E1DFDC] bg-[#F1EFEC] px-2 py-0.5 text-[10px] text-[#7A7873]">
                      {w.source}
                    </span>
                  </p>
                  <p className="text-[11px] text-[#A6A49E]">
                    {w.last_seen_version
                      ? `last seen ${w.last_seen_version}${
                          w.last_checked_at !== null && w.last_checked_at !== undefined
                            ? ` · checked ${relTime(w.last_checked_at)}`
                            : ""
                        }`
                      : "never polled yet"}
                    {w.repo ? ` · ${w.repo}` : ""}
                  </p>
                </div>
                <button
                  onClick={() =>
                    api
                      .removeWatch(w.name)
                      .then(refresh)
                      .catch(() => undefined)
                  }
                  className="shrink-0 rounded-full border border-[#E1DFDC] bg-[#F9F8F6] px-3 py-1 text-[11px] text-[#7A7873] transition-colors hover:bg-[#F1EFEC]"
                >
                  remove
                </button>
              </div>
            ))
          )}
        </div>
      </section>

      <AddWatchForm onAdded={refresh} />
    </div>
  );
}

function AddWatchForm({ onAdded }: { onAdded: () => void }) {
  const [name, setName] = useState("");
  const [source, setSource] = useState("pypi");
  const [ghRepo, setGhRepo] = useState("");
  const [owner, setOwner] = useState("");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [registered, setRegistered] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setRegistered(false);
    try {
      const credential = owner.trim() && token.trim() ? { token: token.trim(), owner: owner.trim(), repo: ghRepo.trim() } : undefined;
      const res = await api.addWatch(
        name.trim(),
        source,
        ghRepo.trim() || undefined,
        credential,
      );
      setRegistered(res.credential_registered === true);
      setName("");
      setGhRepo("");
      setOwner("");
      setToken("");
      onAdded();
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="rounded-2xl border border-[#EAE9E6] bg-[#F9F8F6] p-5">
      <p className="text-xs text-[#7A7873]">Watch a dependency</p>
      <p className="mt-1 text-sm text-[#7A7873]">
        Alfred polls its releases on a schedule. Paste a GitHub token below <em>once</em> — it is
        stored encrypted (Fernet, at rest) on this entry so automatic investigations can post their
        verdict issue unattended. It is never returned by any endpoint, never logged, and can be
        rotated by re-registering. Leave it blank and verdict issues simply skip.
      </p>
      <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_auto_1.4fr]">
        <input
          className="rounded-full border border-[#E1DFDC] bg-white px-4 py-2 text-sm text-[#3C3C3B] placeholder-[#A6A49E] outline-none focus:border-[#B8B6B0]"
          placeholder="dependency (e.g. openai)"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          autoComplete="off"
        />
        <select
          className="rounded-full border border-[#E1DFDC] bg-white px-4 py-2 text-sm text-[#3C3C3B] outline-none focus:border-[#B8B6B0]"
          value={source}
          onChange={(e) => setSource(e.target.value)}
        >
          <option value="pypi">PyPI</option>
          <option value="github">GitHub</option>
        </select>
        <input
          className="rounded-full border border-[#E1DFDC] bg-white px-4 py-2 text-sm text-[#3C3C3B] placeholder-[#A6A49E] outline-none focus:border-[#B8B6B0]"
          placeholder="github owner/repo (optional, e.g. openai/openai-python)"
          value={ghRepo}
          onChange={(e) => setGhRepo(e.target.value)}
          autoComplete="off"
        />
      </div>
      <div className="mt-2 grid gap-2 sm:grid-cols-[1fr_1.6fr_auto]">
        <input
          className="rounded-full border border-[#E1DFDC] bg-white px-4 py-2 text-sm text-[#3C3C3B] placeholder-[#A6A49E] outline-none focus:border-[#B8B6B0]"
          placeholder="issue destination owner (optional)"
          value={owner}
          onChange={(e) => setOwner(e.target.value)}
          autoComplete="off"
        />
        <input
          className="rounded-full border border-[#E1DFDC] bg-white px-4 py-2 text-sm text-[#3C3C3B] placeholder-[#A6A49E] outline-none focus:border-[#B8B6B0]"
          type="password"
          placeholder="GitHub token (one-time, encrypted at rest)"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          autoComplete="new-password"
        />
        <button
          type="submit"
          disabled={busy}
          className="rounded-full bg-[#2F2F2E] px-5 py-2 text-sm text-[#F9F8F6] transition-all hover:bg-black disabled:opacity-50"
        >
          {busy ? "Saving…" : "Watch"}
        </button>
      </div>
      {error && <p className="mt-2 px-1 text-xs text-[#A94B43]">{error}</p>}
      {registered && !error && (
        <p className="mt-2 px-1 text-xs text-[#4A6B45]">
          Credential registered — encrypted at rest, never returned. Automatic investigations for
          this entry can now post their verdict issue on their own.
        </p>
      )}
    </form>
  );
}

function GithubCardInline({
  gh,
  onConnect,
  onDisconnect,
}: {
  gh: GhState | null;
  onConnect: (g: GhState) => void;
  onDisconnect: () => void;
}) {
  const [owner, setOwner] = useState("");
  const [repo, setRepo] = useState("");
  const [token, setToken] = useState("");
  if (gh) {
    return (
      <p className="font-mono text-xs text-[#3C3C3B]">
        {gh.owner}/{gh.repo}{" "}
        <button onClick={onDisconnect} className="ml-2 text-[#7A7873] underline underline-offset-2">
          disconnect
        </button>
      </p>
    );
  }
  return (
    <div className="mx-auto flex max-w-xl flex-wrap items-center justify-center gap-2">
      <input
        className="w-32 rounded-full border border-[#E1DFDC] bg-white px-4 py-2 text-xs text-[#3C3C3B] placeholder-[#A6A49E] outline-none focus:border-[#B8B6B0]"
        placeholder="owner"
        value={owner}
        onChange={(e) => setOwner(e.target.value)}
        autoComplete="off"
      />
      <input
        className="w-40 rounded-full border border-[#E1DFDC] bg-white px-4 py-2 text-xs text-[#3C3C3B] placeholder-[#A6A49E] outline-none focus:border-[#B8B6B0]"
        placeholder="repo"
        value={repo}
        onChange={(e) => setRepo(e.target.value)}
        autoComplete="off"
      />
      <input
        className="w-56 rounded-full border border-[#E1DFDC] bg-white px-4 py-2 text-xs text-[#3C3C3B] placeholder-[#A6A49E] outline-none focus:border-[#B8B6B0]"
        type="password"
        placeholder="GitHub token"
        value={token}
        onChange={(e) => setToken(e.target.value)}
        autoComplete="off"
      />
      <button
        onClick={() => {
          if (owner.trim() && repo.trim() && token.trim()) {
            onConnect({ owner: owner.trim(), repo: repo.trim(), token: token.trim() });
            setToken("");
          }
        }}
        className="rounded-full bg-[#2F2F2E] px-5 py-2 text-xs text-[#F9F8F6] transition-all hover:bg-black"
      >
        Connect GitHub
      </button>
    </div>
  );
}
