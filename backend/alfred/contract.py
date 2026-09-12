"""Alfred's repo contract.

A testable repo must contain, at its root:
    Dockerfile          required — must serve the app on $PORT
    requirements.txt    required — pinned versions; Alfred bumps the candidate
    tests/              required — pytest suite
    alfred.yaml         required — workload config

``validate_repo`` enforces the contract; nothing about any single sample
project is baked in here — Alfred works on any repo following the convention.

Note: GitHub destination (owner/repo) and the GitHub token are NOT part of the
repo contract — they are supplied per-request by whoever triggers the
investigation, keeping credentials out of repos and out of Alfred.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import yaml


class RepoContractError(Exception):
    """Raised when a repo does not satisfy the Alfred contract."""


@dataclass
class WorkloadConfig:
    endpoint: str = "/health"
    method: str = "GET"
    concurrency: int = 20
    requests: int = 500
    payloads: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AlfredConfig:
    dependency_name: str
    current_version: str
    workload: WorkloadConfig


def validate_repo(repo_path: str) -> AlfredConfig:
    """Validate the contract and return the parsed alfred.yaml config.

    Raises RepoContractError with a human-readable message when the repo is
    missing any required file or the yaml is malformed.
    """
    if not os.path.isdir(repo_path):
        raise RepoContractError(f"repo path does not exist: {repo_path}")

    required = {
        "Dockerfile": os.path.isfile(os.path.join(repo_path, "Dockerfile")),
        "requirements.txt": os.path.isfile(os.path.join(repo_path, "requirements.txt")),
        "tests/": os.path.isdir(os.path.join(repo_path, "tests")),
        "alfred.yaml": os.path.isfile(os.path.join(repo_path, "alfred.yaml")),
    }
    missing = [name for name, ok in required.items() if not ok]
    if missing:
        raise RepoContractError(
            "repo does not satisfy the Alfred contract; missing: " + ", ".join(missing)
        )

    try:
        with open(os.path.join(repo_path, "alfred.yaml"), "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    except yaml.YAMLError as exc:
        raise RepoContractError(f"invalid alfred.yaml: {exc}") from exc

    dep = raw.get("dependency") or {}
    name = dep.get("name")
    current = dep.get("current")
    if not name or not current:
        raise RepoContractError("alfred.yaml must define dependency.name and dependency.current")

    workload_raw = raw.get("workload") or {}
    workload = WorkloadConfig(
        endpoint=workload_raw.get("endpoint", "/health"),
        method=str(workload_raw.get("method", "GET")).upper(),
        concurrency=int(workload_raw.get("concurrency", 20)),
        requests=int(workload_raw.get("requests", 500)),
        payloads=list(workload_raw.get("payloads") or []),
    )
    # NOTE: a legacy "github:" section in alfred.yaml is intentionally ignored.
    # Owner/repo and the token come from the per-request caller, not the repo.

    return AlfredConfig(
        dependency_name=str(name),
        current_version=str(current),
        workload=workload,
    )
