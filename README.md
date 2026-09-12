# Alfred — autonomous release-impact testing agent

> "What actually happens if I take this update?" — answered with evidence from
> real execution, not a guess.

When a dependency has a new version available, Alfred doesn't just notify. It
builds **two environments from the same real repo** — baseline (current
version) and candidate (proposed version) — runs the identical test suite and
workload against both, measures the real difference, researches the change on
the web, has an LLM reason over that measured evidence, and posts a verdict
back to GitHub as an issue (verified to actually exist).

**Every number shown anywhere comes from a container that actually ran.**
The LLM interprets facts; it never invents them.

## Architecture

```
backend/alfred/
├── orchestrator.py    run_investigation(): the 10-step pipeline
├── candidate.py       PREPARE  — clone/copy repo ×2, bump candidate requirements.txt
├── docker_runner.py   BUILD/RUN — docker build + run (--memory 512m --cpus 1)
├── test_runner.py     TEST     — pytest inside each container, summary parsing
├── workload.py        WORKLOAD — real concurrent HTTP (httpx + asyncio), p50/p95/p99
├── compare.py         COMPARE  — deterministic deltas + compatibility score (no LLM)
├── research.py        RESEARCH — one targeted Exa search (fallback: PyPI/GitHub scrape)
├── reason.py          REASON   — ONE Groq (llama-3.3-70b-versatile) call, or rule-based fallback
├── github_action.py   ACTION/VERIFY — REST issue create + GET-back verification
├── discovery.py       watchlist polling: PyPI RSS + GitHub releases
├── triage.py          deterministic filter (→ LLM only when ambiguous) → auto-invoke
├── contract.py        the repo contract validator (no demo app baked in)
├── db.py              SQLite: investigations, agent_events, test_runs,
│                      comparisons, decisions, actions, detected_changes, watchlist
├── app.py             FastAPI REST API + static dashboard serving
└── cli.py             manual trigger fallback / debug tool
frontend/              React + Tailwind dashboard (polling, no websockets)
```

## The repo contract

Alfred works on **any** repo following this minimal convention:

```
repo/
├── Dockerfile          # required — must expose the app on $PORT
├── requirements.txt    # required — pinned versions; this gets bumped
├── tests/              # required — pytest suite
└── alfred.yaml         # required — workload + github config
```

```yaml
dependency:
  name: openai
  current: "1.99.0"
workload:
  endpoint: /chat
  method: POST
  concurrency: 20
  requests: 500
  payloads:
    - { "message": "Summarize this refund policy." }
github:
  owner: someuser
  repo: customer-support-ai
```

`examples/sample-repo/` is a *reference implementation of the contract* for
validating installs — Alfred itself contains nothing repo-specific.

## The pipeline

```
PREPARE → BUILD → RUN → TEST → WORKLOAD → COMPARE → REASON → ACTION → VERIFY → CLEANUP
```

* **COMPARE** is pure deterministic Python (no LLM):
  `functional = tests_passed_cand / tests_passed_base`,
  `performance = 1 - max(0, (p95_cand - p95_base)/p95_base)`,
  `overall = 0.6*functional + 0.4*performance`
* **REASON** is ONE Groq call (`llama-3.3-70b-versatile`, via Groq's OpenAI-compatible
  API) fed the real comparison + web evidence; without `GROQ_API_KEY` it degrades to a
  rule-based verdict
  (≥95 SAFE, ≥80 SAFE_WITH_REVIEW, ≥60 MODERATE_RISK, else HIGH_RISK) — the
  pipeline never crashes from a missing key.
* **ACTION** posts via GitHub's REST API; **VERIFY** GETs the issue back to
  confirm it exists. Without `GITHUB_TOKEN` the step is skipped cleanly — never faked.
* **CLEANUP** always stops/removes both containers (try/finally), even on failure.
* Build failure and startup failure are valid, reportable results — not crashes.
* Every step logs `[HH:MM:SS] STEP_NAME   message` events (stdout + SQLite).

## Discovery → triage → automatic investigation

1. A background poller checks each watchlist entry every 15 min
   (`ALFRED_POLL_INTERVAL` seconds to override): PyPI RSS for pip packages,
   GitHub releases API for GitHub-hosted deps. New releases land in `detected_changes`.
2. **Triage** runs cheap deterministic checks first — major version bump?
   breaking/deprecated/removed/migration language? pre-release or
   not-actually-newer → skipped. Ambiguous cases get ONE LLM relevance check
   (skipped entirely when no key is configured).
3. Skipped changes are recorded and **visible on the dashboard** — nothing is
   hidden, and they never trigger the expensive Docker pipeline.
4. Accepted changes auto-invoke `run_investigation()` — this replaces manual
   CLI triggering as the primary path.

## Running

```bash
# backend
pip install -r backend/requirements.txt
cd backend && python -m alfred.cli serve          # serves API + built dashboard on :8000

# frontend (dev)
cd frontend && bun install && bun run dev         # proxies /api to :8000

# production dashboard build
cd frontend && bun run build                      # → frontend/dist, served by FastAPI

# CLI fallback / debug
python -m alfred.cli investigate ./examples/sample-repo 2.1.0
python -m alfred.cli poll
```

Environment variables (all optional — the pipeline degrades, never crashes):

| Var | Effect |
| --- | --- |
| `GROQ_API_KEY` | enables LLM reasoning + LLM triage checks (Groq free tier, used intentionally for cost) |
| `EXA_API_KEY` | enables targeted web research (Exa) |
| `GITHUB_TOKEN` | enables GitHub issue posting |
| `ALFRED_DB_PATH` | SQLite location (default `backend/alfred.db`) |
| `ALFRED_POLL_INTERVAL` | discovery poll cadence in seconds (default 900) |

## REST API

```
GET    /api/health
GET    /api/investigations            list (newest first)
POST   /api/investigations            manual trigger {repo_source, target_version, dependency_name?}
GET    /api/investigations/{id}       full detail: events, runs, comparison, decision, action
GET    /api/detected-changes          every discovered release, incl. skipped
POST   /api/discovery/poll            force one discovery poll now
GET    /api/watchlist                 monitored dependencies
POST   /api/watchlist                 add {name, source: pypi|github, repo?}
DELETE /api/watchlist/{name}          stop watching
GET    /api/events                    live tail of recent event lines
```

## Explicit non-goals

* No behavioral/semantic compatibility checking (only build/startup/functional/performance)
* Python/Docker/pytest/HTTP-API projects only
* Dependency version bumps only — not arbitrary code/framework migrations
* No browser automation for GitHub — REST API is correct and sufficient
* No user accounts, no long-term trend analytics beyond the investigation list

## Tests

```bash
cd backend && python -m pytest tests/ -q   # 29 tests, no Docker/network needed
```
