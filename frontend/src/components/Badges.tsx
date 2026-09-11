import { STATUS_STYLES, VERDICT_STYLES } from "../api";

export function VerdictBadge({ verdict }: { verdict: string | null }) {
  if (!verdict) {
    return (
      <span className="inline-flex items-center rounded-md border border-slate-600/40 bg-slate-700/20 px-2 py-0.5 text-xs font-medium text-slate-400">
        pending
      </span>
    );
  }
  const style = VERDICT_STYLES[verdict] ?? "border-slate-500/40 bg-slate-500/10 text-slate-300";
  return (
    <span className={`inline-flex items-center rounded-md border px-2 py-0.5 font-mono text-xs font-semibold ${style}`}>
      {verdict}
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const style = STATUS_STYLES[status] ?? STATUS_STYLES.pending;
  return (
    <span className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium ${style}`}>
      {status}
    </span>
  );
}
