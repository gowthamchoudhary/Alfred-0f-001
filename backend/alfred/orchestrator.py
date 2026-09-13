"""Orchestrator — run_investigation(), the full 10-step pipeline.

    PREPARE → BUILD → RUN → TEST → WORKLOAD → COMPARE → REASON → ACTION → VERIFY → CLEANUP

Every step logs a timestamped event line. CLEANUP always stops and removes
both containers (try/finally), even when earlier steps fail. Build/startup
failures are valid, reportable results, not crashes.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import threading
import uuid
from typing import Any

from .candidate import stage_environments
from .compare import compare_results
from .contract import AlfredConfig, RepoContractError, validate_repo
from .db import Database
from .docker_runner import DockerUnavailableError, _docker_available, build_image, run_container
from .events import log_event
from .github_action import post_github_issue
from .reason import reason_about_update
from .research import research_dependency
from .test_runner import run_tests_in_container
from .workload import run_workload

BASE_PORT = 18200
_cleanup_lock = threading.Lock()


def _free_port(start: int) -> int:
    """Pick a free TCP port starting at ``start`` (probes then releases)."""
    port = start
    for _ in range(100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", port))
                return port
            except OSError:
                port += 1
    return start


def _stop_container(container_name: str) -> None:
    with _cleanup_lock:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, timeout=60)


def run_investigation(
    db: Database,
    repo_source: str,
    target_version: str,
    dependency_name: str | None = None,
    workload_config: Any = None,
    github_token: str | None = None,
    github_owner: str | None = None,
    github_repo: str | None = None,
    trigger: str = "manual",
    user_id: str | None = None,
) -> str:
    """Execute the full pipeline for one dependency bump; returns investigation id.

    ``dependency_name``/``workload_config`` override the repo's alfred.yaml
    when provided (discovery passes the watched dep).

    ``github_token``/``github_owner``/``github_repo`` are PER-REQUEST user
    credentials — used in-memory for ACTION/VERIFY only, never persisted or
    logged. When the token is absent, ACTION is skipped cleanly.
    """
    if not _docker_available():
        raise DockerUnavailableError(
            "docker daemon is not reachable; Alfred executes real containers and cannot run without it"
        )

    workdir = tempfile.mkdtemp(prefix="alfred-run-")
    baseline_tag = f"alfred/{uuid.uuid4().hex[:10]}-baseline"
    candidate_tag = f"alfred/{uuid.uuid4().hex[:10]}-candidate"
    containers: list[str] = []
    inv_id = "pending"
    try:
        # ---- PREPARE -----------------------------------------------------
        staged = stage_environments(db, inv_id, repo_source, dependency_name or "", target_version, workdir)
        config: AlfredConfig = validate_repo(staged["candidate_path"])
        dep_name = dependency_name or config.dependency_name
        baseline_version = config.current_version

        # Now that we know the id-able values, create the investigation row
        # and replay the PREPARE events under the real investigation id.
        inv_id = db.create_investigation(
            dependency_name=dep_name,
            baseline_version=baseline_version,
            candidate_version=target_version,
            repo_source=repo_source,
            trigger=trigger,
            user_id=user_id,
        )
        db.log_event(inv_id, "PREPARE", f"staged baseline and candidate copies from {repo_source}")
        if staged["bump_applied"]:
            db.log_event(
                inv_id, "PREPARE",
                f"bumped {dep_name} to {target_version} in candidate requirements.txt",
            )
        else:
            db.log_event(
                inv_id, "PREPARE",
                f"no pinned {dep_name} requirement found; candidate requirements.txt left as-is",
                level="warn",
            )

        wl = workload_config or config.workload

        db.update_investigation(inv_id, current_step="BUILD")

        # ---- BUILD -------------------------------------------------------
        baseline_build = build_image(db, inv_id, staged["baseline_path"], baseline_tag)
        candidate_build = build_image(db, inv_id, staged["candidate_path"], candidate_tag)

        # ---- RUN + TEST + WORKLOAD (per environment) ----------------------
        db.update_investigation(inv_id, current_step="RUN")

        def _execute_environment(tag: str, env: str, build_result: dict) -> dict:
            run_data: dict[str, Any] = {"build_success": build_result["build_success"],
                                        "build_log": build_result["build_log"]}
            if not build_result["build_success"]:
                run_data.update({
                    "startup_success": False,
                    "startup_log": "skipped: image build failed",
                    "tests_passed": 0, "tests_failed": 0, "tests_errors": 0, "tests_total": 0,
                    "pytest_summary": "skipped: image build failed",
                })
                return run_data

            port = _free_port(BASE_PORT)
            cname = f"alfred-{inv_id}-{env}-{uuid.uuid4().hex[:6]}"
            containers.append(cname)
            started = run_container(db, inv_id, tag, cname, port)
            run_data.update(started)

            if not started["startup_success"]:
                run_data.update({
                    "tests_passed": 0, "tests_failed": 0, "tests_errors": 0, "tests_total": 0,
                    "pytest_summary": "skipped: container failed to start",
                })
                return run_data

            db.update_investigation(inv_id, current_step="TEST")
            run_data.update(run_tests_in_container(db, inv_id, cname))

            db.update_investigation(inv_id, current_step="WORKLOAD")
            workload = run_workload(db, inv_id, f"http://127.0.0.1:{port}", wl, env)
            # Merge diagnostics: the workload's raw_output must not clobber the
            # pytest raw_output captured above (same key in both dicts).
            workload_raw = workload.pop("raw_output", "")
            if workload_raw:
                run_data["raw_output"] = ((run_data.get("raw_output") or "") + "\n" + workload_raw).strip()
            run_data.update(workload)
            return run_data

        baseline_run = _execute_environment(baseline_tag, "baseline", baseline_build)
        db.save_test_run(inv_id, "baseline", baseline_run)
        candidate_run = _execute_environment(candidate_tag, "candidate", candidate_build)
        db.save_test_run(inv_id, "candidate", candidate_run)

        # ---- COMPARE ------------------------------------------------------
        db.update_investigation(inv_id, current_step="COMPARE")
        comparison = compare_results(baseline_run, candidate_run)
        db.save_comparison(inv_id, comparison)
        score = comparison["scores"]["overall_score"]
        log_event(db, inv_id, "COMPARE", f"compatibility score {score:.4f}")

        # ---- RESEARCH (feeds REASON) ---------------------------------------
        research = research_dependency(
            db, inv_id, dep_name, baseline_version, target_version,
            github_repo=f"{github_owner}/{github_repo}" if github_owner and github_repo else None,
        )

        # ---- REASON --------------------------------------------------------
        db.update_investigation(inv_id, current_step="REASON")
        decision = reason_about_update(
            db, inv_id, comparison, research, dep_name, baseline_version, target_version
        )
        db.save_decision(
            inv_id, decision["verdict"], decision["confidence"],
            decision["reasons"], decision["recommendation"],
            decided_by="llm_groq" if os.environ.get("GROQ_API_KEY") else "rule_based",
        )

        # ---- ACTION + VERIFY ----------------------------------------------
        db.update_investigation(inv_id, current_step="ACTION")
        action = post_github_issue(
            db, inv_id, github_token, github_owner, github_repo,
            dep_name, baseline_version, target_version,
            comparison, decision, research, scores=comparison["scores"],
        )
        db.save_action(inv_id, action)

        # ---- finalize -------------------------------------------------------
        db.update_investigation(
            inv_id,
            status="complete",
            current_step="CLEANUP",
            verdict=decision["verdict"],
            confidence=decision["confidence"],
            compatibility_score=score,
            github_issue_url=action.get("issue_url"),
            completed_at=__import__("time").time(),
        )
        log_event(db, inv_id, "CLEANUP", f"investigation complete: verdict {decision['verdict']}")
        return inv_id

    except RepoContractError as exc:
        if inv_id != "pending":
            db.update_investigation(inv_id, status="failed", error=str(exc), completed_at=__import__("time").time())
            log_event(db, inv_id, "PREPARE", f"repo contract violation: {exc}", level="error")
        raise
    except Exception as exc:  # noqa: BLE001 — record then re-raise for API surfacing
        if inv_id != "pending":
            db.update_investigation(inv_id, status="failed", error=str(exc)[:500], completed_at=__import__("time").time())
            log_event(db, inv_id, "PIPELINE", f"investigation failed: {exc}", level="error")
        raise
    finally:
        # ---- CLEANUP — always stop/remove containers ------------------------
        for cname in containers:
            try:
                _stop_container(cname)
            except Exception:  # noqa: BLE001
                pass
        shutil.rmtree(workdir, ignore_errors=True)
        if inv_id != "pending":
            try:
                db.log_event(inv_id, "CLEANUP", "containers removed and workspace cleaned")
            except Exception:  # noqa: BLE001
                pass
