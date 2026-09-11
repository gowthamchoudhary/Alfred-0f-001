"""Version-tolerant helper used by the sample app and its tests."""

from __future__ import annotations

try:
    import openai
except Exception:  # pragma: no cover — the app runs without the SDK present
    openai = None  # type: ignore[assignment]

_KB = {
    "refund": "Refunds are available within 30 days of purchase.",
    "hours": "Support is available 9am-5pm ET, Monday to Friday.",
    "shipping": "Standard shipping takes 3-5 business days.",
}


def answer_question(message: str) -> str:
    """Deterministic knowledge-base lookup; exercises the openai import path."""
    low = (message or "").lower()
    for key, answer in _KB.items():
        if key in low:
            return answer
    return (
        "I don't have that answer yet. "
        f"(openai SDK present: {openai.__version__ if openai else 'no'})"
    )
