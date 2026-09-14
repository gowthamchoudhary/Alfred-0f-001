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

- **Jump to: [How to use Alfred — the complete walkthrough](#how-to-use-alfred--the-complete-walkthrough)** ·
  [How to get a GitHub token](#step-3--get-a-github-token-once) ·
  [What happens during each pipeline step, in plain language](#what-actually-happens-in-each-step-in-plain-language)

## How to use Alfred — the complete walkthrough

This section explains, in plain language, everything a user needs: what to
prepare, where to click, what the GitHub token is for, and what happens
underneath.

### Step 1 — Create your account

Sign up with an email and a password (≥8 chars). That is the only identity
Alfred needs — **GitHub is an integration, not a login.** After signup you land
on the dashboard.

### Step 2 — Prepare your repo (the one-time contract)

Alfred runs **any** repository that follows one minimal convention — there is
no demo app baked in. Four things, already true of most Python services:

```
your-repo/
├── Dockerfile          # builds your app; must expose it on $PORT
├── requirements.txt    # pinned versions — THIS is the file Alfred bumps
├── tests/              # a pytest suite that runs INSIDE the container
└── alfred.yaml         # what to watch, which endpoint to hit, how hard
```

`alfred.yaml` (the workload plan):

```yaml
dependency:
  name: openai          # the dependency Alfred watches and bumps
  current: "1.99.0"     # the version your requirements.txt currently pins
workload:
  endpoint: /chat       # the real endpoint the load test fires at
  method: POST
  concurrency: 20       # simultaneous requests
  requests: 500         # total requests per environment
  payloads:
    - { "message": "Summarize this refund policy." }
```

Why each piece matters: the Dockerfile is how Alfred gets two honest copies of
your app running; the pinned `requirements.txt` is the only thing that differs
between the two environments; the pytest suite is your own definition of
"still works"; the workload is your own definition of "still fast enough".
`examples/sample-repo/` is a working reference of the whole contract.

### Step 3 — Get a GitHub token (once)

Alfred posts each verdict **as a real GitHub issue on your repo**, so it needs
a token that may create issues as you. Recommended: a **fine-grained personal
access token** scoped to exactly one repo:

1. Go to **github.com → Settings → Developer settings → Personal access
   tokens → Fine-grained tokens → Generate new token** (direct link:
   `https://github.com/settings/personal-access-tokens/new`).
2. **Token name:** anything, e.g. `alfred-verdicts`.
3. **Resource owner:** your user/org. **Repository access:** *Only select
   repositories* → pick the repo that should receive verdict issues.
4. **Permissions:** *Contents* → `Read-only` (enough for release discovery);
   if your repo requires it for issue creation, set *Issues* → `Read and
   write`. Leave **everything else unchecked**.
5. Click **Generate token**, copy the `github_pat_…` value — GitHub shows it
   **once**.
6. Paste it into the dashboard **Watchlist** form (Step 4) when you register a
   dependency. That is the only time you will ever handle it.

**What happens to it (the security model):**

* Stored **Fernet-encrypted at rest** (`ALFRED_ENCRYPTION_KEY`) on your
  watchlist entry — the database never contains the plaintext.
* When an automatic investigation fires, the ciphertext is decrypted **in
  memory**, used for the issue POST and the verify GET, and discarded when the
  run ends.
* It is **never returned by any API response** (the watchlist reader
  structurally excludes credential columns), never logged, and never written
  to any table in plaintext. A leak test in the suite asserts this against the
  raw database bytes.
* Rotate any time by re-registering the entry with a new token; delete the
  entry and the ciphertext is gone.
* Manual one-off runs can alternatively pass a fresh token per request — an
  explicit per-request token always wins over the stored one.

### Step 4 — Watch a dependency (turns on the automatic loop)

Dashboard → **Watchlist** → fill the form:

* **dependency** — e.g. `openai` (the PyPI or GitHub name)
* **source** — PyPI or GitHub
* **github owner/repo** — optional; sharpens release discovery for GitHub-hosted deps
* **issue destination owner** + **GitHub token** — the one-time credential from Step 3

Click **Watch**. From this moment the loop is fully autonomous: the background
poller (started automatically when the server starts) checks this dependency
every `ALFRED_POLL_INTERVAL` seconds (default 900), detects new releases,
triages them, and — for anything it accepts — runs the full pipeline with zero
human action. The verdict lands on your repo as an issue and on your dashboard
with a live event timeline.

### Step 5 — Run an investigation yourself (optional)

You never *have* to wait for a real release. Dashboard → **Overview** →
"Run an investigation": give it a repo path or git URL and a target version —
Alfred stages baseline vs candidate immediately. Same engine, same evidence.

### Step 6 — Read the results

Every investigation page shows, all sourced from real persisted data:

* a **timestamped event timeline** — every one of the ten pipeline steps
* **baseline vs candidate** test counts, p50/p95/p99 latency, error rate,
  throughput — each with absolute + percentage deltas
* the deterministic **compatibility score** (60% functional, 40% performance)
* the **verdict** (SAFE / SAFE_WITH_REVIEW / MODERATE_RISK / HIGH_RISK) with
  the AI's reasons and confidence
* the **verified GitHub issue URL** — VERIFY literally GETs the issue back
  before claiming it exists

Skipped releases are visible on the **Changes** tab with the reason — nothing
is hidden, and skipped changes never burn Docker cycles.

### What actually happens in each step (plain language)

```
WATCH      A background thread polls release feeds (Anakin Wire releases for
           GitHub-hosted deps; PyPI RSS / GitHub REST as fallbacks) on a
           schedule. A new version becomes a row in detected_changes.
TRIAGE     Cheap rules first: is it actually newer? Is it a major bump? Do the
           notes say breaking/deprecated/removed/migration? Pre-releases are
           skipped. Only genuinely ambiguous cases spend one LLM relevance
           check. Accepted changes are marked and dispatched.
PREPARE    Your repo is cloned/copied twice. Candidate's requirements.txt gets
           the watched dependency bumped to the new version. Baseline stays
           exactly as-is.
BUILD      Both copies are built from their own Dockerfile. (Build failure is a
           valid result — reported, not a crash.)
RUN        Both images run as containers with --memory 512m --cpus 1, on
           separate host ports. Alfred waits for the app to accept connections
           (startup failure is also a valid, reportable result).
TEST       Your own pytest suite runs inside each container. The summary line
           is parsed for passed/failed/errors — no plugins, minimal contract.
WORKLOAD   Real concurrent HTTP requests — your payloads at your concurrency —
           fire at both containers. Latency percentiles and error rates come
           from actual timings, not simulations.
COMPARE    Pure deterministic math (no AI): deltas per metric plus the
           compatibility score.
RESEARCH   Anakin agentic-search + GitHub release data fetch migration-guide /
           breaking-change context for this exact dependency + version pair.
REASON     ONE LLM call reads the measured evidence + research and writes a
           verdict with confidence and reasons. Without an LLM key, a
           rule-based verdict from the score takes over — never a crash.
ACTION     The verdict is posted to your repo as a GitHub issue via the REST
           API (using the token from Step 3 — or skipped cleanly if absent).
VERIFY     The issue is fetched back from GitHub to confirm it really exists.
CLEANUP    Both containers are always stopped and removed, even on failure.
```

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
* `ALFRED_ENCRYPTION_KEY` — a Fernet key (`python -c "from alfred.crypto import
  generate_key; print(generate_key())"`). Required for encrypted watchlist
  credentials; without it, registering a token returns 503 and auto-runs fall
  back to a clean ACTION skip. Never stored in the database.
* **GitHub token — two supply paths, one rule: never exposed.**
  * *Automatic (poller → triage) runs:* the user supplies their token **once**
    at watchlist registration (`POST /api/watchlist` with
    `github_token`/`github_owner`/`github_repo`). It is stored **Fernet-encrypted
    at rest** on that watchlist entry (`watchlist.gh_token_enc`); the plaintext
    never enters the database. When a change auto-investigates, the ciphertext
    is decrypted in memory, used for ACTION/VERIFY, and discarded when the run
    ends.
  * *Manual/API/CLI runs:* per-request override, in-memory only (unchanged) —
    an explicit `github_token` on the trigger always wins over the stored one.
  * The plaintext token is NEVER logged and NEVER returned by any API response:
    `GET /api/watchlist` and the dashboard read through
    `db.list_watchlist()`, which structurally excludes the credential columns.
  * No stored credential → the pipeline still runs; ACTION skips cleanly.
* Rotation: delete and re-register the watchlist entry with the new token
  (re-registering with a token updates the stored ciphertext in place).

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
GET    /api/watchlist                 monitored dependencies (auth; credentials never included)
POST   /api/watchlist                 add {name, source: pypi|github, repo?,
                                      github_token?, github_owner?, github_repo?}
                                      — token stored encrypted once, never returned
DELETE /api/watchlist/{name}          stop watching
GET    /api/events                    live tail of recent event lines
```

## Explicit non-goals

* No behavioral/semantic compatibility checking (only build/startup/functional/performance)
* Python/Docker/pytest/HTTP-API projects only
* Dependency version bumps only — not arbitrary code/framework migrations
* No browser automation for GitHub — REST API is correct and sufficient
* No long-term trend analytics beyond the investigation list

## Tests

```bash
cd backend && python -m pytest tests/ -q   # 29 tests, no Docker/network needed
```
