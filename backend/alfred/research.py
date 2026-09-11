"""RESEARCH step — one targeted web search per investigation.

Gathers release-notes / migration-guide / breaking-changes context for the
specific version bump being tested, to feed the REASON step as ground truth.

Primary path: Exa search API (needs ``EXA_API_KEY``), one call, results
include highlights. Fallback (no key): direct scrape of the package's PyPI
release page / GitHub release page — still real evidence, just narrower.
The pipeline must never crash or block on research; failures are logged and
returned as empty evidence.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from .db import Database
from .events import log_event

EXA_ENDPOINT = "https://api.exa.ai/search"
SEARCH_TIMEOUT = 20.0
USER_AGENT = "Alfred-ReleaseImpactAgent/0.1 (release research; contact: alfred local)"


def research_dependency(
    db: Database,
    investigation_id: str,
    dependency_name: str,
    from_version: str,
    to_version: str,
    github_repo: str | None = None,
) -> dict:
    """Return {'source': 'exa'|'fallback'|'none', 'evidence_text': str, 'urls': [...]}."""
    query = (
        f"{dependency_name} python {to_version} release notes breaking changes migration guide "
        f"upgrade from {from_version}"
    )
    api_key = None
    try:
        import os

        api_key = os.environ.get("EXA_API_KEY")
    except Exception:  # pragma: no cover
        pass

    if api_key:
        result = _search_exa(db, investigation_id, query, api_key)
        if result:
            return result

    return _fallback_scrape(db, investigation_id, dependency_name, from_version, to_version, github_repo)


def _search_exa(db: Database, investigation_id: str, query: str, api_key: str) -> dict | None:
    log_event(db, investigation_id, "RESEARCH", f"exa search: {query[:100]}")
    try:
        resp = httpx.post(
            EXA_ENDPOINT,
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
            json={
                "query": query,
                "numResults": 4,
                "contents": {"highlights": {"numSentences": 3}, "text": {"maxCharacters": 1200}},
            },
            timeout=SEARCH_TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001 — research must never block the pipeline
        log_event(db, investigation_id, "RESEARCH", f"exa search failed: {exc}", level="warn")
        return None

    results = payload.get("results") or []
    chunks: list[str] = []
    urls: list[str] = []
    for item in results[:4]:
        title = item.get("title") or ""
        url = item.get("url") or ""
        highlights = item.get("highlights") or []
        text = item.get("text") or ""
        chunk = f"## {title}\n{url}\n" + "\n".join(highlights[:2] or [text[:600]])
        chunks.append(chunk)
        if url:
            urls.append(url)

    if not chunks:
        log_event(db, investigation_id, "RESEARCH", "exa returned no results", level="warn")
        return None

    evidence = "\n\n".join(chunks)[:8000]
    log_event(db, investigation_id, "RESEARCH", f"collected {len(urls)} evidence sources via exa")
    return {"source": "exa", "evidence_text": evidence, "urls": urls}


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

    evidence = "\n\n".join(chunks)[:8000]
    return {"source": "fallback", "evidence_text": evidence, "urls": urls}
