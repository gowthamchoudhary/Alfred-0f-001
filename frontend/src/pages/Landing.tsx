import { useEffect, useRef, useState } from "react";

type AuthMode = "login" | "signup";

/* ------------------------------------------------------------- logo slots */

const LOGO_SLOTS = ["anakin", "groq", "github", "docker", "supabase"] as const;

function LogoSlot({ slot }: { slot: string }) {
  const [src, setSrc] = useState<string | null>(null);

  useEffect(() => {
    // Drop the real asset at frontend/public/logos/<slot>.<ext> and it appears
    // here automatically — no code change needed.
    // NOTE: both the sandbox SPA fallback and vercel.json's rewrite return a
    // 200 (serving index.html) for MISSING files — so res.ok alone is a false
    // positive. Only accept a response whose content-type is really an image.
    let alive = true;
    const exts = ["svg", "png", "webp", "jpg"];
    (async () => {
      for (const ext of exts) {
        const url = `/logos/${slot}.${ext}`;
        try {
          const res = await fetch(url, { method: "HEAD" });
          const type = res.headers.get("content-type") ?? "";
          if (res.ok && type.startsWith("image/")) {
            if (alive) setSrc(url);
            return;
          }
        } catch {
          /* keep probing */
        }
      }
    })();
    return () => {
      alive = false;
    };
  }, [slot]);

  if (src) {
    return <img src={src} alt={`${slot} logo`} className="h-8 w-auto max-w-[150px] object-contain opacity-90" />;
  }
  return (
    <span className="select-none rounded-full border border-dashed border-[#D8D6D0] px-5 py-2 text-[11px] tracking-wide text-[#A6A49E]">
      logo slot — {slot}
    </span>
  );
}

function LogoStrip() {
  return (
    <div className="border-y border-[#EAE9E6] bg-[#F1F0EC]">
      <div className="grid grid-cols-2 items-center justify-items-center gap-y-10 px-8 py-14 sm:grid-cols-3 lg:grid-cols-5 lg:py-16">
        {LOGO_SLOTS.map((slot) => (
          <LogoSlot key={slot} slot={slot} />
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------- shell */

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="alfred-shell min-h-screen px-2.5 py-4 sm:px-4 sm:py-6 lg:px-6">
      {/* ONE continuous inner page — a single large sheet floating on the outer background */}
      <div className="mx-auto max-w-[1200px] overflow-hidden rounded-[2.5rem] border border-[#EAE9E6] bg-[#F9F8F6] shadow-[0_30px_80px_-48px_rgba(60,60,59,0.28)]">
        {children}
      </div>
    </div>
  );
}

/* ------------------------------------------------------- scroll-reveal hook */

function useReveal(): (node: HTMLElement | null) => void {
  const observer = useRef<IntersectionObserver | null>(null);

  useEffect(() => {
    observer.current = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            observer.current?.unobserve(entry.target);
          }
        }
      },
      { threshold: 0.15 },
    );
    // Observe everything currently marked .reveal on the page.
    document.querySelectorAll<HTMLElement>(".reveal:not(.is-visible)").forEach((el) => {
      observer.current?.observe(el);
    });
    return () => observer.current?.disconnect();
  }, []);

  return (node) => {
    if (node && !node.classList.contains("is-visible")) {
      observer.current?.observe(node);
    }
  };
}

/* ------------------------------------------------------------------ navbar */

function Navbar({ onAuth }: { onAuth: AuthModeDispatch }) {
  return (
    <header className="flex items-center justify-between px-6 pt-6 sm:px-10">
      <div className="flex flex-wrap items-center gap-2">
        <span className="flex items-center gap-2 rounded-full bg-[#EAE9E6] py-1 pl-1.5 pr-4">
          <img src="/logos/alfred.png" alt="Alfred logo" className="h-6 w-6 rounded-full object-cover" />
          <span className="text-xs font-medium text-[#3C3C3B]">Alfred</span>
        </span>
        <a
          href="#how-it-works"
          className="rounded-full border border-[#E1DFDC] bg-[#F9F9F6] px-4 py-1.5 text-xs text-[#3C3C3B] transition-colors hover:bg-[#F1F0EC]"
        >
          How it works
        </a>
        <a
          href="#how-to-use"
          className="rounded-full border border-[#E1DFDC] bg-[#F9F9F6] px-4 py-1.5 text-xs text-[#3C3C3B] transition-colors hover:bg-[#F1F0EC]"
        >
          How to use
        </a>
      </div>
      <nav className="flex items-center gap-1.5 text-xs text-[#3C3C3B]">
        <a href="#" className="transition-opacity hover:opacity-70">GitHub</a>
        <span className="text-[#B8B6B0]">/</span>
        <a href="#" className="transition-opacity hover:opacity-70">Docs</a>
        <span className="text-[#B8B6B0]">/</span>
        <button onClick={() => onAuth("login")} className="transition-opacity hover:opacity-70">Login</button>
      </nav>
    </header>
  );
}

type AuthModeDispatch = (mode: AuthMode) => void;

/* -------------------------------------------------------------------- hero */

function Orb() {
  return (
    <div className="relative mx-auto h-28 w-28 sm:h-32 sm:w-32">
      <div className="orb-halo absolute -inset-8 rounded-full" />
      <div className="orb orb-core absolute inset-0 rounded-full" />
    </div>
  );
}

function Hero({ onAuth }: { onAuth: AuthModeDispatch }) {
  return (
    <section className="flex flex-col items-center px-6 pb-20 pt-10 text-center sm:pb-24 sm:pt-14">
      <Orb />
      <h1 className="alfred-enter mt-10 text-5xl font-normal leading-[1.05] tracking-tight text-[#2F2F2E] sm:text-6xl">
        Test before you
        <br />
        deploy.
      </h1>
      <p className="alfred-enter mt-6 max-w-xl text-sm leading-relaxed text-[#7A7873] sm:text-[15px]">
        Alfred automatically detects updates, tests them on your application, and tells you
        exactly what changes — with real metrics, not guesses.
      </p>
      <div className="alfred-enter mt-10 flex flex-wrap items-center justify-center gap-3">
        <button
          onClick={() => onAuth("signup")}
          className="rounded-full bg-[#2F2F2E] px-9 py-3.5 text-sm text-[#F9F8F6] transition-all hover:bg-black"
        >
          Get started
        </button>
        <a
          href="#how-to-use"
          className="rounded-full border border-[#E1DFDC] bg-[#F9F8F6] px-9 py-3.5 text-sm text-[#3C3C3B] transition-colors hover:bg-[#F1F0EC]"
        >
          See how it works ↓
        </a>
      </div>
    </section>
  );
}

/* ------------------------------------------------- how it works (pipeline) */

const PIPELINE = [
  {
    n: "01",
    t: "Watch",
    d: "Alfred's background poller checks every dependency on your watchlist — PyPI feeds and GitHub releases via Anakin — on a fixed schedule.",
  },
  {
    n: "02",
    t: "Triage",
    d: "A cheap deterministic filter: major bumps and breaking-change language get accepted, pre-releases and not-actually-newer versions get skipped. Ambiguous cases get one LLM relevance check.",
  },
  {
    n: "03",
    t: "Prepare",
    d: "Your repo is cloned twice. Only the candidate copy gets its requirements.txt bumped to the new version — the baseline stays exactly as you run it today.",
  },
  {
    n: "04",
    t: "Build & run",
    d: "Both copies are built from their own Dockerfile and run as real containers with resource limits, on separate ports. A build failure is itself a valid, reportable result.",
  },
  {
    n: "05",
    t: "Test & load",
    d: "Your own pytest suite runs inside each container. Then a real concurrent HTTP workload — your endpoints, your payloads, your concurrency — fires at both.",
  },
  {
    n: "06",
    t: "Compare",
  d: "Pure deterministic math, no AI: pass/fail counts, p50/p95/p99 latency, error rate, throughput → absolute and percentage deltas plus a compatibility score.",
  },
  {
    n: "07",
    t: "Research",
    d: "Anakin agentic-search and GitHub release data pull migration guides and breaking-change context for the exact dependency and version pair.",
  },
  {
    n: "08",
    t: "Reason",
    d: "One LLM call reads the measured evidence and web research and writes the verdict — SAFE, SAFE_WITH_REVIEW, MODERATE_RISK, or HIGH_RISK — with confidence and reasons.",
  },
  {
    n: "09",
    t: "Act & verify",
    d: "The verdict is posted to your repo as a real GitHub issue via the REST API, then fetched back to confirm it exists. The container pair is always cleaned up.",
  },
];

function PipelineFlow() {
  const reveal = useReveal();
  return (
    <div className="relative mx-auto max-w-2xl">
      {/* vertical connector with a traveling pulse — visual thread through every step */}
      <div className="flow-line absolute left-[19px] top-3 bottom-3 w-px sm:left-1/2" aria-hidden />
      <ol className="space-y-10">
        {PIPELINE.map((step, i) => (
          <li
            key={step.n}
            ref={reveal}
            className={`relative flex items-start gap-5 ${i % 2 === 1 ? "sm:flex-row-reverse" : ""}`}
          >
            <span className="z-10 flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-[#E1DFDC] bg-[#F9F8F6] font-mono text-xs text-[#3C3C3B] shadow-sm">
              {step.n}
            </span>
            <div className="flex-1 rounded-2xl border border-[#EAE9E6] bg-[#F1EFEC]/60 px-5 py-4 text-left">
              <h4 className="text-sm font-medium text-[#2F2F2E]">{step.t}</h4>
              <p className="mt-1.5 text-[13px] leading-relaxed text-[#7A7873]">{step.d}</p>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

function HowItWorks() {
  return (
    <section id="how-it-works" className="px-6 pb-20 pt-20 sm:px-10">
      <div className="relative border-t border-[#EAE9E6]">
        <span className="absolute left-1/2 top-0 -translate-x-1/2 -translate-y-1/2 rounded-full border border-[#E1DFDC] bg-[#F9F8F6] px-4 py-1 text-xs text-[#3C3C3B]">
          The pipeline
        </span>
      </div>
      <h2 className="reveal mt-16 text-center text-3xl font-normal tracking-tight text-[#2F2F2E] sm:text-4xl">
        What Alfred does the moment a new version drops.
      </h2>
      <p className="reveal mx-auto mt-4 max-w-xl text-center text-sm text-[#7A7873]">
        Nine steps, zero human triggering. Every number comes from a container that actually ran —
        the AI interprets the evidence, it never invents it.
      </p>
      <div className="mt-14">
        <PipelineFlow />
      </div>
    </section>
  );
}

/* ------------------------------------------------- how to use (user guide) */

const GUIDE = [
  {
    step: "1",
    title: "Create your account",
    body: "Sign up with email and password. That is the only identity Alfred needs — GitHub is an integration, not a login.",
  },
  {
    step: "2",
    title: "Prepare your repo (the one-time contract)",
    body: "Alfred runs any repository that follows one minimal convention — nothing is hardcoded to a demo app. Your repo needs four things:",
    bullets: [
      "Dockerfile — must expose the app on $PORT",
      "requirements.txt — pinned versions; this is the file Alfred bumps",
      "tests/ — a pytest suite that runs inside the container",
      "alfred.yaml — which dependency to watch, which endpoint to hit, how hard to hit it",
    ],
    code: `dependency:
  name: openai
  current: "1.99.0"
workload:
  endpoint: /chat
  method: POST
  concurrency: 20
  requests: 500
  payloads:
    - { "message": "Summarize this refund policy." }`,
  },
  {
    step: "3",
    title: "Get a GitHub token (2 minutes, once)",
    body: "The verdict issue must be posted to your repo as you — so Alfred needs a personal access token. Generate a fine-grained token in two clicks:",
    bullets: [
      "Open github.com/settings/personal-access-tokens/new",
      "Repository access: only select the repo that should receive verdict issues",
      "Permissions: Contents → read-only (that is enough to read releases; the token is used for nothing else)",
      "Optional metadata: read — leave everything else unchecked",
      "Copy the github_pat_… value. You will paste it exactly once, below.",
    ],
    note: "Security model: the token is stored Fernet-encrypted at rest on your watchlist entry, decrypted in memory only for the duration of one run, never returned by any API endpoint, never logged, and never written to the database in plaintext. Rotate by re-registering; delete the watchlist entry and it is gone.",
  },
  {
    step: "4",
    title: "Watch a dependency",
    body: "In the dashboard, open Watchlist → add a dependency (e.g. openai). Paste your token, the issue destination (owner/repo), and you are done. From this moment the loop is fully automatic.",
  },
  {
    step: "5",
    title: "Let Alfred run — or run it yourself",
    body: "The background poller checks your watchlist every cycle. When a new release appears, triage decides whether it matters, and accepted changes trigger a full investigation with no human present. You can also trigger one manually: Investigations → point Alfred at any contract-compliant repo path or git URL and a target version.",
  },
  {
    step: "6",
    title: "Read the verdict",
    body: "Each investigation shows a live event timeline (every pipeline step, timestamped), real baseline-vs-candidate metrics, the compatibility score, the AI verdict with reasons, and the verified GitHub issue link. Skipped releases are visible too — nothing is hidden.",
  },
];

function HowToUse() {
  const reveal = useReveal();
  return (
    <section id="how-to-use" className="px-6 pb-20 pt-4 sm:px-10">
      <h2 className="reveal text-center text-3xl font-normal tracking-tight text-[#2F2F2E] sm:text-4xl">
        How to use Alfred — end to end.
      </h2>
      <p className="reveal mx-auto mt-4 max-w-xl text-center text-sm text-[#7A7873]">
        Everything you need: the repo contract, the GitHub token, and the automatic loop.
      </p>
      <div className="mx-auto mt-14 max-w-3xl space-y-5">
        {GUIDE.map((g) => (
          <div
            key={g.step}
            ref={reveal}
            className="rounded-2xl border border-[#EAE9E6] bg-[#F1EFEC]/60 p-6 sm:p-8"
          >
            <div className="flex items-center gap-4">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#2F2F2E] text-sm text-[#F9F8F6]">
                {g.step}
              </span>
              <h3 className="text-base font-medium text-[#2F2F2E]">{g.title}</h3>
            </div>
            <p className="mt-4 text-sm leading-relaxed text-[#7A7873]">{g.body}</p>
            {g.bullets && (
              <ul className="mt-3 space-y-1.5">
                {g.bullets.map((b) => (
                  <li key={b} className="flex gap-2 text-[13px] leading-relaxed text-[#7A7873]">
                    <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-[#A6A49E]" />
                    <span>{b}</span>
                  </li>
                ))}
              </ul>
            )}
            {g.code && (
              <pre className="mt-4 overflow-x-auto rounded-xl border border-[#E1DFDC] bg-[#F9F8F6] p-4 font-mono text-xs leading-relaxed text-[#3C3C3B]">
                {g.code}
              </pre>
            )}
            {g.note && (
              <p className="mt-3 rounded-xl border border-[#DFD9BC] bg-[#F4F0E1] px-4 py-3 text-xs leading-relaxed text-[#8A7020]">
                {g.note}
              </p>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

/* --------------------------------------------------------- feature strip */

function FeatureGrid() {
  const features = [
    { n: "01", t: "Monitor", d: "Track the tools, libraries, and APIs your project depends on." },
    { n: "02", t: "Test", d: "Automatically build and run your application with new versions." },
    { n: "03", t: "Compare", d: "Get real compatibility and performance metrics." },
    { n: "04", t: "Take Action", d: "Create GitHub issues or tasks based on the results." },
  ];
  return (
    <section className="px-6 pb-20 sm:px-10">
      <div className="relative border-t border-[#EAE9E6]">
        <span className="absolute left-1/2 top-0 -translate-x-1/2 -translate-y-1/2 rounded-full border border-[#E1DFDC] bg-[#F9F8F6] px-4 py-1 text-xs text-[#3C3C3B]">
          Explore
        </span>
      </div>
      <div className="grid grid-cols-1 gap-x-8 gap-y-12 pt-16 sm:grid-cols-2 lg:grid-cols-4 lg:pt-20">
        {features.map((f) => (
          <div key={f.n}>
            <div className="text-xs text-[#7A7873]">{f.n}</div>
            <h3 className="mt-3 text-base font-medium text-[#2F2F2E]">{f.t}</h3>
            <p className="mt-2 text-sm leading-relaxed text-[#7A7873]">{f.d}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

/* --------------------------------------------------------------- final CTA */

function FinalCTA({ onAuth }: { onAuth: AuthModeDispatch }) {
  return (
    <section className="px-6 pb-24 pt-6 sm:px-10">
      <div className="rounded-[2rem] border border-[#EAE9E6] bg-[#F1F0EC] px-6 py-20 text-center sm:py-28">
      <h2 className="mx-auto max-w-md text-4xl font-normal leading-[1.1] tracking-tight text-[#2F2F2E] sm:text-[2.75rem]">
        Start testing smarter
        <br />
        today.
      </h2>
        <div className="mt-10 flex flex-wrap items-center justify-center gap-3">
          <button
            onClick={() => onAuth("signup")}
            className="rounded-full bg-[#2F2F2E] px-7 py-3 text-sm text-[#F9F8F6] transition-all hover:bg-black"
          >
            Create account
          </button>
          <a
            href="#how-to-use"
            className="rounded-full border border-[#E1DFDC] bg-[#F9F8F6] px-7 py-3 text-sm text-[#3C3C3B] transition-colors hover:bg-white"
          >
            Read the guide
          </a>
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ footer */

function Footer() {
  const links = ["GitHub", "Docs", "X", "LinkedIn"];
  return (
    <footer className="px-6 sm:px-10">
      <div className="border-t border-[#EAE9E6] py-6">
        <div className="flex flex-col items-center justify-between gap-3 text-xs text-[#7A7873] sm:flex-row">
          <span>© 2026 Alfred. All rights reserved.</span>
          <div className="flex items-center gap-2">
            {links.map((label, i) => (
              <span key={label} className="flex items-center gap-2">
                <a href="#" className="transition-colors hover:text-[#3C3C3B]">
                  {label}
                </a>
                {i < links.length - 1 && <span className="text-[#B8B6B0]">/</span>}
              </span>
            ))}
          </div>
        </div>
      </div>
    </footer>
  );
}

/* -------------------------------------------------------------------- page */

export default function LandingPage({ onAuth }: { onAuth: AuthModeDispatch }) {
  return (
    <Shell>
      <Navbar onAuth={onAuth} />
      <Hero onAuth={onAuth} />
      <LogoStrip />
      <HowItWorks />
      <HowToUse />
      <FeatureGrid />
      <FinalCTA onAuth={onAuth} />
      <Footer />
    </Shell>
  );
}
