import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import DashboardPage from "./pages/Dashboard";
import InvestigationPage from "./pages/Investigation";

function HealthDot() {
  const [docker, setDocker] = useState<boolean | null>(null);
  useEffect(() => {
    api
      .health()
      .then((h) => setDocker(h.docker_available))
      .catch(() => setDocker(false));
  }, []);
  return (
    <span className="flex items-center gap-1.5 text-xs text-slate-500" title={docker ? "docker daemon reachable" : "docker daemon unreachable — pipeline cannot run"}>
      <span className={`h-2 w-2 rounded-full ${docker ? "bg-signal-green" : "bg-signal-red"}`} />
      docker
    </span>
  );
}

export default function App() {
  const [selected, setSelected] = useState<string | null>(null);

  const open = useCallback((id: string) => {
    setSelected(id);
    window.scrollTo({ top: 0 });
  }, []);

  return (
    <div className="min-h-screen bg-gradient-to-b from-ink-950 via-ink-950 to-ink-900">
      <header className="border-b border-ink-800">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <button onClick={() => setSelected(null)} className="flex items-center gap-3 text-left">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-signal-blue/15 font-mono text-lg font-bold text-signal-blue">
              A
            </span>
            <span>
              <span className="block font-mono text-lg font-bold leading-tight text-white">Alfred</span>
              <span className="block text-[11px] leading-tight text-slate-500">
                autonomous release-impact testing agent
              </span>
            </span>
          </button>
          <HealthDot />
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-8">
        {selected ? (
          <InvestigationPage id={selected} onBack={() => setSelected(null)} />
        ) : (
          <DashboardPage onSelect={open} onTriggered={open} />
        )}
      </main>

      <footer className="border-t border-ink-800 py-4 text-center text-xs text-slate-600">
        every number on this dashboard comes from a container that actually ran
      </footer>
    </div>
  );
}
