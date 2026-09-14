"""TRIAGE — stop wasting compute on trivial changes.

Order of checks:
  1. deterministic (cheap, instant):
       * major version bump?  → accept
       * release notes mention breaking/deprecated/removed/migration required?
       * pre-release markers (a/b/rc/dev/post) → skip
       * backwards-only version (≤ already-known latest) → skip
  2. ambiguous cases fall through to ONE LLM relevance check (skipped
     entirely when no GROQ_API_KEY — then only clearly-matching
     deterministic signals trigger the pipeline).

Only changes that pass triage auto-invoke run_investigation(). Skipped ones
are recorded as "detected, skipped, low relevance" so the dashboard shows
nothing is hidden.
"""

from __future__ import annotations

import os
import re
from typing import Any

from .db import Database
from .events import log_event

BREAKING_KEYWORDS = re.compile(
    r"\b(breaking|breaks|backward.?incompatible|deprecat(?:e|es|ed|ion|ions)|removal|"
    r"removed|no longer|migration required|migrat(?:e|ing) to|upgrade required|"
    r"drop(?:ped|s)? support)\b",
    re.IGNORECASE,
)
PRE_RELEASE = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:[.-]?(a|b|rc|dev|post)\.?\d*)?$", re.IGNORECASE)
MAJOR_KEYWORDS = re.compile(r"\bmajor (release|version|bump)\b", re.IGNORECASE)


def parse_version(v: str) -> tuple[int, int, int] | None:
    m = PRE_RELEASE.match((v or "").strip())
    if not m:
        return None
    try:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    except ValueError:
        return None


def is_major_bump(from_v: str, to_v: str) -> bool:
    a, b = parse_version(from_v), parse_version(to_v)
    if not a or not b:
        return False
    return b[0] > a[0]


def is_pre_release(v: str) -> bool:
    """True when the version carries an a/b/rc/dev/post marker."""
    m = PRE_RELEASE.match((v or "").strip())
    return bool(m and m.group(4))


def deterministic_triage(
    change: dict[str, Any],
    known_latest: str | None,
) -> tuple[str, str] | None:
    """Return (status, reason) for a decision, or None when ambiguous."""
    version = (change.get("latest_version") or "").strip()
    notes = change.get("release_notes") or ""

    if known_latest:
        a, b = parse_version(known_latest), parse_version(version)
        if a and b and b <= a:
            return ("skipped", f"version {version} is not newer than already-known {known_latest}")

    if is_pre_release(version):
        return ("skipped", f"{version} is a pre-release (alpha/beta/rc/dev/post)")

    if is_major_bump(known_latest or change.get("baseline_version", "0.0.0"), version):
        return ("accepted", f"major version bump detected ({known_latest or 'current'} → {version})")

    if BREAKING_KEYWORDS.search(notes):
        matched = BREAKING_KEYWORDS.search(notes).group(0)
        return ("accepted", f"release notes flag breaking change: matched '{matched}'")

    if MAJOR_KEYWORDS.search(notes):
        return ("accepted", "release notes describe a major release")

    return None  # ambiguous → caller decides whether to run the LLM check


def llm_relevance_check(
    change: dict[str, Any],
    dependency_name: str,
) -> tuple[bool, str]:
    """ONE LLM call for ambiguous cases; returns (relevant, reason)."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return (False, "no LLM key for ambiguous relevance check; treated as low relevance")

    import json

    from openai import OpenAI  # Groq's API is OpenAI-compatible

    prompt = {
        "dependency": dependency_name,
        "new_version": change.get("latest_version"),
        "release_notes_excerpt": (change.get("release_notes") or "")[:1500],
        "task": (
            "Decide whether this dependency release is likely to impact an application "
            "that uses it: look for breaking changes, deprecations, removed APIs, "
            "behavior or performance changes. Answer with JSON only: "
            "{\"relevant\": true|false, \"reason\": \"one sentence\"}"
        ),
    }
    try:
        client = OpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
        )
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a precise release-triage assistant. Answer with JSON only."},
                {"role": "user", "content": json.dumps(prompt)},
            ],
            max_tokens=300,
            response_format={"type": "json_object"},
        )
        text = resp.choices[0].message.content or ""
        data = json.loads(text.strip().strip("`"))
        return (bool(data.get("relevant")), str(data.get("reason"))[:300])
    except Exception as exc:  # noqa: BLE001 — ambiguity must not crash triage
        return (False, f"LLM relevance check failed ({exc}); treated as low relevance")


def triage_and_dispatch(
    db: Database,
    change: dict[str, Any],
    repo_source: str,
    allow_llm: bool = True,
    github_token: str | None = None,
    github_owner: str | None = None,
    github_repo: str | None = None,
) -> str | None:
    """Triage one detected change; auto-invoke run_investigation when accepted.

    Returns the investigation id when the pipeline ran, else None.

    Credential model: this is the UNATTENDED path — no human is present to
    supply a token. When the caller did not pass one, the credential stored
    (Fernet-encrypted at rest) on this dependency's watchlist entry is
    decrypted in memory, used for ACTION/VERIFY inside the pipeline, and
    DISCARDED when run_investigation returns — same in-memory-only principle
    as before, now sourced from encrypted storage. An explicit per-request
    ``github_token`` (API/CLI override) always wins. No stored credential →
    the pipeline still runs; ACTION skips itself cleanly. A missing key or
    failed decrypt is logged honestly and never crashes the pipeline.
    """
    name = change["dependency_name"]
    version = change["latest_version"]
    change_id = change["id"]

    entry = next((w for w in db.list_watchlist() if w["name"] == name), None)
    known_latest = (entry or {}).get("last_seen_version")

    deterministic = deterministic_triage(change, known_latest)
    if deterministic is None and allow_llm:
        relevant, reason = llm_relevance_check(change, name)
        if relevant:
            db.mark_change_triaged(change_id, "accepted", reason, "llm")
            log_event(db, "system", "TRIAGE", f"{name} {version}: accepted via LLM — {reason}")
        else:
            db.mark_change_triaged(change_id, "skipped", reason, "llm")
            log_event(db, "system", "TRIAGE", f"{name} {version}: skipped — {reason}")
            return None
    elif deterministic is None:
        db.mark_change_triaged(change_id, "skipped", "ambiguous release with no LLM key; low relevance", "deterministic")
        log_event(db, "system", "TRIAGE", f"{name} {version}: skipped (ambiguous, no LLM key)")
        return None
    else:
        status, reason = deterministic
        mode = "deterministic"
        if status == "skipped":
            db.mark_change_triaged(change_id, "skipped", reason, mode)
            log_event(db, "system", "TRIAGE", f"{name} {version}: skipped — {reason}")
            return None
        db.mark_change_triaged(change_id, "accepted", reason, mode)
        log_event(db, "system", "TRIAGE", f"{name} {version}: accepted — {reason}")

    # Accepted → run the real pipeline.
    from .orchestrator import run_investigation

    # Credential resolution for the unattended run: explicit per-request token
    # (API/CLI) wins; otherwise decrypt the watchlist entry's stored token in
    # memory. The plaintext lives only for the duration of this investigation.
    used_stored_credential = False
    if not github_token:
        stored = db.get_watchlist_credential(name)  # returns ciphertext
        if stored:
            try:
                from .crypto import decrypt_secret

                github_token = decrypt_secret(stored["gh_token_enc"])
                github_owner = github_owner or stored.get("gh_owner")
                github_repo = github_repo or stored.get("gh_repo")
                used_stored_credential = True
                log_event(db, "system", "TRIAGE", f"{name} {version}: using encrypted watchlist credential (decrypted in memory for this run only)")
            except Exception as exc:  # noqa: BLE001 — bad/missing key must not kill the run
                log_event(db, "system", "TRIAGE", f"{name} {version}: stored credential unusable ({exc}); ACTION will skip", level="warn")
                github_token = None

    try:
        inv_id = run_investigation(
            db,
            repo_source=repo_source,
            target_version=version,
            dependency_name=name,
            github_token=github_token,
            github_owner=github_owner,
            github_repo=github_repo,
            trigger="discovery",
        )
        # Plaintext token goes out of scope here — discarded after the run.
        del github_token
        db.mark_change_triaged(change_id, "accepted", "investigation dispatched", "deterministic", investigation_id=inv_id)
        if used_stored_credential:
            log_event(db, inv_id, "ACTION", "issue credentials came from the encrypted watchlist entry (in-memory only)")
        return inv_id
    except Exception as exc:  # noqa: BLE001 — record the failure, keep the loop alive
        db.mark_change_triaged(change_id, "accepted", f"investigation failed to start: {exc}", "deterministic")
        log_event(db, "system", "TRIAGE", f"{name} {version}: investigation failed to start: {exc}", level="error")
        return None
