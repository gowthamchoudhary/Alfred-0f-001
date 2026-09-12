import { useCallback, useEffect, useState } from "react";
import { api, type AuthUser } from "./api";
import LandingPage from "./pages/Landing";
import AuthPage from "./pages/Auth";
import DashboardPage from "./pages/Dashboard";
import InvestigationPage from "./pages/Investigation";

type Route =
  | { name: "landing" }
  | { name: "auth"; mode: "login" | "signup" }
  | { name: "dashboard" }
  | { name: "investigation"; id: string };

function parseHash(): Route {
  const hash = window.location.hash.replace(/^#/, "");
  if (hash.startsWith("/login")) return { name: "auth", mode: "login" };
  if (hash.startsWith("/signup")) return { name: "auth", mode: "signup" };
  if (hash.startsWith("/investigation/")) {
    return { name: "investigation", id: hash.split("/")[2] };
  }
  if (hash.startsWith("/app")) return { name: "dashboard" };
  return { name: "landing" };
}

function routeToHash(route: Route): string {
  switch (route.name) {
    case "auth":
      return route.mode === "login" ? "#/login" : "#/signup";
    case "dashboard":
      return "#/app";
    case "investigation":
      return `#/investigation/${route.id}`;
    default:
      return "#/";
  }
}

function HealthDot() {
  const [docker, setDocker] = useState<boolean | null>(null);
  useEffect(() => {
    api
      .health()
      .then((h) => setDocker(h.docker_available))
      .catch(() => setDocker(false));
  }, []);
  return (
    <span
      className="flex items-center gap-1.5 text-xs text-slate-500"
      title={docker ? "docker daemon reachable" : "docker daemon unreachable — pipeline cannot run"}
    >
      <span className={`h-2 w-2 rounded-full ${docker ? "bg-signal-green" : "bg-signal-red"}`} />
      docker
    </span>
  );
}

export default function App() {
  const [route, setRoute] = useState<Route>(() => parseHash());
  const [user, setUser] = useState<AuthUser | null>(null);
  const [checkedAuth, setCheckedAuth] = useState(false);

  const navigate = useCallback((next: Route) => {
    window.location.hash = routeToHash(next);
    window.scrollTo({ top: 0 });
  }, []);

  useEffect(() => {
    const onHash = () => setRoute(parseHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  // Restore the session once on load.
  useEffect(() => {
    api.me().then((res) => {
      if (res?.user) setUser(res.user);
      setCheckedAuth(true);
    });
  }, []);

  const open = useCallback(
    (id: string) => {
      setRoute({ name: "investigation", id });
      window.scrollTo({ top: 0 });
    },
    [],
  );

  const signOut = useCallback(async () => {
    await api.logout().catch(() => undefined);
    setUser(null);
    navigate({ name: "landing" });
  }, [navigate]);

  // Wait for the session check before deciding what a protected route shows.
  const onProtected = route.name === "dashboard" || route.name === "investigation";
  if (onProtected && !checkedAuth) {
    return <div className="alfred-shell min-h-screen" />;
  }
  if (onProtected && !user) {
    return (
      <AuthPage
        mode="login"
        onSignedIn={(email) => {
          setUser({ id: "", email });
          navigate({ name: "dashboard" });
        }}
        onBack={() => navigate({ name: "landing" })}
      />
    );
  }

  return (
    <>
      {route.name === "landing" && (
        <LandingPage
          onAuth={(mode) => navigate({ name: "auth", mode })}
        />
      )}

      {route.name === "auth" && (
        <AuthPage
          key={route.mode}
          mode={route.mode}
          onSignedIn={(email) => {
            setUser({ id: "", email });
            navigate({ name: "dashboard" });
          }}
          onBack={() => navigate({ name: "landing" })}
        />
      )}

      {route.name === "dashboard" && user && (
        <div className="min-h-screen bg-gradient-to-b from-ink-950 via-ink-950 to-ink-900">
          <header className="border-b border-ink-800">
            <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
              <div className="flex items-center gap-3">
                <button onClick={() => navigate({ name: "dashboard" })} className="flex items-center gap-3 text-left">
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
              </div>
              <div className="flex items-center gap-4">
                <HealthDot />
                <span className="text-xs text-slate-400">{user.email}</span>
                <button onClick={signOut} className="btn-ghost text-xs">
                  Sign out
                </button>
              </div>
            </div>
          </header>

          <main className="mx-auto max-w-6xl px-6 py-8">
            <DashboardPage onSelect={open} onTriggered={open} />
          </main>

          <footer className="border-t border-ink-800 py-4 text-center text-xs text-slate-600">
            every number on this dashboard comes from a container that actually ran
          </footer>
        </div>
      )}

      {route.name === "investigation" && user && (
        <div className="min-h-screen bg-gradient-to-b from-ink-950 via-ink-950 to-ink-900">
          <header className="border-b border-ink-800">
            <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
              <button onClick={() => navigate({ name: "dashboard" })} className="flex items-center gap-3 text-left">
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
              <div className="flex items-center gap-4">
                <HealthDot />
                <span className="text-xs text-slate-400">{user.email}</span>
                <button onClick={signOut} className="btn-ghost text-xs">
                  Sign out
                </button>
              </div>
            </div>
          </header>

          <main className="mx-auto max-w-6xl px-6 py-8">
            <InvestigationPage id={route.id} onBack={() => navigate({ name: "dashboard" })} />
          </main>

          <footer className="border-t border-ink-800 py-4 text-center text-xs text-slate-600">
            every number on this dashboard comes from a container that actually ran
          </footer>
        </div>
      )}
    </>
  );
}
