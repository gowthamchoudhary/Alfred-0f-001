import { useState } from "react";
import { api } from "../api";

type Mode = "login" | "signup";

export default function AuthPage({
  mode: initialMode,
  onSignedIn,
  onBack,
}: {
  mode: Mode;
  onSignedIn: (email: string) => void;
  onBack: () => void;
}) {
  const [mode, setMode] = useState<Mode>(initialMode);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res =
        mode === "signup"
          ? await api.signup(email, password)
          : await api.login(email, password);
      onSignedIn(res.user.email);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="alfred-shell flex min-h-screen items-center justify-center px-4 py-8">
      <div className="w-full max-w-md rounded-[2rem] border border-[#EAE9E6] bg-[#F9F8F6] px-8 py-12 sm:px-12">
        <button onClick={onBack} className="text-xs text-[#7A7873] transition-colors hover:text-[#3C3C3B]">
          ← back
        </button>

        <img
          src="/logos/alfred.png"
          alt="Alfred logo"
          className="mt-8 h-12 w-12 rounded-2xl object-cover shadow-[0_10px_30px_-12px_rgba(60,60,59,0.35)]"
        />

        <h1 className="mt-6 text-3xl font-normal tracking-tight text-[#2F2F2E]">
          {mode === "signup" ? "Create your account" : "Welcome back"}
        </h1>
        <p className="mt-2 text-sm text-[#7A7873]">
          {mode === "signup"
            ? "Test before you deploy — with real metrics, not guesses."
            : "Sign in to your Alfred workspace."}
        </p>

        <form onSubmit={submit} className="mt-8 space-y-3">
          <input
            type="email"
            required
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            className="w-full rounded-full border border-[#E1DFDC] bg-white px-5 py-3 text-sm text-[#3C3C3B] placeholder-[#A6A49E] outline-none transition-colors focus:border-[#B8B6B0]"
          />
          <input
            type="password"
            required
            minLength={8}
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === "signup" ? "new-password" : "current-password"}
            className="w-full rounded-full border border-[#E1DFDC] bg-white px-5 py-3 text-sm text-[#3C3C3B] placeholder-[#A6A49E] outline-none transition-colors focus:border-[#B8B6B0]"
          />
          {error && <p className="px-2 text-xs text-[#B4544E]">{error}</p>}
          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-full bg-[#2F2F2E] px-5 py-3 text-sm text-[#F9F8F6] transition-all hover:bg-black disabled:opacity-50"
          >
            {busy ? "…" : mode === "signup" ? "Create account" : "Log in"}
          </button>
        </form>

        <p className="mt-6 text-center text-xs text-[#7A7873]">
          {mode === "signup" ? "Already have an account?" : "New to Alfred?"}{" "}
          <button
            onClick={() => {
              setMode(mode === "signup" ? "login" : "signup");
              setError(null);
            }}
            className="text-[#3C3C3B] underline underline-offset-2 hover:opacity-70"
          >
            {mode === "signup" ? "Log in" : "Create one"}
          </button>
        </p>
      </div>
    </div>
  );
}
