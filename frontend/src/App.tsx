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
        <DashboardPage
          user={user}
          onSelect={open}
          onTriggered={open}
          onSignOut={signOut}
        />
      )}

      {route.name === "investigation" && user && (
        <InvestigationPage id={route.id} onBack={() => navigate({ name: "dashboard" })} />
      )}
    </>
  );
}
