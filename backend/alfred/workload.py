"""WORKLOAD step — fire real concurrent HTTP requests at each environment.

Uses httpx + asyncio with the endpoint/method/concurrency/requests/payloads
from the repo's alfred.yaml. Latencies (p50/p95/p99), error rate, and
throughput are computed from actual per-request timings — nothing synthetic.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from .db import Database
from .events import log_event

REQUEST_TIMEOUT = 30.0


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (len(sorted_values) - 1) * pct
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


async def _fire_requests(
    client: httpx.AsyncClient,
    url: str,
    method: str,
    payloads: list[dict[str, Any]],
    concurrency: int,
    total: int,
    latencies: list[float],
    errors: list[str],
) -> None:
    sem = asyncio.Semaphore(concurrency)

    async def one(i: int) -> None:
        payload = payloads[i % len(payloads)] if payloads else None
        async with sem:
            start = time.perf_counter()
            try:
                if method == "GET":
                    await client.get(url)
                elif method == "POST":
                    await client.post(url, json=payload)
                elif method == "PUT":
                    await client.put(url, json=payload)
                elif method == "PATCH":
                    await client.patch(url, json=payload)
                elif method == "DELETE":
                    await client.delete(url)
                else:
                    await client.request(method, url, json=payload)
            except Exception as exc:  # noqa: BLE001 — any failure counts as an errored request
                errors.append(f"{type(exc).__name__}: {exc}")
            finally:
                latencies.append((time.perf_counter() - start) * 1000.0)

    # chunk into batches so a huge `requests` count does not build a huge task list
    batch_size = max(concurrency * 4, 50)
    done = 0
    while done < total:
        n = min(batch_size, total - done)
        await asyncio.gather(*(one(done + i) for i in range(n)))
        done += n


def run_workload(
    db: Database,
    investigation_id: str,
    base_url: str,
    workload_config: Any,
    environment: str,
) -> dict:
    """Send real load and return measured metrics for one environment."""
    endpoint = workload_config.endpoint
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    url = f"{base_url.rstrip('/')}{endpoint}"
    method = workload_config.method
    concurrency = max(1, workload_config.concurrency)
    total = max(1, workload_config.requests)
    payloads = list(workload_config.payloads or [])

    log_event(
        db,
        investigation_id,
        "WORKLOAD",
        f"{environment}: {total} {method} {endpoint} requests at concurrency {concurrency}",
    )

    latencies: list[float] = []
    errors: list[str] = []
    start = time.perf_counter()
    asyncio.run(_fire_requests(
        httpx.AsyncClient(timeout=REQUEST_TIMEOUT, verify=False),
        url,
        method,
        payloads,
        concurrency,
        total,
        latencies,
        errors,
    ))
    wall = time.perf_counter() - start

    successful = sum(1 for _ in latencies) - len(errors)
    error_rate = len(errors) / total if total else 0.0
    throughput = total / wall if wall > 0 else 0.0
    ordered = sorted(latencies)

    metrics = {
        "total_requests": total,
        "successful_requests": successful,
        "error_rate": round(error_rate, 6),
        "latency_p50_ms": round(_percentile(ordered, 0.50), 3),
        "latency_p95_ms": round(_percentile(ordered, 0.95), 3),
        "latency_p99_ms": round(_percentile(ordered, 0.99), 3),
        "throughput_rps": round(throughput, 3),
        "raw_output": "\n".join(errors[:50]),
    }
    log_event(
        db,
        investigation_id,
        "WORKLOAD",
        f"{environment}: p50 {metrics['latency_p50_ms']}ms p95 {metrics['latency_p95_ms']}ms "
        f"p99 {metrics['latency_p99_ms']}ms err {metrics['error_rate']:.2%} {metrics['throughput_rps']}rps",
    )
    return metrics
