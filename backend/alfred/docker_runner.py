"""BUILD and RUN steps — real Docker execution, never simulated.

Build failure and startup failure are both valid, reportable results: they are
captured into the run record and flow through comparison normally instead of
crashing the pipeline.
"""

from __future__ import annotations

import subprocess
import time

from .db import Database
from .events import log_event

BUILD_TIMEOUT = 600        # seconds
HEALTH_TIMEOUT = 120       # seconds for container startup/health
HEALTH_POLL_INTERVAL = 2.0
MEMORY_LIMIT = "512m"
CPU_LIMIT = "1"


class DockerUnavailableError(RuntimeError):
    """Raised when the docker daemon is unreachable."""


def _docker_available() -> bool:
    try:
        proc = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=15,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _run_cmd(cmd: list[str], timeout: int) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired as exc:
        return 124, (exc.stdout or "") + (exc.stderr or "") + f"\n[alfred] command timed out after {timeout}s"
    except OSError as exc:
        return 125, f"[alfred] failed to execute {cmd[0]}: {exc}"


def build_image(
    db: Database,
    investigation_id: str,
    repo_path: str,
    tag: str,
) -> dict:
    """docker build a repo into ``tag``. Returns build_success + build_log."""
    log_event(db, investigation_id, "BUILD", f"docker build {repo_path} -> {tag}")
    code, output = _run_cmd(["docker", "build", "-t", tag, repo_path], BUILD_TIMEOUT)
    success = code == 0
    log_event(
        db,
        investigation_id,
        "BUILD",
        f"build {'succeeded' if success else f'FAILED (exit {code})'} for {tag}",
        level="info" if success else "error",
    )
    return {"build_success": success, "build_log": output[-20000:]}


def run_container(
    db: Database,
    investigation_id: str,
    tag: str,
    container_name: str,
    host_port: int,
) -> dict:
    """docker run with resource limits; poll TCP until the app answers."""
    log_event(
        db,
        investigation_id,
        "RUN",
        f"docker run {tag} as {container_name} on host port {host_port} (memory {MEMORY_LIMIT}, cpus {CPU_LIMIT})",
    )
    cmd = [
        "docker", "run", "-d",
        "--name", container_name,
        "--memory", MEMORY_LIMIT,
        "--cpus", CPU_LIMIT,
        "-e", "PORT=8000",  # the contract: app listens on $PORT; Alfred pins it
        "-p", f"{host_port}:8000",
        tag,
    ]
    code, output = _run_cmd(cmd, 60)
    if code != 0:
        return {"startup_success": False, "startup_log": output[-10000:], "container_name": container_name}

    # Wait for the app to accept TCP connections (container port is 8000
    # inside; the repo contract says the app must listen on $PORT which
    # Docker's -p maps to the container's 8000 by convention).
    deadline = time.time() + HEALTH_TIMEOUT
    last_err = ""
    while time.time() < deadline:
        code_c, out_c = _run_cmd(
            ["docker", "exec", container_name, "python", "-c",
             "import socket;s=socket.socket();s.settimeout(1);"
             "exit(0) if s.connect_ex(('127.0.0.1',8000))==0 else exit(1)"],
            15,
        )
        if code_c == 0:
            log_event(db, investigation_id, "RUN", f"{container_name} is accepting connections on 8000")
            return {"startup_success": True, "startup_log": output[-10000:], "container_name": container_name}
        last_err = out_c
        time.sleep(HEALTH_POLL_INTERVAL)

    logs = _run_cmd(["docker", "logs", container_name], 15)[1]
    return {
        "startup_success": False,
        "startup_log": (output + "\n" + logs + "\n" + last_err)[-15000:],
        "container_name": container_name,
    }
