import { useCallback, useEffect, useRef, useState } from "react";
import { api, type InvestigationDetail } from "../api";
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

/* ------------------------------------------------------------ step timeline */

function StepTimeline({ detail, tick }: { detail: InvestigationDetail | null; tick: number }) {
  const events = detail?.events ?? [];
  const seenSteps = new Set(events.map((e) => e.step));
  const currentStep = detail?.investigation.current_step;
  const status = detail?.investigation.status;

  const stepState = (step: string): "done" | "active" | "pending" => {
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
      ? "border-[#9DB894] bg-[#DDE7D7] text-[#4A6B45]"
      : state === "active"
        ? "border-[#2F2F2E] bg-[#2F2F2E] text-white animate-pulse"
        : "border-[#E1DFDC] bg-[#F9F8F6] text-[#A6A49E]";

  const label = (state: string) =>
    state === "pending" ? "text-[#A6A49E]" : "text-[#3C3C3B]";

  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-2.5 sm:grid-cols-5" data-tick={tick}>
      {PIPELINE_STEPS.map((step) => {
        const state = stepState(step);
        return (
          <div key={step} className="flex items-center gap-2">
            <span
              className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-[10px] font-bold ${dot(state)}`}
            >
              {state === "done" ? "✓" : state === "active" ? "•" : ""}
            </span>
            <span className={`font-mono text-[11px] tracking-tight ${label(state)}`}>{step}</span>
          </div>
        );
      })}
    </div>
  );
}

/* ---------------------------------------------------------------- event log */

function EventLog({ detail }: { detail: InvestigationDetail | null }) {
  const events = detail?.events ?? [];
  const fmt = (t: number) => new Date(t * 1000).toLocaleTimeString("en-GB", { hour12: false });
  const levelColor = (level: string) =>
    level === "error" ? "text-[#A94B43]" : level === "warn" ? "text-[#8A7020]" : "text-[#7A7873]";
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [events.length]);

  return (
    <div className="max-h-72 overflow-y-auto rounded-2xl border border-[#EAE9E6] bg-[#F1EFEC]/60 p-3 font-mono text-xs">
      {events.length === 0 && <p className="text-[#A6A49E]">waiting for events…</p>}
      {events.map((e) => (
        <div key={e.id} className="flex gap-2 py-0.5">
          <span className="shrink-0 text-[#A6A49E]">{fmt(e.created_at)}</span>
          <span className="shrink-0 font-semibold text-[#2F2F2E]">{e.step}</span>
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

/* -------------------------------------------------------- comparison table */

function ComparisonTable({ comparison }: { comparison: InvestigationDetail["comparison"] }) {
  if (!comparison)
    return <p className="text-sm text-[#7A7873]">comparison not available yet</p>;
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
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[#E1DFDC] text-left text-[11px] uppercase tracking-wider text-[#7A7873]">
              <th className="py-2 pr-4 font-medium">Metric</th>
              <th className="py-2 pr-4 text-right font-medium">Baseline</th>
              <th className="py-2 pr-4 text-right font-medium">Candidate</th>
              <th className="py-2 pr-4 text-right font-medium">Δ abs</th>
              <th className="py-2 text-right font-medium">Δ %</th>
            </tr>
          </thead>
          <tbody className="font-mono">
            {Object.entries(comparison.metrics).map(([key, m]) => {
              const worse =
                key.includes("latency") || key === "error_rate" || key.includes("failed") || key.includes("errors")
                  ? m.absolute_delta > 0
                  : m.absolute_delta < 0;
              const deltaColor =
                m.absolute_delta === 0
                  ? "text-[#A6A49E]"
                  : worse
                    ? "text-[#A94B43]"
                    : "text-[#4A6B45]";
              return (
                <tr key={key} className="border-b border-[#EAE9E6]">
                  <td className="py-2 pr-4 font-sans text-[#3C3C3B]">{label[key] ?? key}</td>
                  <td className="py-2 pr-4 text-right text-[#7A7873]">{fmtNum(m.baseline, 4)}</td>
                  <td className="py-2 pr-4 text-right text-[#3C3C3B]">{fmtNum(m.candidate, 4)}</td>
                  <td className={`py-2 pr-4 text-right ${deltaColor}`}>
                    {m.absolute_delta > 0 ? "+" : ""}
                    {fmtNum(m.absolute_delta, 4)}
                  </td>
                  <td className={`py-2 text-right ${deltaColor}`}>
                    {m.percentage_delta === null
                      ? "—"
                      : `${m.percentage_delta > 0 ? "+" : ""}${m.percentage_delta}%`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="mt-4 grid grid-cols-3 gap-3">
        {(
          [
            ["Functional", comparison.scores.functional_score],
            ["Performance", comparison.scores.performance_score],
            ["Overall", comparison.scores.overall_score],
          ] as const
        ).map(([lbl, score]) => (
          <div
            key={lbl}
            className="rounded-2xl border border-[#EAE9E6] bg-[#F9F8F6] p-3 text-center"
          >
            <p className="text-[11px] uppercase tracking-wider text-[#7A7873]">{lbl}</p>
            <p className="mt-1 font-mono text-xl font-semibold text-[#3C3C3B]">
              {(score * 100).toFixed(1)}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- env health */

function EnvHealth({ detail }: { detail: InvestigationDetail | null }) {
  const health = detail?.comparison?.environment_health;
  if (!health) return null;
  return (
    <div className="grid grid-cols-2 gap-3">
      {(["baseline", "candidate"] as const).map((env) => {
        const h = health[env];
        if (!h) return null;
        return (
          <div key={env} className="rounded-2xl border border-[#EAE9E6] bg-[#F9F8F6] p-3">
            <p className="font-mono text-[11px] uppercase tracking-wider text-[#7A7873]">{env}</p>
            <p className="mt-1 text-sm text-[#3C3C3B]">
              build {h.build_success ? "✅" : "❌"} · startup {h.startup_success ? "✅" : "❌"}
            </p>
          </div>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------ verdict card */

function VerdictCard({ detail }: { detail: InvestigationDetail | null }) {
  const decision = detail?.decision;
  const inv = detail?.investigation;
  if (!inv) return null;
  if (!decision && inv.status === "running") {
    return (
      <div className="rounded-2xl border border-[#EAE9E6] bg-[#F9F8F6] p-6">
        <p className="animate-pulse font-mono text-sm text-[#7A7873]">
          reasoning over measured evidence…
        </p>
      </div>
    );
  }
  if (!decision) return null;
  return (
    <div className="rounded-2xl border border-[#EAE9E6] bg-[#F9F8F6] p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-[11px] uppercase tracking-wider text-[#7A7873]">Verdict</p>
          <div className="mt-1 flex items-center gap-3">
            <VerdictBadge verdict={decision.verdict} />
            <span className="font-mono text-xs text-[#7A7873]">
              confidence {(decision.confidence * 100).toFixed(0)}% · {decision.decided_by}
            </span>
          </div>
        </div>
        {inv.compatibility_score !== null && (
          <div className="text-right">
            <p className="text-[11px] uppercase tracking-wider text-[#7A7873]">Score</p>
            <p className="font-mono text-2xl font-bold text-[#3C3C3B]">
              {(inv.compatibility_score * 100).toFixed(1)}
            </p>
          </div>
        )}
      </div>
      <ul className="mt-4 space-y-1.5">
        {decision.reasons.map((r, i) => (
          <li key={i} className="flex gap-2 text-sm text-[#3C3C3B]">
            <span className="text-[#2F2F2E]">›</span> {r}
          </li>
        ))}
      </ul>
      <p className="mt-4 rounded-2xl border border-[#EAE9E6] bg-[#F1EFEC]/60 p-3 text-sm text-[#3C3C3B]">
        <span className="font-semibold">Recommendation: </span>
        {decision.recommendation}
      </p>
      {detail?.action && (
        <div className="mt-3 text-sm">
          {detail.action.issue_url ? (
            <a
              href={detail.action.issue_url}
              target="_blank"
              rel="noreferrer"
              className="font-medium text-[#2F2F2E] underline underline-offset-4 hover:opacity-70"
            >
              GitHub issue #{detail.action.issue_number}
              {detail.action.verified ? " ✓ verified" : " (unverified)"}
            </a>
          ) : detail.action.skipped ? (
            <p className="text-[#7A7873]">GitHub action skipped — {detail.action.skip_reason}</p>
          ) : (
            <p className="text-[#A94B43]">GitHub action failed — {detail.action.error}</p>
          )}
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------- page shell */

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

  const poll = useCallback(async () => {
    try {
      const d = await api.investigationDetail(id);
      setDetail(d);
      setTick((t) => t + 1);
      setError(null);
    } catch (e) {
      // 404 = wrong id or another account's run — stop hammering, show a calm message.
      setError(String(e instanceof Error ? e.message : e));
      if (String(e).includes("404")) {
        setDetail(null);
      }
    }
  }, [id]);

  useEffect(() => {
    poll();
    const timer = setInterval(poll, 1500);
    return () => clearInterval(timer);
  }, [poll]);

  const inv = detail?.investigation;
  const notFound = error !== null && error.includes("404");

  return (
    <div className="alfred-shell min-h-screen">
      <div className="mx-auto max-w-5xl px-4 py-8 sm:px-8">
        <button
          onClick={onBack}
          className="rounded-full border border-[#E1DFDC] bg-[#F9F8F6] px-4 py-1.5 text-xs text-[#7A7873] transition-colors hover:bg-[#F1EFEC] hover:text-[#3C3C3B]"
        >
          ← All investigations
        </button>

        {notFound && (
          <div className="mt-6 rounded-2xl border border-[#EAE9E6] bg-[#F9F8F6] p-8 text-center">
            <p className="text-sm font-medium text-[#3C3C3B]">
              This investigation isn't available.
            </p>
            <p className="mx-auto mt-1 max-w-md text-xs leading-relaxed text-[#7A7873]">
              It may belong to a different account, or the run died before it was created. Head
              back to the dashboard and start a fresh run — every real run gets its own page like
              this one.
            </p>
            <button
              onClick={onBack}
              className="mt-4 rounded-full bg-[#2F2F2E] px-5 py-2 text-sm text-[#F9F8F6] transition-all hover:bg-black"
            >
              Back to dashboard
            </button>
          </div>
        )}

        {!notFound && error && (
          <div className="mt-6 rounded-2xl border border-[#E5C4C0] bg-[#F7E9E7] p-4 text-sm text-[#A94B43]">
            failed to load: {error}
          </div>
        )}

        {inv && (
          <div className="mt-6 rounded-2xl border border-[#EAE9E6] bg-[#F9F8F6] p-6">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <h1 className="truncate font-mono text-xl font-bold text-[#3C3C3B]">
                  {inv.dependency_name}{" "}
                  <span className="text-[#7A7873]">{inv.baseline_version} →</span>{" "}
                  <span className="text-[#2E5AAC]">{inv.candidate_version}</span>
                </h1>
                <p className="mt-1 truncate text-xs text-[#7A7873]" title={inv.repo_source}>
                  {inv.repo_source} · triggered by {inv.trigger}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <StatusBadge status={inv.status} />
                <VerdictBadge verdict={inv.verdict} />
              </div>
            </div>
            {inv.error && (
              <p className="mt-3 rounded-2xl border border-[#E5C4C0] bg-[#F7E9E7] p-3 font-mono text-xs text-[#A94B43]">
                {inv.error}
              </p>
            )}
            <div className="mt-4 border-t border-[#EAE9E6] pt-4">
              <StepTimeline detail={detail} tick={tick} />
            </div>
          </div>
        )}

        <div className="mt-6 grid gap-6 lg:grid-cols-2">
          <div className="rounded-2xl border border-[#EAE9E6] bg-[#F9F8F6] p-6">
            <h2 className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-[#7A7873]">
              Live pipeline log
            </h2>
            <EventLog detail={detail} />
          </div>
          <div className="space-y-6">
            <VerdictCard detail={detail} />
            <EnvHealth detail={detail} />
          </div>
        </div>

        <div className="mt-6 rounded-2xl border border-[#EAE9E6] bg-[#F9F8F6] p-6">
          <h2 className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-[#7A7873]">
            Baseline vs candidate — measured
          </h2>
          <ComparisonTable comparison={detail?.comparison ?? null} />
        </div>
      </div>
    </div>
  );
}
