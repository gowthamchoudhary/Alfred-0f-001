"""PREPARE step — stage baseline and candidate copies of the target repo.

Supports both local paths and remote git URLs (https://... or git@...):
remote sources are fetched with ``git clone --depth 1`` into a temp dir, then
copied twice. The dependency bump is applied ONLY to the candidate copy's
requirements.txt. No version values are hardcoded here — everything comes from
the repo's alfred.yaml plus the requested target version.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile

from .events import log_event
from .db import Database

RESERVED_ENV_NAMES = {"baseline", "candidate"}


def _rmtree_force(path: str) -> None:
    """shutil.rmtree that clears the read-only bit git sets on pack files.

    Plain rmtree silently leaves .git fragments behind on Windows
    (ignore_errors swallows the PermissionErrors), which is exactly how a
    half-deleted clone once got copied as a 'baseline'.
    """
    import stat

    def _onerror(func, failed_path, _exc_info):
        try:
            os.chmod(failed_path, stat.S_IWRITE)
            func(failed_path)
        except Exception:  # noqa: BLE001 — best-effort cleanup of a temp dir
            pass

    shutil.rmtree(path, ignore_errors=True, onerror=_onerror)


def _is_git_url(source: str) -> bool:
    return bool(re.match(r"^(https?://|git@)", source)) or source.endswith(".git")


def _clone(source: str, dest: str) -> None:
    subprocess.run(
        ["git", "clone", "--depth", "1", source, dest],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )


def stage_environments(
    db: Database,
    investigation_id: str,
    source: str,
    dependency_name: str,
    target_version: str,
    workdir: str,
) -> dict:
    """Create <workdir>/baseline and <workdir>/candidate; bump the candidate.

    Returns:
        {
          "baseline_path": str,
          "candidate_path": str,
          "bump_applied": bool,
          "baseline_requirements": str,
          "candidate_requirements": str,
        }
    """
    os.makedirs(workdir, exist_ok=True)
    baseline = os.path.join(workdir, "baseline")
    candidate = os.path.join(workdir, "candidate")

    tmp_clone: str | None = None
    if _is_git_url(source):
        tmp_clone = tempfile.mkdtemp(prefix="alfred-clone-")
        try:
            log_event(db, investigation_id, "PREPARE", f"git clone --depth 1 {source}")
            _clone(source, tmp_clone)
        except subprocess.CalledProcessError as exc:
            _rmtree_force(tmp_clone)
            raise RuntimeError(
                f"git clone failed: {exc.stderr.strip()[:500]}"
            ) from exc
        except Exception:
            _rmtree_force(tmp_clone)
            raise
        src = tmp_clone
    else:
        src = os.path.abspath(source)

    # Copy while the source still exists — the clone temp dir must outlive
    # these two calls (a finally-rmtree here used to delete it first, so the
    # copies ran against a deleted dir and the bump step then failed with
    # FileNotFoundError on baseline/requirements.txt).
    try:
        shutil.copytree(src, baseline, dirs_exist_ok=True)
        shutil.copytree(src, candidate, dirs_exist_ok=True)
    finally:
        if tmp_clone:
            _rmtree_force(tmp_clone)

    bump_applied = False
    baseline_req = _read_requirements(baseline)
    candidate_req = baseline_req
    if target_version:
        bumped = _bump_dependency(candidate_req, dependency_name, target_version)
        if bumped is None:
            log_event(
                db,
                investigation_id,
                "PREPARE",
                f"{dependency_name} not pinned in requirements.txt; candidate left untouched",
                level="warn",
            )
        else:
            candidate_req = bumped
            _write_requirements(candidate, candidate_req)
            bump_applied = True
            log_event(
                db,
                investigation_id,
                "PREPARE",
                f"bumped {dependency_name} to {target_version} in candidate requirements.txt",
            )

    return {
        "baseline_path": baseline,
        "candidate_path": candidate,
        "bump_applied": bump_applied,
        "baseline_requirements": baseline_req,
        "candidate_requirements": candidate_req,
    }


def _read_requirements(repo_path: str) -> str:
    path = os.path.join(repo_path, "requirements.txt")
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _write_requirements(repo_path: str, content: str) -> None:
    path = os.path.join(repo_path, "requirements.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def _bump_dependency(content: str, package: str, version: str) -> str | None:
    """Rewrite ``package==<old>`` to ``package==<version>`` in requirements text."""
    pattern = re.compile(
        rf"(?im)^(\s*)({re.escape(package)}(?:\[[^\]]+\])?)\s*==\s*[^#\s;]+(.*)$"
    )
    new_content, count = pattern.subn(
        lambda m: f"{m.group(1)}{m.group(2)}=={version}{m.group(3)}",
        content,
    )
    return new_content if count else None
