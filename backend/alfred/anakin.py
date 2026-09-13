"""Anakin API client — AnakinScraper REST API, used properly at both stages.

Anakin (api.anakin.io/v1, ``X-API-Key`` header) is Alfred's discovery AND
research provider:

  * ``POST /search``          — synchronous keyword search with snippets
  * ``POST /agentic-search``  — async multi-stage research; submit, then poll
                                ``GET /agentic-search/{job_id}``
  * ``POST /wire/task``       — Wire catalog actions; poll
                                ``GET /wire/jobs/{job_id}`` until the job
                                settles (``github_public`` catalog exposes
                                read-only actions such as ``gh_repo_releases``)

Reliability contract (same as every Alfred integration): a missing
``ANAKIN_API_KEY`` or a failed call is logged and surfaced as ``None`` —
callers continue with reduced evidence. Nothing here may crash the pipeline.

Legacy note: older drafts of the API spoke of ``POST /holocron/task``; the
live documented surface (verified Jul 2026) is ``/wire/task`` +
``/wire/jobs/{id}``, which this client uses.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

BASE_URL = "https://api.anakin.io/v1"
REQUEST_TIMEOUT = 30.0
AGENTIC_POLL_TIMEOUT = 180.0
AGENTIC_POLL_INTERVAL = 10.0
WIRE_POLL_TIMEOUT = 60.0
WIRE_POLL_INTERVAL = 3.0
USER_AGENT = "Alfred-ReleaseImpactAgent/0.1 (Anakin-powered discovery+research)"


def anakin_api_key() -> str | None:
    """Read once from the environment; callers must treat None as 'unavailable'."""
    key = (os.environ.get("ANAKIN_API_KEY") or "").strip()
    return key or None


def _headers(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key, "Content-Type": "application/json", "User-Agent": USER_AGENT}


# ------------------------------------------------------------------- /search
def search(api_key: str, prompt: str, limit: int = 5) -> dict[str, Any] | None:
    """Synchronous keyword search. Returns the raw payload or None on failure."""
    try:
        resp = httpx.post(
            f"{BASE_URL}/search",
            headers=_headers(api_key),
            json={"prompt": prompt, "limit": limit},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:  # noqa: BLE001 — caller logs and continues
        return None


# ---------------------------------------------------------- /agentic-search
def agentic_search(
    api_key: str,
    prompt: str,
    timeout: float = AGENTIC_POLL_TIMEOUT,
) -> dict[str, Any] | None:
    """Multi-stage research job: submit, then poll to completion.

    Returns the final job payload (``status``/``result``/``answer``/...) or
    None when the key/endpoint fails or the job does not settle in time.
    """
    try:
        resp = httpx.post(
            f"{BASE_URL}/agentic-search",
            headers=_headers(api_key),
            json={"prompt": prompt},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code not in (200, 202):
            return None
        job = resp.json()
        job_id = job.get("job_id") or job.get("id")
        if not job_id:
            return None

        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(AGENTIC_POLL_INTERVAL)
            poll = httpx.get(
                f"{BASE_URL}/agentic-search/{job_id}",
                headers=_headers(api_key),
                timeout=REQUEST_TIMEOUT,
            )
            if poll.status_code != 200:
                continue
            payload = poll.json()
            status = (payload.get("status") or "").lower()
            if status in ("completed", "succeeded", "success", "done"):
                return payload
            if status in ("failed", "error", "cancelled", "canceled"):
                return payload  # settled-but-failed; caller decides
        return None
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------- /wire/task
def wire_task(
    api_key: str,
    action_id: str,
    params: dict[str, Any],
    timeout: float = WIRE_POLL_TIMEOUT,
) -> dict[str, Any] | None:
    """Run a Wire catalog action and poll its job to a settled state.

    Returns the final job payload or None on failure/timeout.
    """
    try:
        resp = httpx.post(
            f"{BASE_URL}/wire/task",
            headers=_headers(api_key),
            json={"action_id": action_id, "params": params},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code not in (200, 202):
            return None
        job = resp.json()
        job_id = job.get("job_id") or job.get("id")
        if not job_id:
            return job  # some actions may answer synchronously

        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(WIRE_POLL_INTERVAL)
            poll = httpx.get(
                f"{BASE_URL}/wire/jobs/{job_id}",
                headers=_headers(api_key),
                timeout=REQUEST_TIMEOUT,
            )
            if poll.status_code != 200:
                continue
            payload = poll.json()
            status = (payload.get("status") or "").lower()
            if status in ("completed", "succeeded", "success", "done"):
                return payload
            if status in ("failed", "error", "cancelled", "canceled"):
                return payload
        return None
    except Exception:  # noqa: BLE001
        return None
