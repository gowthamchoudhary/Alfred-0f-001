"""COMPARE step — pure deterministic Python, no LLM involved.

For each metric: absolute_delta and percentage_delta. Compatibility scores:

    functional_score  = tests_passed_candidate / tests_passed_baseline
    performance_score = 1 - max(0, (p95_candidate - p95_baseline) / p95_baseline)
    overall           = 0.6 * functional_score + 0.4 * performance_score
"""

from __future__ import annotations


def _pct(old: float, new: float) -> float | None:
    if old in (None, 0):
        return None
    return round((new - old) / old * 100.0, 2)


def _metric(baseline: float | None, candidate: float | None) -> dict:
    baseline = baseline if baseline is not None else 0
    candidate = candidate if candidate is not None else 0
    delta = candidate - baseline
    return {
        "baseline": baseline,
        "candidate": candidate,
        "absolute_delta": round(delta, 4),
        "percentage_delta": _pct(baseline, candidate),
    }


def compare_results(baseline_run: dict, candidate_run: dict) -> dict:
    """Build the comparison object from the two measured runs."""
    baseline = {
        "build_success": bool(baseline_run.get("build_success")),
        "startup_success": bool(baseline_run.get("startup_success")),
        "tests_passed": baseline_run.get("tests_passed") or 0,
        "tests_failed": baseline_run.get("tests_failed") or 0,
        "tests_errors": baseline_run.get("tests_errors") or 0,
        "latency_p50_ms": baseline_run.get("latency_p50_ms") or 0.0,
        "latency_p95_ms": baseline_run.get("latency_p95_ms") or 0.0,
        "latency_p99_ms": baseline_run.get("latency_p99_ms") or 0.0,
        "error_rate": baseline_run.get("error_rate") or 0.0,
        "throughput_rps": baseline_run.get("throughput_rps") or 0.0,
    }
    candidate = {
        "build_success": bool(candidate_run.get("build_success")),
        "startup_success": bool(candidate_run.get("startup_success")),
        "tests_passed": candidate_run.get("tests_passed") or 0,
        "tests_failed": candidate_run.get("tests_failed") or 0,
        "tests_errors": candidate_run.get("tests_errors") or 0,
        "latency_p50_ms": candidate_run.get("latency_p50_ms") or 0.0,
        "latency_p95_ms": candidate_run.get("latency_p95_ms") or 0.0,
        "latency_p99_ms": candidate_run.get("latency_p99_ms") or 0.0,
        "error_rate": candidate_run.get("error_rate") or 0.0,
        "throughput_rps": candidate_run.get("throughput_rps") or 0.0,
    }

    functional_score = 1.0
    if baseline["tests_passed"] > 0:
        functional_score = candidate["tests_passed"] / baseline["tests_passed"]
    elif candidate["tests_passed"] > 0:
        functional_score = 1.0

    performance_score = 1.0
    if baseline["latency_p95_ms"] > 0:
        performance_score = 1.0 - max(
            0.0, (candidate["latency_p95_ms"] - baseline["latency_p95_ms"]) / baseline["latency_p95_ms"]
        )
    performance_score = max(0.0, min(1.0, performance_score))

    overall = round(0.6 * functional_score + 0.4 * performance_score, 4)

    return {
        "metrics": {
            "tests_passed": _metric(baseline["tests_passed"], candidate["tests_passed"]),
            "tests_failed": _metric(baseline["tests_failed"], candidate["tests_failed"]),
            "tests_errors": _metric(baseline["tests_errors"], candidate["tests_errors"]),
            "latency_p50_ms": _metric(baseline["latency_p50_ms"], candidate["latency_p50_ms"]),
            "latency_p95_ms": _metric(baseline["latency_p95_ms"], candidate["latency_p95_ms"]),
            "latency_p99_ms": _metric(baseline["latency_p99_ms"], candidate["latency_p99_ms"]),
            "error_rate": _metric(baseline["error_rate"], candidate["error_rate"]),
            "throughput_rps": _metric(baseline["throughput_rps"], candidate["throughput_rps"]),
        },
        "environment_health": {
            "baseline": {
                "build_success": baseline["build_success"],
                "startup_success": baseline["startup_success"],
            },
            "candidate": {
                "build_success": candidate["build_success"],
                "startup_success": candidate["startup_success"],
            },
        },
        "scores": {
            "functional_score": round(min(1.0, max(0.0, functional_score)), 4),
            "performance_score": round(performance_score, 4),
            "overall_score": overall,
        },
    }
