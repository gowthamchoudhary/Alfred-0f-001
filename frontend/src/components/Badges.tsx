// Light editorial badge styles shared across the dashboard pages.
// (The old maps in api.ts were dark-theme leftovers.)

const VERDICT_STYLES: Record<string, string> = {
  SAFE: "border-[#C9D6C6] bg-[#EAEFE7] text-[#4A6B45]",
  SAFE_WITH_REVIEW: "border-[#E4D9B0] bg-[#F4F0E1] text-[#8A7020]",
  MODERATE_RISK: "border-[#ECD3BC] bg-[#F8EFE4] text-[#9A5B27]",
  HIGH_RISK: "border-[#E5C4C0] bg-[#F7E9E7] text-[#A94B43]",
  INCOMPATIBLE: "border-[#D8A5A0] bg-[#F2DBD8] text-[#8C3B34]",
};

const STATUS_STYLES: Record<string, string> = {
  running: "border-[#BFD3E8] bg-[#EAF1F9] text-[#2E5AAC]",
  complete: "border-[#C9D6C6] bg-[#EAEFE7] text-[#4A6B45]",
  failed: "border-[#E5C4C0] bg-[#F7E9E7] text-[#A94B43]",
  pending: "border-[#E1DFDC] bg-[#F1EFEC] text-[#7A7873]",
};

export function VerdictBadge({ verdict }: { verdict: string | null }) {
  if (!verdict) {
    return (
      <span className="inline-flex items-center rounded-full border border-[#E1DFDC] bg-[#F1EFEC] px-2.5 py-0.5 text-xs font-medium text-[#7A7873]">
        pending
      </span>
    );
  }
  const style = VERDICT_STYLES[verdict] ?? "border-[#E1DFDC] bg-[#F1EFEC] text-[#7A7873]";
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 font-mono text-xs font-semibold ${style}`}>
      {verdict}
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const style = STATUS_STYLES[status] ?? STATUS_STYLES.pending;
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${style}`}>
      {status}
      {status === "running" && <span className="ml-1.5 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-[#2E5AAC]" />}
    </span>
  );
}
