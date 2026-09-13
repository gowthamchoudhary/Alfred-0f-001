import { useEffect, useState } from "react";

type AuthMode = "login" | "signup";

/* ------------------------------------------------------------- logo slots */

const LOGO_SLOTS = ["openai", "vercel", "microsoft", "stripe", "docker"] as const;

function LogoSlot({ slot }: { slot: string }) {
  const [src, setSrc] = useState<string | null>(null);

  useEffect(() => {
    // Drop the real asset at frontend/public/logos/<slot>.<ext> and it appears
    // here automatically — no code change needed.
    let alive = true;
    const exts = ["svg", "png", "webp", "jpg"];
    (async () => {
      for (const ext of exts) {
        const url = `/logos/${slot}.${ext}`;
        try {
          const res = await fetch(url, { method: "HEAD" });
          if (res.ok) {
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

/* ------------------------------------------------------------------ navbar */

function Navbar({ onAuth }: { onAuth: AuthModeDispatch }) {
  return (
    <header className="flex items-center justify-between px-6 pt-6 sm:px-10">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full bg-[#EAE9E6] px-4 py-1.5 text-xs font-medium text-[#3C3C3B]">Alfred</span>
        {["Product", "Pricing"].map((label) => (
          <a
            key={label}
            href="#"
            className="rounded-full border border-[#E1DFDC] bg-[#F9F9F6] px-4 py-1.5 text-xs text-[#3C3C3B] transition-colors hover:bg-[#F1F0EC]"
          >
            {label}
          </a>
        ))}
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
      <button
        onClick={() => onAuth("signup")}
        className="alfred-enter mt-10 rounded-full bg-[#2F2F2E] px-9 py-3.5 text-sm text-[#F9F8F6] transition-all hover:bg-black"
      >
        Get started
      </button>
    </section>
  );
}

/* ------------------------------------------------------- product overview */

function ProductOverview() {
  return (
    <section className="flex flex-col items-center px-6 pb-14 pt-20 text-center sm:pb-16 sm:pt-24">
      <h2 className="text-3xl font-normal tracking-tight text-[#2F2F2E] sm:text-4xl">From updates to insights.</h2>
      <p className="mt-4 text-sm text-[#7A7873]">Everything you need to keep your project ahead of change.</p>
    </section>
  );
}

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
          <button className="rounded-full border border-[#E1DFDC] bg-[#F9F8F6] px-7 py-3 text-sm text-[#3C3C3B] transition-colors hover:bg-white">
            Watch demo
          </button>
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
      <ProductOverview />
      <FeatureGrid />
      <FinalCTA onAuth={onAuth} />
      <Footer />
    </Shell>
  );
}
