"""Backend unit tests for Alfred's deterministic components.

These run without Docker or network access — they verify the pure logic of
the pipeline (bumping, parsing, comparing, triaging, persistence).
"""

from __future__ import annotations

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from alfred.candidate import _bump_dependency
from alfred.compare import compare_results
from alfred.contract import RepoContractError, validate_repo
from alfred.db import Database
from alfred.test_runner import parse_pytest_summary
from alfred.triage import deterministic_triage, is_major_bump, is_pre_release, parse_version


# ------------------------------------------------------------------- bumping
def test_bump_dependency_rewrites_pin():
    req = "fastapi==0.110.0\nopenai==1.99.0\n# comment\nanthropic==0.30.1\n"
    out = _bump_dependency(req, "openai", "2.1.0")
    assert "openai==2.1.0" in out
    assert "openai==1.99.0" not in out
    assert "fastapi==0.110.0" in out
    assert "anthropic==0.30.1" in out


def test_bump_dependency_with_extras():
    req = "openai[embeddings]==1.99.0\n"
    out = _bump_dependency(req, "openai", "1.100.2")
    assert "openai[embeddings]==1.100.2" in out


def test_bump_dependency_missing_returns_none():
    assert _bump_dependency("requests==2.0.0\n", "openai", "1.0.0") is None


# ------------------------------------------------------------ pytest parsing
def test_parse_pytest_summary_all_pass():
    parsed = parse_pytest_summary("tests/test_x.py ..\n10 passed in 1.23s")
    assert parsed == {"passed": 10, "failed": 0, "errors": 0, "summary_line": "10 passed in 1.23s"}


def test_parse_pytest_summary_mixed():
    parsed = parse_pytest_summary("3 failed, 2 errors, 10 passed in 1.23s")
    assert parsed["passed"] == 10
    assert parsed["failed"] == 3
    assert parsed["errors"] == 2


def test_parse_pytest_summary_no_tests():
    parsed = parse_pytest_summary("no tests ran in 0.01s")
    assert parsed["passed"] == 0 and parsed["failed"] == 0


# ---------------------------------------------------------------- comparison
def _run(passed, p95, build=True, startup=True, err_rate=0.0):
    return {
        "build_success": build,
        "startup_success": startup,
        "tests_passed": passed,
        "tests_failed": 0,
        "tests_errors": 0,
        "latency_p50_ms": p95 * 0.5,
        "latency_p95_ms": p95,
        "latency_p99_ms": p95 * 1.2,
        "error_rate": err_rate,
        "throughput_rps": 100.0,
    }


def test_compare_identical_scores_perfect():
    c = compare_results(_run(10, 200), _run(10, 200))
    assert c["scores"]["functional_score"] == 1.0
    assert c["scores"]["performance_score"] == 1.0
    assert c["scores"]["overall_score"] == 1.0


def test_compare_regression_lowers_scores():
    c = compare_results(_run(10, 200), _run(5, 400))
    assert c["scores"]["functional_score"] == 0.5
    # p95 doubled → performance score 0
    assert c["scores"]["performance_score"] == 0.0
    assert c["scores"]["overall_score"] == pytest.approx(0.6 * 0.5 + 0.4 * 0.0)


def test_compare_improvement_caps_at_one():
    c = compare_results(_run(10, 400), _run(10, 100))
    assert c["scores"]["functional_score"] == 1.0
    assert c["scores"]["performance_score"] == 1.0
    assert c["scores"]["overall_score"] == 1.0


def test_compare_records_deltas():
    c = compare_results(_run(10, 200), _run(8, 220))
    tests = c["metrics"]["tests_passed"]
    assert tests["absolute_delta"] == -2
    assert tests["percentage_delta"] == pytest.approx(-20.0)
    p95 = c["metrics"]["latency_p95_ms"]
    assert p95["percentage_delta"] == pytest.approx(10.0)


# -------------------------------------------------------------------- triage
def test_parse_version_and_major_bump():
    assert parse_version("2.0.1") == (2, 0, 1)
    assert is_major_bump("1.9.9", "2.0.0")
    assert not is_major_bump("1.9.9", "1.10.0")


def test_is_pre_release():
    assert is_pre_release("2.0.0rc1")
    assert is_pre_release("1.2.3b2")
    assert not is_pre_release("1.2.3")


def test_deterministic_triage_major_bump_accepted():
    status, reason = deterministic_triage({"latest_version": "2.0.0", "release_notes": ""}, "1.5.0")
    assert status == "accepted"
    assert "major version bump" in reason


def test_deterministic_triage_breaking_keyword_accepted():
    status, _ = deterministic_triage(
        {"latest_version": "1.3.0", "release_notes": "This release deprecates the old client API."}, "1.2.0"
    )
    assert status == "accepted"


def test_deterministic_triage_trivial_skipped():
    result = deterministic_triage({"latest_version": "1.2.1", "release_notes": "Minor bug fixes."}, "1.2.0")
    assert result is None  # ambiguous → falls to LLM path (skipped without key)


def test_deterministic_triage_pre_release_skipped():
    status, _ = deterministic_triage({"latest_version": "2.0.0rc1", "release_notes": ""}, "1.9.0")
    assert status == "skipped"


def test_deterministic_triage_older_version_skipped():
    status, _ = deterministic_triage({"latest_version": "1.1.0", "release_notes": ""}, "1.2.0")
    assert status == "skipped"


# ----------------------------------------------------------------------- db
def test_db_investigation_lifecycle():
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(os.path.join(tmp, "test.db"))
        inv_id = db.create_investigation("openai", "1.0.0", "2.0.0", "/tmp/repo")
        db.update_investigation(inv_id, status="complete", verdict="SAFE", compatibility_score=0.97)
        inv = db.get_investigation(inv_id)
        assert inv["status"] == "complete"
        assert inv["verdict"] == "SAFE"

        db.log_event(inv_id, "BUILD", "docker build ok")
        assert len(db.list_events(inv_id)) == 1

        db.save_test_run(inv_id, "baseline", _run(10, 200))
        runs = db.list_test_runs(inv_id)
        assert runs[0]["environment"] == "baseline"
        assert runs[0]["latency_p95_ms"] == 200

        db.save_comparison(inv_id, compare_results(_run(10, 200), _run(10, 200)))
        assert db.get_comparison(inv_id)["scores"]["overall_score"] == 1.0

        db.save_decision(inv_id, "SAFE", 0.9, ["all good"], "ship it", "rule_based")
        d = db.get_decision(inv_id)
        assert d["verdict"] == "SAFE" and d["reasons"] == ["all good"]

        db.save_action(inv_id, {"success": True, "verified": True, "issue_url": "https://example.com/1", "issue_number": 1})
        assert bool(db.get_action(inv_id)["verified"]) is True


def test_db_detected_changes_dedup():
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(os.path.join(tmp, "test.db"))
        change = {"dependency_name": "openai", "source": "pypi", "latest_version": "2.0.0"}
        first = db.upsert_detected_change(change)
        assert first is not None and first["id"]
        assert db.upsert_detected_change(change) is None  # duplicate ignored
        db.mark_change_triaged(first["id"], "skipped", "low relevance", "deterministic")
        assert db.list_detected_changes(status="skipped")[0]["triage_reason"] == "low relevance"


def test_db_watchlist():
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(os.path.join(tmp, "test.db"))
        db.add_watchlist_entry("openai", "pypi")
        db.add_watchlist_entry("openai", "pypi")  # idempotent
        assert len(db.list_watchlist()) == 1
        db.update_watchlist_status("openai", "2.0.0")
        assert db.list_watchlist()[0]["last_seen_version"] == "2.0.0"
        db.remove_watchlist_entry("openai")
        assert db.list_watchlist() == []


# ------------------------------------------------------------------ contract
def test_validate_repo_enforces_contract(tmp_path):
    for f in ("Dockerfile", "requirements.txt", "alfred.yaml"):
        (tmp_path / f).write_text("placeholder\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "alfred.yaml").write_text(
        "dependency:\n  name: openai\n  current: '1.0.0'\n"
        "workload:\n  endpoint: /chat\n  method: POST\n  concurrency: 5\n  requests: 10\n"
        "  payloads:\n    - message: hi\n"
        "github:\n  owner: o\n  repo: r\n"
    )
    cfg = validate_repo(str(tmp_path))
    assert cfg.dependency_name == "openai"
    assert cfg.workload.endpoint == "/chat"
    assert cfg.github.owner == "o"


def test_validate_repo_rejects_missing_files(tmp_path):
    (tmp_path / "Dockerfile").write_text("x")
    with pytest.raises(RepoContractError):
        validate_repo(str(tmp_path))
