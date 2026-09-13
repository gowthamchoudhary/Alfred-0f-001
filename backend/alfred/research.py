"""RESEARCH step — Anakin-powered evidence gathering.

For every investigation Anakin is called at two levels (both need
``ANAKIN_API_KEY``):

  a. ``POST /wire/task`` (``github_public`` catalog, ``gh_repo_releases``
     action) — structured release data for the dependency under test when it
     is GitHub-hosted.
  b. ``POST /agentic-search`` — ONE multi-stage research job for
     migration-guide / breaking-change context on the exact version bump
     (chosen over plain /search because its synthesis produces better
     evidence text for the reasoning step).

Whatever comes back is folded into ``evidence_text`` — the contract with the
REASON step is unchanged. When Anakin is unavailable or both calls fail, the
PyPI/GitHub direct scrape remains as a real-evidence fallback; the pipeline
never crashes or blocks on research. The previous web-search provider and all
of its code paths have been fully removed — Anakin is the research provider.
"""

from __future__ import annotations

from typing import Any

import httpx

from .anakin import agentic_search, anakin_api_key, search, wire_task
from .db import Database
from .events import log_event

SEARCH_TIMEOUT = 20.0
USER_AGENT = "Alfred-ReleaseImpactAgent/0.1 (release research)"
WIRE_GH_RELEASES_ACTION = "gh_repo_releases"  # github_public catalog (read-only)
MAX_EVIDENCE_CHARS = 8000


def research_dependency(
    db: Database,
    investigation_id: str,
    dependency_name: str,
    from_version: str,
    to_version: str,
    github_repo: str | None = None,
) -> dict:
    """Return {'source': 'anakin'|'fallback'|'none', 'evidence_text': str, 'urls': [...]}."""
    api_key = anakin_api_key()
    if not api_key:
        log_event(
            db, investigation_id, "RESEARCH",
            "ANAKIN_API_KEY not set — falling back to direct PyPI/GitHub scrape",
            level="warn",
        )
        return _fallback_scrape(db, investigation_id, dependency_name, from_version, to_version, github_repo)

    chunks: list[str] = []
    urls: list[str] = []

    # ---- (a) Wire: structured release data for GitHub-hosted deps ----------
    wire_raw: dict[str, Any] | None = None
    if github_repo:
        owner, _, name = github_repo.partition("/")
        log_event(db, investigation_id, "RESEARCH", f"anakin wire gh_repo_releases: {github_repo}")
        wire_raw = wire_task(api_key, WIRE_GH_RELEASES_ACTION, {"owner": owner, "repo": name})
        if wire_raw and (wire_raw.get("status") or "completed") not in ("failed", "error"):
            chunk, wire_urls = _wire_chunk(wire_raw, dependency_name, to_version, github_repo)
            if chunk:
                chunks.append(chunk)
                urls.extend(wire_urls)
                log_event(
                    db, investigation_id, "RESEARCH",
                    f"wire gh_repo_releases returned {len(wire_urls)} source(s) for {github_repo}",
                )
            else:
                log_event(db, investigation_id, "RESEARCH", "wire result had no usable release data", level="warn")
        else:
            log_event(db, investigation_id, "RESEARCH", f"wire gh_repo_releases failed for {github_repo}", level="warn")

    # ---- (b) Agentic search: migration/breaking-change context -------------
    prompt = (
        f"{dependency_name} python library upgrade from {from_version} to {to_version}: "
        f"official release notes, breaking changes, deprecations, and migration guide"
    )
    log_event(db, investigation_id, "RESEARCH", f"anakin agentic-search: {prompt[:100]}")
    agentic_raw = agentic_search(api_key, prompt)
    agentic_answer = _agentic_answer(agentic_raw) if agentic_raw else None
    if agentic_answer:
        chunks.append(f"## Anakin agentic research\n{agentic_answer}")
        for r in (agentic_raw.get("result") or {}).get("sources") or agentic_raw.get("sources") or []:
            if isinstance(r, dict) and r.get("url"):
                urls.append(r["url"])
        log_event(db, investigation_id, "RESEARCH", "agentic-search completed with synthesized evidence")
    else:
        # Graceful degradation INSIDE Anakin: one synchronous /search call.
        log_event(db, investigation_id, "RESEARCH", "agentic-search did not settle; trying synchronous /search", level="warn")
        sync = search(api_key, prompt, limit=5)
        if sync and sync.get("results"):
            for r in sync["results"][:5]:
                title, url, snippet = r.get("title") or "", r.get("url") or "", r.get("snippet") or ""
                chunks.append(f"## {title}\n{url}\n{snippet}")
                if url:
                    urls.append(url)
            log_event(db, investigation_id, "RESEARCH", f"collected {len(chunks)} sources via anakin /search")
        else:
            log_event(db, investigation_id, "RESEARCH", "anakin search returned no evidence", level="warn")

    if chunks:
        evidence = "\n\n".join(chunks)[:MAX_EVIDENCE_CHARS]
        return {"source": "anakin", "evidence_text": evidence, "urls": urls[:20], "anakin_raw": _trimmed_raw(wire_raw, agentic_raw)}

    log_event(
        db, investigation_id, "RESEARCH",
        "anakin produced no evidence; REASON will rely on measured data only",
        level="warn",
    )
    return _fallback_scrape(db, investigation_id, dependency_name, from_version, to_version, github_repo)


def _wire_chunk(
    wire_raw: dict[str, Any],
    dependency_name: str,
    to_version: str,
    github_repo: str,
) -> tuple[str, list[str]]:
    """Extract a release-notes chunk + urls from a gh_repo_releases job result."""
    result = wire_raw.get("result") or wire_raw.get("data") or wire_raw.get("output") or {}
    releases = result if isinstance(result, list) else (result.get("releases") or result.get("items") or [])
    if not isinstance(releases, list):
        releases = [releases]
    lines: list[str] = [f"## Wire gh_repo_releases — {github_repo}"]
    found_urls: list[str] = []
    target_tag = to_version.lstrip("v")
    for rel in releases[:5]:
        if not isinstance(rel, dict):
            continue
        tag = str(rel.get("tag_name") or rel.get("tag") or "").lstrip("v")
        body = str(rel.get("body") or rel.get("notes") or "")[:1200]
        url = rel.get("html_url") or rel.get("url") or ""
        name = rel.get("name") or tag
        if not tag and not body:
            continue
        marker = " (TARGET VERSION)" if target_tag and target_tag in tag else ""
        lines.append(f"### {name or tag}{marker}\n{url}\n{body}")
        if url:
            found_urls.append(url)
    if len(lines) <= 1:
        return "", []
    return "\n".join(lines)[:3000], found_urls


def _agentic_answer(payload: dict[str, Any]) -> str:
    """Pull the synthesized answer text out of the final agentic-search job."""
    result = payload.get("result") or {}
    for key in ("answer", "summary", "analysis", "content"):
        if isinstance(payload.get(key), str) and payload[key].strip():
            return payload[key].strip()[:4000]
    if isinstance(result, dict):
        for key in ("answer", "summary", "analysis", "content"):
            if isinstance(result.get(key), str) and result[key].strip():
                return result[key].strip()[:4000]
        if isinstance(result.get("text"), str) and result["text"].strip():
            return result["text"].strip()[:4000]
    return ""


def _trimmed_raw(
    wire_raw: dict[str, Any] | None, agentic_raw: dict[str, Any] | None
) -> dict[str, Any]:
    """Compact provenance record of the actual Anakin responses (for the event log)."""
    keep: dict[str, Any] = {}
    if wire_raw is not None:
        keep["wire"] = {"status": wire_raw.get("status"), "keys": sorted(wire_raw.keys())[:12]}
    if agentic_raw is not None:
        keep["agentic"] = {"status": agentic_raw.get("status"), "keys": sorted(agentic_raw.keys())[:12]}
    return keep


def _fallback_scrape(
    db: Database,
    investigation_id: str,
    dependency_name: str,
    from_version: str,
    to_version: str,
    github_repo: str | None,
) -> dict:
    urls: list[str] = []
    headers = {"User-Agent": USER_AGENT}
    chunks: list[str] = []

    with httpx.Client(timeout=SEARCH_TIMEOUT, headers=headers, follow_redirects=True) as client:
        # PyPI JSON API release description for the target version.
        pypi_url = f"https://pypi.org/pypi/{dependency_name}/{to_version}/json"
        try:
            resp = client.get(pypi_url)
            if resp.status_code == 200:
                data = resp.json()
                info = data.get("info") or {}
                summary = info.get("summary") or ""
                description = (info.get("description") or "")[:2500]
                project_urls = info.get("project_urls") or {}
                changelog = next(
                    (u for u in project_urls.values() if u and ("changelog" in u.lower() or "releases" in u.lower())),
                    None,
                )
                if changelog:
                    urls.append(changelog)
                chunks.append(f"## PyPI {dependency_name} {to_version}\nhttps://pypi.org/project/{dependency_name}/{to_version}/\n{summary}\n{description}")
                urls.append(f"https://pypi.org/project/{dependency_name}/{to_version}/")
                log_event(db, investigation_id, "RESEARCH", f"scraped PyPI metadata for {dependency_name} {to_version}")
        except Exception as exc:  # noqa: BLE001
            log_event(db, investigation_id, "RESEARCH", f"PyPI fetch failed: {exc}", level="warn")

        # GitHub release notes when the package lives on GitHub.
        if github_repo and len(chunks) < 2:
            gh_url = f"https://api.github.com/repos/{github_repo}/releases/tags/v{to_version}"
            try:
                resp = client.get(gh_url)
                if resp.status_code == 200:
                    data = resp.json()
                    body = (data.get("body") or "")[:2500]
                    html_url = data.get("html_url") or f"https://github.com/{github_repo}/releases/tag/v{to_version}"
                    chunks.append(f"## GitHub release v{to_version}\n{html_url}\n{body}")
                    urls.append(html_url)
                    log_event(db, investigation_id, "RESEARCH", f"scraped GitHub release v{to_version} for {github_repo}")
            except Exception as exc:  # noqa: BLE001
                log_event(db, investigation_id, "RESEARCH", f"GitHub release fetch failed: {exc}", level="warn")

    if not chunks:
        log_event(db, investigation_id, "RESEARCH", "no research evidence found; REASON will rely on measured data only", level="warn")
        return {"source": "none", "evidence_text": "", "urls": []}

    evidence = "\n\n".join(chunks)[:MAX_EVIDENCE_CHARS]
    return {"source": "fallback", "evidence_text": evidence, "urls": urls}
