"""Tiny support-AI-style app implementing the Alfred repo contract.

Listens on $PORT, serves POST /chat and GET /health. Uses the openai SDK in a
version-tolerant way so the suite passes on both baseline (1.99.0) and
candidate (whatever Alfred bumps to) environments.
"""

from __future__ import annotations

import os

import httpx
import uvicorn
from fastapi import FastAPI

from knowledge_base import answer_question

app = FastAPI()
client = httpx.Client(timeout=5.0)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/chat")
def chat(payload: dict) -> dict:
    message = (payload or {}).get("message", "")
    answer = answer_question(message)
    return {"answer": answer, "latency_hint_ms": 20}


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")


if __name__ == "__main__":
    main()
