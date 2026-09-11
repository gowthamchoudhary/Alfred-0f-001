"""REASON step — ONE LLM call (Claude) over real evidence.

The LLM receives the deterministic comparison object plus web evidence as
ground truth and must reason over it — never invent numbers. Output is
structured JSON:

    { verdict: SAFE|SAFE_WITH_REVIEW|MODERATE_RISK|HIGH_RISK|INCOMPATIBLE,
      confidence: float, reasons: [...], recommendation: str }

If ``ANTHROPIC_API_KEY`` is unset (or the call fails), a deterministic
rule-based verdict is derived from the compatibility score:

    >= 95 SAFE | >= 80 SAFE_WITH_REVIEW | >= 60 MODERATE_RISK | else HIGH_RISK
    (INCOMPATIBLE overrides when the candidate build/startup/tests collapse)

The pipeline must never crash from a missing key.
"""

from __future__ import annotations

import json
import os

from .db import Database
from .events import log_event

ANTHROPIC_MODEL = "claude-sonnet-4-5"
MAX_TOKENS = 1500

VALID_VERDICTS = {"SAFE", "SAFE_WITH_REVIEW", "MODERATE_RISK", "HIGH_RISK", "INCOMPATIBLE"}

_SYSTEM_PROMPT = (
    "You are Alfred, a release-impact analyst. You are given REAL measured "
    "results from running a test suite and workload against a dependency's "
    "baseline and candidate versions, plus web research evidence. You must "
    "NEVER invent numbers — every figure you cite must come from the provided "
    "data. If evidence is missing, say so. Answer with ONLY a JSON object, no "
    "markdown fences, matching: {\"verdict\": one of SAFE|SAFE_WITH_REVIEW|"
    "MODERATE_RISK|HIGH_RISK|INCOMPATIBLE, \"confidence\": 0.0-1.0, "
    "\"reasons\": [short strings citing the measured numbers], "
    "\"recommendation\": one sentence}"
)


def _rule_based_verdict(comparison: dict) -> dict:
    score = float((comparison.get("scores") or {}).get("overall_score") or 0.0)
    health = comparison.get("environment_health") or {}
    cand = health.get("candidate") or {}
    tests = (comparison.get("metrics") or {}).get("tests_passed") or {}

    if not cand.get("build_success") or not cand.get("startup_success"):
        verdict, confidence = "INCOMPATIBLE", 0.95
        reasons = [
            f"candidate environment failed to {'build' if not cand.get('build_success') else 'start'}"
        ]
    elif tests.get("candidate", 0) == 0 and tests.get("baseline", 0) > 0:
        verdict, confidence = "INCOMPATIBLE", 0.9
        reasons = ["candidate test suite produced zero passing tests while baseline passed"]
    elif score >= 0.95:
        verdict, confidence = "SAFE", 0.85
        reasons = [f"compatibility score {score:.2f} >= 0.95 with no environment failures"]
    elif score >= 0.80:
        verdict, confidence = "SAFE_WITH_REVIEW", 0.75
        reasons = [f"compatibility score {score:.2f} >= 0.80; minor degradation measured"]
    elif score >= 0.60:
        verdict, confidence = "MODERATE_RISK", 0.7
        reasons = [f"compatibility score {score:.2f} >= 0.60; measurable regression detected"]
    else:
        verdict, confidence = "HIGH_RISK", 0.8
        reasons = [f"compatibility score {score:.2f} < 0.60; significant regression detected"]

    return {
        "verdict": verdict,
        "confidence": confidence,
        "reasons": reasons,
        "recommendation": _recommendation_for(verdict),
    }


def _recommendation_for(verdict: str) -> str:
    return {
        "SAFE": "Proceed with the upgrade; monitored checks passed.",
        "SAFE_WITH_REVIEW": "Upgrade is viable; review the flagged metrics before merging.",
        "MODERATE_RISK": "Investigate the regressed metrics before upgrading.",
        "HIGH_RISK": "Do not upgrade without fixing the measured regressions.",
        "INCOMPATIBLE": "Block the upgrade; the candidate environment failed.",
    }[verdict]


def reason_about_update(
    db: Database,
    investigation_id: str,
    comparison: dict,
    research: dict,
    dependency_name: str,
    from_version: str,
    to_version: str,
) -> dict:
    """One LLM call when a key exists; deterministic rule-based fallback otherwise."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log_event(
            db, investigation_id, "REASON",
            "ANTHROPIC_API_KEY not set; using deterministic rule-based verdict",
            level="warn",
        )
        return _rule_based_verdict(comparison)

    user_payload = {
        "dependency": dependency_name,
        "from_version": from_version,
        "to_version": to_version,
        "comparison": comparison,
        "web_evidence": (research or {}).get("evidence_text", "")[:6000],
        "web_evidence_source": (research or {}).get("source", "none"),
    }

    log_event(db, investigation_id, "REASON", f"calling {ANTHROPIC_MODEL} with measured evidence")
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=MAX_TOKENS,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(user_payload)}],
        )
        text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
    except Exception as exc:  # noqa: BLE001 — fall back rather than crash
        log_event(db, investigation_id, "REASON", f"LLM call failed ({exc}); using rule-based verdict", level="warn")
        return _rule_based_verdict(comparison)

    try:
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = stripped.strip("`")
            if stripped.startswith("json"):
                stripped = stripped[4:]
        data = json.loads(stripped)
    except json.JSONDecodeError:
        log_event(db, investigation_id, "REASON", "LLM output was not valid JSON; using rule-based verdict", level="warn")
        return _rule_based_verdict(comparison)

    verdict = data.get("verdict")
    if verdict not in VALID_VERDICTS:
        log_event(db, investigation_id, "REASON", f"LLM returned unknown verdict {verdict!r}; using rule-based", level="warn")
        return _rule_based_verdict(comparison)

    reasons = data.get("reasons") or []
    if not isinstance(reasons, list):
        reasons = [str(reasons)]
    result = {
        "verdict": verdict,
        "confidence": float(data.get("confidence") or 0.5),
        "reasons": [str(r) for r in reasons][:8],
        "recommendation": str(data.get("recommendation") or _recommendation_for(verdict)),
    }
    log_event(db, investigation_id, "REASON", f"LLM verdict {result['verdict']} (confidence {result['confidence']:.2f})")
    return result
