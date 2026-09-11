import { useEffect, useRef, useState } from "react";
import { api, type Comparison, type InvestigationDetail } from "../api";
import { StatusBadge, VerdictBadge } from "../components/Badges";

const PIPELINE_STEPS = [
  "PREPARE",
  "BUILD",
  "RUN",
  "TEST",
  "WORKLOAD",
  "COMPARE",
  "REASON",
  "ACTION",
  "VERIFY",
  "CLEANUP",
];

function StepTimeline({ detail, tick }: { detail: InvestigationDetail | null; tick: number }) {
  const events = detail?.events ?? [];
  const seenSteps = new Set(events.map((e) => e.step));
  const currentStep = detail?.investigation.current_step;
  const status = detail?.investigation.status;

  const stepState = (step: string): "done" | "active" | "pending" | "skipped" => {
    const idx = PIPELINE_STEPS.indexOf(step);
    const currentIdx = currentStep ? PIPELINE_STEPS.indexOf(currentStep) : -1;
    if (status === "complete" || seenSteps.has(step)) return "done";
    if (status === "running" && idx === currentIdx) return "active";
    if (status === "running" && idx < currentIdx) return "done";
    if (status === "failed" && idx <= currentIdx) return "done";
    return "pending";
  };

  const dot = (state: string) =>
    state === "done"
      ? "bg-signal-green border-signal-green text-ink-950"
      : state === "active"
        ? "bg-signal-blue border-signal-blue text-ink-950 animate-pulse"
        : "border-ink-700 bg-ink-800 text-slate-600";

  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-5" data-tick={tick}>
      {PIPELINE_STEPS.map((step) => {
        const state = stepState(step);
        return (
          <div key={step} className="flex items-center gap-2">
            <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-[10px] font-bold ${dot(state)}`}>
              {state === "done" ? "✓" : state === "active" ? "•" : ""}
            </span>
            <span className={`font-mono text-xs ${state === "pending" ? "text-slate-500" : "text-slate-200"}`}>
              {step}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function EventLog({ detail }: { detail: InvestigationDetail | null }) {
  const events = detail?.events ?? [];
  const fmt = (t: number) =>
    new Date(t * 1000).toLocaleTimeString("en-GB", { hour12: false });
  const levelColor = (level: string) =>
    level === "error" ? "text-signal-red" : level === "warn" ? "text-signal-amber" : "text-slate-400";
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [events.length]);

  return (
    <div className="max-h-72 overflow-y-auto rounded-lg border border-ink-700/60 bg-black/40 p-3 font-mono text-xs">
      {events.length === 0 && <p className="text-slate-600">waiting for events…</p>}
      {events.map((e) => (
        <div key={e.id} className="flex gap-2 py-0.5">
          <span className="shrink-0 text-slate-600">{fmt(e.created_at)}</span>
          <span className="shrink-0 font-semibold text-signal-blue">{e.step}</span>
          <span className={levelColor(e.level)}>{e.message}</span>
        </div>
      ))}
      <div ref={bottom} />
    </div>
  );
}

function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined) return "—";
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: digits });
}

function ComparisonTable({ comparison }: { comparison: Comparison | null }) {
  if (!comparison) return <p className="text-sm text-slate-500">comparison not available yet</p>;
  const label: Record<string, string> = {
    tests_passed: "Tests passed",
    tests_failed: "Tests failed",
    tests_errors: "Test errors",
    latency_p50_ms: "Latency p50 (ms)",
    latency_p95_ms: "Latency p95 (ms)",
    latency_p99_ms: "Latency p99 (ms)",
    error_rate: "Error rate",
    throughput_rps: "Throughput (rps)",
  };
  return (
    <div>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-ink-700 text-left text-xs uppercase tracking-wider text-slate-500">
            <th className="py-2 pr-4">Metric</th>
            <th className="py-2 pr-4 text-right">Baseline</th>
            <th className="py-2 pr-4 text-right">Candidate</th>
            <th className="py-2 pr-4 text-right">Δ abs</th>
            <th className="py-2 text-right">Δ %</th>
          </tr>
        </thead>
        <tbody className="font-mono">
          {Object.entries(comparison.metrics).map(([key, m]) => {
            const worse =
              (key.includes("latency") || key === "error_rate" || key.includes("failed") || key.includes("errors"))
                ? m.absolute_delta > 0
                : m.absolute_delta < 0;
            const deltaColor = m.absolute_delta === 0 ? "text-slate-400" : worse ? "text-signal-red" : "text-signal-green";
            return (
              <tr key={key} className="border-b border-ink-800/60">
                <td className="py-2 pr-4 font-sans text-slate-300">{label[key] ?? key}</td>
                <td className="py-2 pr-4 text-right text-slate-400">{fmtNum(m.baseline, 4)}</td>
                <td className="py-2 pr-4 text-right text-slate-100">{fmtNum(m.candidate, 4)}</td>
                <td className={`py-2 pr-4 text-right ${deltaColor}`}>
                  {m.absolute_delta > 0 ? "+" : ""}{fmtNum(m.absolute_delta, 4)}
                </td>
                <td className={`py-2 text-right ${deltaColor}`}>
                  {m.percentage_delta === null ? "—" : `${m.percentage_delta > 0 ? "+" : ""}${m.percentage_delta}%`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="mt-4 grid grid-cols-3 gap-3">
        {[
          ["Functional", comparison.scores.functional_score],
          ["Performance", comparison.scores.performance_score],
          ["Overall", comparison.scores.overall_score],
        ].map(([label, score]) => (
          <div key={label as string} className="rounded-lg border border-ink-700/60 bg-ink-800/50 p-3 text-center">
            <p className="text-xs uppercase tracking-wider text-slate-500">{label as string}</p>
            <p className="mt-1 font-mono text-xl font-semibold text-slate-100">
              {((score as number) * 100).toFixed(1)}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

function EnvHealth({ detail }: { detail: InvestigationDetail | null }) {
  const health = detail?.comparison?.environment_health;
  if (!health) return null;
  return (
    <div className="grid grid-cols-2 gap-3">
      {["baseline", "candidate"].map((env) => {
        const h = health[env];
        if (!h) return null;
        return (
          <div key={env} className="rounded-lg border border-ink-700/60 bg-ink-800/50 p-3">
            <p className="font-mono text-xs uppercase tracking-wider text-slate-500">{env}</p>
            <p className="mt-1 text-sm">
              build {h.build_success ? "✅" : "❌"} · startup {h.startup_success ? "✅" : "❌"}
            </p>
          </div>
        );
      })}
    </div>
  );
}

function VerdictCard({ detail }: { detail: InvestigationDetail | null }) {
  const decision = detail?.decision;
  const inv = detail?.investigation;
  if (!inv) return null;
  if (!decision && inv.status === "running") {
    return (
      <div className="card flex items-center justify-center">
        <p className="animate-pulse font-mono text-sm text-slate-500">reasoning over measured evidence…</p>
      </div>
    );
  }
  if (!decision) return null;
  return (
    <div className="card">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-wider text-slate-500">Verdict</p>
          <div className="mt-1 flex items-center gap-3">
            <VerdictBadge verdict={decision.verdict} />
            <span className="font-mono text-xs text-slate-500">
              confidence {(decision.confidence * 100).toFixed(0)}% · {decision.decided_by}
            </span>
          </div>
        </div>
        {inv.compatibility_score !== null && (
          <div className="text-right">
            <p className="text-xs uppercase tracking-wider text-slate-500">Score</p>
            <p className="font-mono text-2xl font-bold text-slate-100">
              {(inv.compatibility_score * 100).toFixed(1)}
            </p>
          </div>
        )}
      </div>
      <ul className="mt-4 space-y-1.5">
        {decision.reasons.map((r, i) => (
          <li key={i} className="flex gap-2 text-sm text-slate-300">
            <span className="text-signal-blue">›</span> {r}
          </li>
        ))}
      </ul>
      <p className="mt-4 rounded-lg border border-ink-700/60 bg-ink-800/50 p-3 text-sm text-slate-300">
        <span className="font-semibold text-slate-200">Recommendation: </span>
        {decision.recommendation}
      </p>
      {detail?.action && (
        <div className="mt-3 text-sm">
          {detail.action.issue_url ? (
            <a
              href={detail.action.issue_url}
              target="_blank"
              rel="noreferrer"
              className="text-signal-blue underline decoration-dotted hover:text-white"
            >
              GitHub issue #{detail.action.issue_number}
              {detail.action.verified ? " ✓ verified" : " (unverified)"}
            </a>
          ) : detail.action.skipped ? (
            <p className="text-slate-500">
              GitHub action skipped — {detail.action.skip_reason}
            </p>
          ) : (
            <p className="text-signal-red">GitHub action failed — {detail.action.error}</p>
          )}
        </div>
      )}
    </div>
  );
}

export default function InvestigationPage({
  id,
  onBack,
}: {
  id: string;
  onBack: () => void;
}) {
  const [detail, setDetail] = useState<InvestigationDetail | null>(null);
  const [tick, setTick] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const d = await api.investigationDetail(id);
        if (!alive) return;
        setDetail(d);
        setTick((t) => t + 1);
        setError(null);
      } catch (e) {
        if (alive) setError(String(e));
      }
    };
    poll();
    const timer = setInterval(poll, 1500);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [id]);

  const inv = detail?.investigation;

  return (
    <div className="space-y-5">
      <button onClick={onBack} className="btn-ghost">
        ← All investigations
      </button>

      {error && <div className="card border-signal-red/40 text-sm text-signal-red">failed to load: {error}</div>}

      {inv && (
        <div className="card">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h1 className="font-mono text-xl font-bold text-white">
                {inv.dependency_name}{" "}
                <span className="text-slate-500">{inv.baseline_version} →</span>{" "}
                <span className="text-signal-blue">{inv.candidate_version}</span>
              </h1>
              <p className="mt-1 truncate text-xs text-slate-500" title={inv.repo_source}>
                {inv.repo_source} · triggered by {inv.trigger}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <StatusBadge status={inv.status} />
              <VerdictBadge verdict={inv.verdict} />
            </div>
          </div>
          {inv.error && (
            <p className="mt-3 rounded-lg border border-signal-red/30 bg-signal-red/5 p-2 font-mono text-xs text-signal-red">
              {inv.error}
            </p>
          )}
          <div className="mt-4 border-t border-ink-800 pt-4">
            <StepTimeline detail={detail} tick={tick} />
          </div>
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        <div className="card">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
            Live pipeline log
          </h2>
          <EventLog detail={detail} />
        </div>
        <div className="space-y-5">
          <VerdictCard detail={detail} />
          <EnvHealth detail={detail} />
        </div>
      </div>

      <div className="card">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
          Baseline vs candidate — measured
        </h2>
        <ComparisonTable comparison={detail?.comparison ?? null} />
      </div>
    </div>
  );
}
