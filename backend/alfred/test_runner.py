"""TEST step — run the repo's own pytest suite inside each container.

Command: ``docker exec <container> pytest tests/ -q --no-header``
The summary line is parsed for passed/failed/error counts — no pytest plugins
required, keeping the repo contract minimal.
"""

from __future__ import annotations

import re
import subprocess

from .db import Database
from .events import log_event

PYTEST_TIMEOUT = 600

_SUMMARY_PATTERNS = [
    # e.g. "3 failed, 2 errors, 10 passed in 1.23s"  (order-agnostic)
    re.compile(r"(?P<count>\d+)\s+(?P<kind>passed|failed|error)s?", re.IGNORECASE),
]
_FAILED_RE = re.compile(r"(\d+) failed", re.IGNORECASE)
_ERROR_RE = re.compile(r"(\d+) error", re.IGNORECASE)
_PASSED_RE = re.compile(r"(\d+) passed", re.IGNORECASE)
_NO_TESTS_RE = re.compile(r"no tests ran", re.IGNORECASE)


def parse_pytest_summary(output: str) -> dict:
    """Extract passed/failed/errors from a pytest summary line."""
    summary_line = ""
    for line in reversed(output.splitlines()):
        if "passed" in line or "failed" in line or "error" in line or _NO_TESTS_RE.search(line):
            summary_line = line.strip()
            break

    if _NO_TESTS_RE.search(summary_line):
        return {"passed": 0, "failed": 0, "errors": 0, "summary_line": summary_line or "no tests ran"}

    passed = _PASSED_RE.search(summary_line)
    failed = _FAILED_RE.search(summary_line)
    errors = _ERROR_RE.search(summary_line)
    return {
        "passed": int(passed.group(1)) if passed else 0,
        "failed": int(failed.group(1)) if failed else 0,
        "errors": int(errors.group(1)) if errors else 0,
        "summary_line": summary_line,
    }


def run_tests_in_container(
    db: Database,
    investigation_id: str,
    container_name: str,
) -> dict:
    """Execute pytest inside the container and return the parsed summary."""
    log_event(db, investigation_id, "TEST", f"docker exec {container_name} pytest tests/ -q --no-header")
    try:
        proc = subprocess.run(
            ["docker", "exec", container_name, "pytest", "tests/", "-q", "--no-header"],
            capture_output=True,
            text=True,
            timeout=PYTEST_TIMEOUT,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        return {
            "tests_passed": 0,
            "tests_failed": 0,
            "tests_errors": 1,
            "tests_total": 0,
            "pytest_summary": f"pytest timed out after {PYTEST_TIMEOUT}s",
            "raw_output": "",
        }
    except OSError as exc:
        return {
            "tests_passed": 0,
            "tests_failed": 0,
            "tests_errors": 1,
            "tests_total": 0,
            "pytest_summary": f"failed to execute pytest: {exc}",
            "raw_output": "",
        }

    parsed = parse_pytest_summary(output)
    total = parsed["passed"] + parsed["failed"] + parsed["errors"]
    log_event(
        db,
        investigation_id,
        "TEST",
        f"{container_name}: {parsed['summary_line'] or f'exit {exit_code}'}",
        level="info" if parsed["failed"] == 0 and parsed["errors"] == 0 else "warn",
    )
    return {
        "tests_passed": parsed["passed"],
        "tests_failed": parsed["failed"],
        "tests_errors": parsed["errors"],
        "tests_total": total,
        "pytest_summary": parsed["summary_line"] or f"exit code {exit_code}",
        "raw_output": output[-20000:],
    }
