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
├── research.py        RESEARCH — Anakin agentic-search + Wire gh_repo_releases
│                      (fallback: direct PyPI/GitHub scrape)
├── reason.py          REASON   — ONE Groq (openai/gpt-oss-120b) call, or rule-based fallback
├── github_action.py   ACTION/VERIFY — REST issue create + GET-back verification
├── anakin.py          Anakin REST client (search / agentic-search / Wire tasks)
├── discovery.py       watchlist polling — PRIMARY: Anakin Wire gh_repo_releases;
│                      fallback: PyPI RSS + GitHub REST releases
├── triage.py          deterministic filter (→ LLM only when ambiguous) → auto-invoke
├── contract.py        the repo contract validator (no demo app baked in)
├── db.py              persistence: Supabase (hosted Postgres, SQLAlchemy) with a
│                      local SQLite fallback for dev/tests
├── db/schema.sql      the canonical Postgres schema, applied idempotently on startup
├── app.py             FastAPI REST API + static dashboard serving
└── cli.py             manual trigger fallback / debug tool
frontend/              React + Tailwind dashboard (polling, no websockets)
```

## Anakin (discovery + research provider)

[Anakin](https://anakin.io) — `api.anakin.io/v1`, authenticated with `X-API-Key`
(`ANAKIN_API_KEY`) — is Alfred's provider at BOTH stages, used properly against
their live documented surface:

* **DISCOVERY (Stage 1):** the poller runs Wire's ``gh_repo_releases`` action
  (``POST /v1/wire/task`` + ``GET /v1/wire/jobs/{id}``, ``github_public``
  catalog) for GitHub-hosted watchlist dependencies on the poll cadence —
  Anakin handles auth/anti-bot and returns structured releases. Detected
  releases are tagged ``source=anakin`` in ``detected_changes``. PyPI RSS and
  GitHub REST polling remain as automatic fallbacks when the key is missing
  or a job fails.
* **RESEARCH (Stage 2):** every investigation calls Wire ``gh_repo_releases``
  for structured release data on the dependency under test (when
  GitHub-hosted) plus ONE ``POST /v1/agentic-search`` job (multi-stage
  synthesis — chosen over plain ``/search`` for better evidence text),
  polling to completion. If agentic-search does not settle in time, one
  synchronous ``POST /v1/search`` call degrades gracefully inside Anakin.
  Everything returned is folded into REASON's ``evidence_text`` — the
  contract with the reasoning step is unchanged. Exa has been fully removed.
* Missing key or failed calls are logged honestly and the pipeline continues
  with reduced evidence — same reliability rules as every other integration.

## The repo contract

Alfred works on **any** repo following this minimal convention:

```
repo/
├── Dockerfile          # required — must expose the app on $PORT
├── requirements.txt    # required — pinned versions; this gets bumped
├── tests/              # required — pytest suite
└── alfred.yaml         # required — workload config
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
```

**GitHub destination is not part of the repo.** Whoever triggers an
investigation supplies `github_owner` + `github_repo` — and their own token —
per request (dashboard form, `POST /api/investigations`, or CLI flags).

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
* **REASON** is ONE Groq call (`openai/gpt-oss-120b` — Groq's free-tier JSON-capable
  model, replacing the retired `llama-3.3-70b-versatile`; via Groq's OpenAI-compatible
  API) fed the real comparison + web evidence; without `GROQ_API_KEY` it degrades to a
  rule-based verdict
  (≥95 SAFE, ≥80 SAFE_WITH_REVIEW, ≥60 MODERATE_RISK, else HIGH_RISK) — the
  pipeline never crashes from a missing key.
* **ACTION** posts via GitHub's REST API; **VERIFY** GETs the issue back to
  confirm it exists. Without a per-request GitHub token (supplied by whoever
  triggers the investigation) the step is skipped cleanly — never faked.
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

## Persistence

Alfred stores all pipeline data in **Supabase (hosted Postgres)** so history
survives sandbox resets. The canonical schema is
[`backend/db/schema.sql`](backend/db/schema.sql) — applied automatically and
idempotently at startup. **There is deliberately no column anywhere in the
schema for credentials**: GitHub tokens are per-request and used in-memory
only, `GROQ_API_KEY`/`ANAKIN_API_KEY` stay in the environment; only results
(issue URLs, verified flags, metrics, verdicts) are ever written.

Without `SUPABASE_DB_URL` Alfred falls back to a local SQLite file (same
schema, warns at startup) so dev and unit tests need no credentials.

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
python -m alfred.cli investigate ./examples/sample-repo 2.1.0 \
    --github-owner someuser --github-repo customer-support-ai --github-token ghp_xxx
python -m alfred.cli poll
```

Environment variables (all optional — the pipeline degrades, never crashes):

| Var | Effect |
| --- | --- |
| `GROQ_API_KEY` | enables LLM reasoning + LLM triage checks (Groq free tier, used intentionally for cost) |
| `ANAKIN_API_KEY` | **discovery AND research provider** (Anakin, `api.anakin.io/v1`): Wire `gh_repo_releases` for GitHub-hosted dependency discovery and release evidence, `agentic-search` for migration/breaking-change research, synchronous `/search` as a graceful in-Anakin fallback. Without it, discovery falls back to PyPI RSS/GitHub REST and research to a direct PyPI/GitHub scrape — reduced evidence, never a crash. |
| (no `GITHUB_TOKEN`) | GitHub credentials are **not** env vars — each caller supplies `github_token`/`github_owner`/`github_repo` with their investigation request (see Credentials above) |
| `SUPABASE_DB_URL` | Supabase Postgres connection string (Project Settings → Database → Connection string, URI tab). When set, all investigation history persists to Supabase — outside this sandbox, so it survives workspace resets. Without it, Alfred falls back to a local SQLite file and warns. |
| `SUPABASE_POOLER_HOST` | Optional. Supabase pooler host (e.g. `aws-0-ap-northeast-2.pooler.supabase.com`) from the dashboard's "Connection pooling" string. Needed in IPv4-only environments where the direct host (`db.<ref>.supabase.co`) is IPv6-only and unreachable; the username is rewritten to `postgres.<project-ref>` automatically. Defaults to this project's discovered pooler host, so no setup is normally required. |
| `ALFRED_DB_PATH` | SQLite fallback location only (default `backend/alfred.db`); ignored when `SUPABASE_DB_URL` is set |
| `ALFRED_POLL_INTERVAL` | discovery poll cadence in seconds (default 900) |

## Credentials

* `GROQ_API_KEY` — environment-level (one shared key, set by the operator);
  used for every investigation's REASON (and triage) LLM calls. Never exposed
  to or requested from end users.
* **GitHub token — per-user, per-request.** Supplied by the caller on each
  investigation (`github_token` + `github_owner` + `github_repo` in the API
  request, CLI flags, or dashboard form). Used in-memory for that run's
  ACTION/VERIFY steps only: never written to the database, never logged, never
  returned in any API response. No token → the ACTION step skips cleanly.

## REST API

```
GET    /api/health
GET    /api/investigations            list (newest first)
POST   /api/investigations            manual trigger {repo_source, target_version,
                                      dependency_name?, github_token?,
                                      github_owner?, github_repo?}
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
