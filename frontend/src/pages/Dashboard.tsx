import { useEffect, useState } from "react";
import {
  api,
  type DetectedChange,
  type Investigation,
  type WatchlistEntry,
} from "../api";
import { StatusBadge, VerdictBadge } from "../components/Badges";

function fmtTime(t: number): string {
  return new Date(t * 1000).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function GithubConnectCard({
  gh,
  onConnect,
  onDisconnect,
}: {
  gh: GithubConnection | null;
  onConnect: (c: GithubConnection) => void;
  onDisconnect: () => void;
}) {
  const [token, setToken] = useState("");
  const [owner, setOwner] = useState("");
  const [repoName, setRepoName] = useState("");

  if (gh) {
    return (
      <div className="card">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400">GitHub</h2>
            <p className="mt-1 text-xs text-slate-500">
              connected — <span className="font-mono text-slate-300">{gh.owner}/{gh.repo}</span> · token held in
              memory for this session only, never stored
            </p>
          </div>
          <button onClick={onDisconnect} className="btn-ghost text-xs">
            Disconnect
          </button>
        </div>
      </div>
    );
  }

  const connect = () => {
    if (!token.trim() || !owner.trim() || !repoName.trim()) return;
    onConnect({ token: token.trim(), owner: owner.trim(), repo: repoName.trim() });
    setToken("");
  };

  return (
    <div className="card">
      <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400">Connect GitHub</h2>
      <p className="mt-1 text-xs text-slate-500">
        Alfred authenticates with email — GitHub is an integration, not a login. Your PAT is held
        in memory for this session only; it is never written to the database or logs.
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-[2fr_1fr_1fr_auto]">
        <input
          className="input"
          type="password"
          placeholder="Personal access token"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          autoComplete="off"
        />
        <input
          className="input"
          placeholder="owner"
          value={owner}
          onChange={(e) => setOwner(e.target.value)}
          autoComplete="off"
        />
        <input
          className="input"
          placeholder="repo"
          value={repoName}
          onChange={(e) => setRepoName(e.target.value)}
          autoComplete="off"
        />
        <button onClick={connect} className="btn-primary">
          Connect
        </button>
      </div>
    </div>
  );
}

function TriggerForm({
  onTriggered,
  github,
}: {
  onTriggered: (id: string) => void;
  github?: GithubConnection | null;
}) {
  const [repo, setRepo] = useState("");
  const [version, setVersion] = useState("");
  const [dep, setDep] = useState("");
  const [ghOwner, setGhOwner] = useState(github?.owner ?? "");
  const [ghRepo, setGhRepo] = useState(github?.repo ?? "");
  const [ghToken, setGhToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      // A connected GitHub session supplies the token in-memory; the manual
      // PAT field is the per-run fallback when nothing is connected.
      const token = github?.token || ghToken.trim() || undefined;
      const owner = ghOwner.trim() || undefined;
      const targetRepo = ghRepo.trim() || undefined;
      const res = await api.trigger(repo.trim(), version.trim(), dep.trim() || undefined, {
        token,
        owner,
        repo: targetRepo,
      });
      setGhToken("");
      onTriggered(res.investigation_id);
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="card">
      <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400">
        Manual trigger <span className="normal-case text-slate-600">(fallback / debug)</span>
      </h2>
      <p className="mt-1 text-xs text-slate-500">
        The primary path is discovery → triage → automatic investigation. This runs the same pipeline on demand.
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-[1fr_auto_auto_auto]">
        <input
          className="input"
          placeholder="Repo path or git URL (contract-compliant)"
          value={repo}
          onChange={(e) => setRepo(e.target.value)}
          required
        />
        <input
          className="input sm:w-28"
          placeholder="target ver"
          value={version}
          onChange={(e) => setVersion(e.target.value)}
          required
        />
        <input
          className="input sm:w-32"
          placeholder="dep (optional)"
          value={dep}
          onChange={(e) => setDep(e.target.value)}
        />
        <button type="submit" disabled={busy} className="btn-primary disabled:opacity-50">
          {busy ? "starting…" : "Investigate"}
        </button>
      </div>
      <div className="mt-3">
        <p className="text-xs uppercase tracking-wider text-slate-500">
          Post verdict to GitHub <span className="normal-case text-slate-600">(optional, per-run)</span>
        </p>
        <div className="mt-2 grid gap-3 sm:grid-cols-[1fr_1fr_2fr]">
          <input
            className="input"
            placeholder="github owner"
            value={ghOwner}
            onChange={(e) => setGhOwner(e.target.value)}
            autoComplete="off"
          />
          <input
            className="input"
            placeholder="github repo"
            value={ghRepo}
            onChange={(e) => setGhRepo(e.target.value)}
            autoComplete="off"
          />
          <input
            className="input"
            type="password"
            placeholder="your GitHub PAT — used in-memory for this run only, never stored"
            value={ghToken}
            onChange={(e) => setGhToken(e.target.value)}
            autoComplete="off"
          />
        </div>
        <p className="mt-1.5 text-[11px] text-slate-600">
          Your token is sent with this one request, held in memory for the duration of the run, and discarded — it is
          never written to the database or logs. Leave it empty to skip the GitHub step.
        </p>
      </div>
      {error && <p className="mt-2 text-xs text-signal-red">{error}</p>}
    </form>
  );
}

function WatchlistPanel() {
  const [entries, setEntries] = useState<WatchlistEntry[]>([]);
  const [name, setName] = useState("");
  const [source, setSource] = useState("pypi");
  const [repo, setRepo] = useState("");
  const [polling, setPolling] = useState(false);

  const refresh = () => api.watchlist().then(setEntries).catch(() => undefined);
  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 10000);
    return () => clearInterval(t);
  }, []);

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    await api.addWatch(name.trim(), source, repo.trim() || undefined);
    setName("");
    setRepo("");
    refresh();
  };

  const remove = async (n: string) => {
    await api.removeWatch(n);
    refresh();
  };

  const pollNow = async () => {
    setPolling(true);
    try {
      await api.pollDiscovery();
    } finally {
      setPolling(false);
    }
  };

  return (
    <div className="card">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400">
          Discovery watchlist
        </h2>
        <button onClick={pollNow} disabled={polling} className="btn-ghost text-xs disabled:opacity-50">
          {polling ? "polling…" : "Poll now"}
        </button>
      </div>
      <div className="mt-3 space-y-1.5">
        {entries.length === 0 && <p className="text-xs text-slate-500">nothing watched yet</p>}
        {entries.map((w) => (
          <div
            key={w.name}
            className="flex items-center justify-between rounded-lg border border-ink-700/60 bg-ink-800/40 px-3 py-2"
          >
            <div>
              <span className="font-mono text-sm text-slate-200">{w.name}</span>
              <span className="ml-2 rounded border border-ink-700 px-1.5 py-0.5 text-[10px] uppercase text-slate-500">
                {w.source}
              </span>
              {w.last_seen_version && (
                <span className="ml-2 text-xs text-slate-500">latest seen {w.last_seen_version}</span>
              )}
            </div>
            <button
              onClick={() => remove(w.name)}
              className="text-xs text-slate-500 hover:text-signal-red"
              title="stop watching"
            >
              ✕
            </button>
          </div>
        ))}
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_auto_auto_auto]">
        <input
          className="input"
          placeholder="package (e.g. openai)"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <select className="input sm:w-24" value={source} onChange={(e) => setSource(e.target.value)}>
          <option value="pypi">PyPI</option>
          <option value="github">GitHub</option>
        </select>
        <input
          className="input sm:w-40"
          placeholder="owner/repo (github)"
          value={repo}
          onChange={(e) => setRepo(e.target.value)}
          disabled={source !== "github"}
        />
        <button onClick={add} className="btn-ghost">
          Watch
        </button>
      </div>
    </div>
  );
}

function SkippedChanges({ changes }: { changes: DetectedChange[] }) {
  const [open, setOpen] = useState(true);
  const skipped = changes.filter((c) => c.triage_status === "skipped");
  return (
    <div className="card">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between text-left"
      >
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400">
          Detected but skipped <span className="text-slate-600">({skipped.length})</span>
        </h2>
        <span className="text-slate-500">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div className="mt-3 space-y-1.5">
          {skipped.length === 0 && (
            <p className="text-xs text-slate-500">no skipped changes — nothing hidden</p>
          )}
          {skipped.map((c) => (
            <div
              key={c.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-ink-800 bg-ink-800/30 px-3 py-1.5"
            >
              <span className="font-mono text-xs text-slate-400">
                {c.dependency_name} {c.latest_version}
              </span>
              <span className="text-xs text-slate-500">
                {c.triage_reason ?? "low relevance"}
                <span className="ml-2 text-slate-600">({fmtTime(c.detected_at)})</span>
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export interface GithubConnection {
  token: string;
  owner: string;
  repo: string;
}

export default function DashboardPage({
  onSelect,
  onTriggered,
}: {
  onSelect: (id: string) => void;
  onTriggered: (id: string) => void;
}) {
  const [investigations, setInvestigations] = useState<Investigation[]>([]);
  const [changes, setChanges] = useState<DetectedChange[]>([]);
  const [gh, setGh] = useState<GithubConnection | null>(null);

  useEffect(() => {
    let alive = true;
    const refresh = async () => {
      try {
        const [invs, chs] = await Promise.all([api.investigations(), api.detectedChanges()]);
        if (!alive) return;
        setInvestigations(invs);
        setChanges(chs);
      } catch {
        /* transient — next tick retries */
      }
    };
    refresh();
    const t = setInterval(refresh, 3000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-2xl font-bold text-white">Investigations</h1>
        <p className="mt-1 text-sm text-slate-500">
          Every verdict is grounded in real container execution — baseline vs candidate, same repo, same tests.
        </p>
      </header>

      <GithubConnectCard gh={gh} onConnect={setGh} onDisconnect={() => setGh(null)} />

      <TriggerForm onTriggered={onTriggered} github={gh} />

      <div className="card">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
          Past investigations
        </h2>
        {investigations.length === 0 ? (
          <p className="text-sm text-slate-500">
            none yet — add deps to the watchlist and poll discovery, or trigger one manually
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-ink-700 text-left text-xs uppercase tracking-wider text-slate-500">
                  <th className="py-2 pr-4">Dependency</th>
                  <th className="py-2 pr-4">Bump</th>
                  <th className="py-2 pr-4">Status</th>
                  <th className="py-2 pr-4">Verdict</th>
                  <th className="py-2 pr-4">Score</th>
                  <th className="py-2 pr-4">Trigger</th>
                  <th className="py-2">When</th>
                </tr>
              </thead>
              <tbody>
                {investigations.map((inv) => (
                  <tr
                    key={inv.id}
                    onClick={() => onSelect(inv.id)}
                    className="cursor-pointer border-b border-ink-800/60 hover:bg-ink-800/40"
                  >
                    <td className="py-2.5 pr-4 font-mono text-slate-200">{inv.dependency_name}</td>
                    <td className="py-2.5 pr-4 font-mono text-xs text-slate-400">
                      {inv.baseline_version} → {inv.candidate_version}
                    </td>
                    <td className="py-2.5 pr-4">
                      <StatusBadge status={inv.status} />
                    </td>
                    <td className="py-2.5 pr-4">
                      <VerdictBadge verdict={inv.verdict} />
                    </td>
                    <td className="py-2.5 pr-4 font-mono text-slate-300">
                      {inv.compatibility_score !== null ? (inv.compatibility_score * 100).toFixed(1) : "—"}
                    </td>
                    <td className="py-2.5 pr-4 text-xs text-slate-500">{inv.trigger}</td>
                    <td className="py-2.5 text-xs text-slate-500">{fmtTime(inv.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <SkippedChanges changes={changes} />
      <WatchlistPanel />
    </div>
  );
}
