"""DISCOVERY — watch a configurable list of dependencies for new releases.

PRIMARY: Anakin Website-Monitoring-style watch — for GitHub-hosted deps we
run the Wire ``gh_repo_releases`` action (github_public catalog) on the poll
cadence; this is the sponsor-integrated discovery mechanism. The result and
its provenance are logged with the ``anakin`` marker for the dashboard.
FALLBACK (unchanged, still reliable):
  * pip packages: PyPI RSS feed https://pypi.org/rss/project/{name}/releases.xml
  * GitHub-hosted deps: GitHub releases API (repos/{repo}/releases)

Every detected release is written to ``detected_changes`` (upsert-safe on the
(dependency, version) pair). Watchlist entries live in the ``watchlist`` table
and can be added/removed via the API or seeded on first boot.
"""

from __future__ import annotations

import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import httpx

from .anakin import anakin_api_key, wire_task
from .db import Database
from .events import log_event

POLL_INTERVAL = 900  # 15 minutes; overridable via ALFRED_POLL_INTERVAL
WIRE_GH_RELEASES_ACTION = "gh_repo_releases"  # github_public catalog (read-only)
# Where triage-accepted investigations get their repo from. Set
# ALFRED_REPO_TARGET to a local path or git URL of a contract-compliant repo;
# when unset (or docker is unavailable) accepted changes stay 'pending' so the
# dashboard shows them without burning compute on an impossible pipeline.
ALFRED_REPO_TARGET = os.environ.get("ALFRED_REPO_TARGET", "")
HTTP_TIMEOUT = 15.0
USER_AGENT = "Alfred-ReleaseImpactAgent/0.1"
_GH_SEM = re.compile(r"href=\"/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/releases\"")
_GH_REPO_RE = re.compile(r"github\.com[/:]([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(\.git)?/?$")

_poller_thread: threading.Thread | None = None
_stop = threading.Event()


def fetch_pypi_releases(package: str) -> list[dict]:
    """Return the newest releases for a pip package from its PyPI RSS feed."""
    url = f"https://pypi.org/rss/project/{package}/releases.xml"
    try:
        resp = httpx.get(url, timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
        resp.raise_for_status()
    except Exception:  # noqa: BLE001 — network hiccups must not kill the poller
        return []
    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError:
        return []
    out: list[dict] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        if not title:
            continue
        published_iso = _parse_rss_date(pub)
        out.append(
            {
                "latest_version": title,
                "release_url": link or f"https://pypi.org/project/{package}/{title}/",
                "published_at": published_iso,
            }
        )
    return out


def fetch_github_releases_anakin(api_key: str, repo: str) -> list[dict]:
    """PRIMARY GitHub discovery: Wire ``gh_repo_releases`` (github_public catalog).

    Same row shape as the REST fallback so ``poll_once`` treats them
    identically; returns [] on any failure so the fallback can take over.
    """
    owner, _, name = repo.partition("/")
    raw = wire_task(api_key, WIRE_GH_RELEASES_ACTION, {"owner": owner, "repo": name})
    if not raw or (raw.get("status") or "").lower() in ("failed", "error", "cancelled", "canceled"):
        return []
    result = raw.get("result") or raw.get("data") or raw.get("output") or {}
    releases = result if isinstance(result, list) else (result.get("releases") or result.get("items") or [])
    if not isinstance(releases, list):
        return []
    out: list[dict] = []
    for rel in releases[:5]:
        if not isinstance(rel, dict):
            continue
        tag = str(rel.get("tag_name") or rel.get("tag") or "").lstrip("v").strip()
        if not tag:
            continue
        out.append(
            {
                "latest_version": tag,
                "release_notes": str(rel.get("body") or rel.get("notes") or "")[:2000],
                "release_url": rel.get("html_url") or rel.get("url") or f"https://github.com/{repo}/releases/tag/{tag}",
                "published_at": rel.get("published_at") or rel.get("published"),
            }
        )
    return out


def fetch_github_releases(repo: str) -> list[dict]:
    """FALLBACK GitHub discovery: direct REST call."""
    url = f"https://api.github.com/repos/{repo}/releases?per_page=5"
    try:
        resp = httpx.get(url, timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
        resp.raise_for_status()
    except Exception:  # noqa: BLE001
        return []
    out: list[dict] = []
    for rel in resp.json():
        tag = (rel.get("tag_name") or "").lstrip("v")
        if not tag:
            continue
        out.append(
            {
                "latest_version": tag,
                "release_notes": (rel.get("body") or "")[:2000],
                "release_url": rel.get("html_url") or f"https://github.com/{repo}/releases/tag/{rel.get('tag_name')}",
                "published_at": rel.get("published_at"),
            }
        )
    return out


def _parse_rss_date(raw: str) -> str | None:
    if not raw:
        return None
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S GMT"):
        try:
            return datetime.strptime(raw, fmt).astimezone(timezone.utc).isoformat()
        except ValueError:
            continue
    return None


def poll_once(db: Database) -> int:
    """Poll every enabled watchlist entry once; returns number of NEW changes."""
    from .docker_runner import _docker_available

    docker_ok = _docker_available()
    repo_target = ALFRED_REPO_TARGET
    new_changes = 0
    for entry in db.list_watchlist():
        if not entry.get("enabled"):
            continue
        name = entry["name"]
        source_used = entry["source"]
        releases: list[dict] = []
        if entry["source"] == "github" and entry.get("repo"):
            api_key = anakin_api_key()
            if api_key:
                releases = fetch_github_releases_anakin(api_key, entry["repo"])
                if releases:
                    source_used = "anakin"
                else:
                    print(f"[discovery] anakin wire returned nothing for {entry['repo']}; REST fallback", flush=True)
            else:
                print("[discovery] ANAKIN_API_KEY not set; REST fallback for github dep", flush=True)
            if not releases:
                releases = fetch_github_releases(entry["repo"])
        else:
            releases = fetch_pypi_releases(name)
        for rel in releases[:3]:
            change = {
                "dependency_name": name,
                "source": source_used,
                "latest_version": rel["latest_version"],
                "release_notes": rel.get("release_notes"),
                "release_url": rel.get("release_url"),
                "published_at": rel.get("published_at"),
            }
            stored = db.upsert_detected_change(change)
            if stored is not None:
                new_changes += 1
                # Triage immediately and auto-invoke the pipeline when accepted
                # (the primary path — CLI triggering stays as fallback/debug).
                try:
                    from .triage import triage_and_dispatch

                    if repo_target and docker_ok:
                        triage_and_dispatch(db, stored, repo_source=repo_target)
                    else:
                        db.mark_change_triaged(
                            stored["id"],
                            "pending",
                            "awaiting ALFRED_REPO_TARGET/docker before auto-investigation",
                            "deterministic",
                        )
                except Exception as exc:  # noqa: BLE001 — triage must not kill polling
                    print(f"[triage] error for {name} {rel['latest_version']}: {exc}", flush=True)
        latest = releases[0]["latest_version"] if releases else None
        db.update_watchlist_status(name, latest)
    return new_changes


def start_poller(app: "Database") -> None:
    """Start the background polling loop (idempotent)."""
    global _poller_thread
    if _poller_thread and _poller_thread.is_alive():
        return

    def _loop() -> None:
        interval = int(__import__("os").environ.get("ALFRED_POLL_INTERVAL", POLL_INTERVAL))
        while not _stop.is_set():
            try:
                count = poll_once(app)
                if count:
                    print(f"[discovery] {count} new release(s) detected", flush=True)
            except Exception as exc:  # noqa: BLE001 — the loop must survive anything
                print(f"[discovery] poll error: {exc}", flush=True)
            _stop.wait(interval)

    _poller_thread = threading.Thread(target=_loop, name="alfred-discovery", daemon=True)
    _poller_thread.start()


def stop_poller() -> None:
    _stop.set()


def infer_repo_from_package(package: str) -> str | None:
    """Best-effort mapping of a pip package to its GitHub repo via PyPI JSON API."""
    try:
        resp = httpx.get(f"https://pypi.org/pypi/{package}/json", timeout=HTTP_TIMEOUT, follow_redirects=True)
        if resp.status_code != 200:
            return None
        urls = (resp.json().get("info") or {}).get("project_urls") or {}
        for u in list(urls.values()) + [urls.get("Homepage") or ""]:
            if not u:
                continue
            m = _GH_REPO_RE.search(u)
            if m:
                return f"{m.group(1)}/{m.group(2)}"
    except Exception:  # noqa: BLE001
        return None
    return None
