"""
HTTP gateway load test.

Sends concurrent requests to:
  GET  /health          — pure liveness
  POST /auth/register   — DB write (creates unique users)
  POST /auth/login      — DB read  (verifies credentials)
  GET  /users/{u}       — DB read  (profile lookup)
  GET  /metrics         — Prometheus scrape

Records per-endpoint:
  • total requests sent
  • success count (2xx)
  • failure count (non-2xx or exception)
  • latencies: min / p50 / p90 / p99 / max  (seconds)

Usage:
  python load_tests/http_load.py
  python load_tests/http_load.py --concurrency 30 --requests 300
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import List

import aiohttp

from load_tests.config import (
    GATEWAY_URL,
    HTTP_CONCURRENCY,
    HTTP_REQUESTS,
    HTTP_TIMEOUT_S,
    USER_PREFIX,
)


# ── Result container ──────────────────────────────────────────────────────────

@dataclass
class EndpointResult:
    name: str
    total: int = 0
    success: int = 0
    failure: int = 0
    latencies: List[float] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        return (self.success / self.total * 100) if self.total else 0.0

    def latency_summary(self) -> dict:
        if not self.latencies:
            return {}
        s = sorted(self.latencies)
        n = len(s)
        def pct(p): return s[min(int(n * p / 100), n - 1)]
        return {
            "min":  round(s[0],    3),
            "p50":  round(pct(50), 3),
            "p90":  round(pct(90), 3),
            "p99":  round(pct(99), 3),
            "max":  round(s[-1],   3),
            "mean": round(statistics.mean(s), 3),
        }

    def print_summary(self) -> None:
        lat = self.latency_summary()
        print(
            f"  {self.name:<28}  "
            f"total={self.total:>4}  "
            f"ok={self.success:>4}  "
            f"fail={self.failure:>3}  "
            f"({self.success_rate:5.1f}%)  "
            f"lat(s): min={lat.get('min','?'):.3f} "
            f"p50={lat.get('p50','?'):.3f} "
            f"p90={lat.get('p90','?'):.3f} "
            f"p99={lat.get('p99','?'):.3f} "
            f"max={lat.get('max','?'):.3f}"
        )


# ── Individual request helpers ────────────────────────────────────────────────

async def _get(session: aiohttp.ClientSession, url: str, result: EndpointResult) -> None:
    t0 = time.monotonic()
    try:
        async with session.get(url) as r:
            await r.read()
            elapsed = time.monotonic() - t0
            result.total += 1
            result.latencies.append(elapsed)
            if r.status < 300:
                result.success += 1
            else:
                result.failure += 1
    except Exception:
        elapsed = time.monotonic() - t0
        result.total += 1
        result.failure += 1
        result.latencies.append(elapsed)


async def _post(session: aiohttp.ClientSession, url: str,
                payload: dict, result: EndpointResult) -> None:
    t0 = time.monotonic()
    try:
        async with session.post(url, json=payload) as r:
            await r.read()
            elapsed = time.monotonic() - t0
            result.total += 1
            result.latencies.append(elapsed)
            if r.status < 300:
                result.success += 1
            else:
                result.failure += 1
    except Exception:
        elapsed = time.monotonic() - t0
        result.total += 1
        result.failure += 1
        result.latencies.append(elapsed)


# ── Test phases ───────────────────────────────────────────────────────────────

async def run_health_flood(
    session: aiohttp.ClientSession,
    n: int,
    concurrency: int,
) -> EndpointResult:
    """Flood /health with n requests at given concurrency."""
    result = EndpointResult("GET /health")
    url = f"{GATEWAY_URL}/health"
    sem = asyncio.Semaphore(concurrency)

    async def one():
        async with sem:
            await _get(session, url, result)

    await asyncio.gather(*[one() for _ in range(n)])
    return result


async def run_metrics_flood(
    session: aiohttp.ClientSession,
    n: int,
    concurrency: int,
) -> EndpointResult:
    """Flood /metrics with n requests."""
    result = EndpointResult("GET /metrics")
    url = f"{GATEWAY_URL}/metrics"
    sem = asyncio.Semaphore(concurrency)

    async def one():
        async with sem:
            await _get(session, url, result)

    await asyncio.gather(*[one() for _ in range(n)])
    return result


async def run_register_login_profile(
    session: aiohttp.ClientSession,
    n_users: int,
    concurrency: int,
) -> tuple[EndpointResult, EndpointResult, EndpointResult]:
    """
    Register n_users unique users, then login each, then fetch their profile.
    All three phases run with the given concurrency.
    """
    reg_result   = EndpointResult("POST /auth/register")
    login_result = EndpointResult("POST /auth/login")
    prof_result  = EndpointResult("GET  /users/{u}")

    reg_url   = f"{GATEWAY_URL}/auth/register"
    login_url = f"{GATEWAY_URL}/auth/login"
    sem       = asyncio.Semaphore(concurrency)

    users = [
        {"username": f"{USER_PREFIX}u{i}", "password": f"pw{i}x"}
        for i in range(n_users)
    ]

    # Phase 1: register
    async def do_register(u):
        async with sem:
            await _post(session, reg_url, u, reg_result)

    await asyncio.gather(*[do_register(u) for u in users])

    # Phase 2: login (only for successfully registered users)
    async def do_login(u):
        async with sem:
            await _post(session, login_url, u, login_result)

    await asyncio.gather(*[do_login(u) for u in users])

    # Phase 3: profile
    async def do_profile(u):
        async with sem:
            await _get(session, f"{GATEWAY_URL}/users/{u['username']}", prof_result)

    await asyncio.gather(*[do_profile(u) for u in users])

    return reg_result, login_result, prof_result


# ── Main entry ────────────────────────────────────────────────────────────────

async def run(
    concurrency: int = HTTP_CONCURRENCY,
    n_requests: int  = HTTP_REQUESTS,
) -> dict:
    """Run all HTTP load tests and return results dict."""
    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S)
    connector = aiohttp.TCPConnector(limit=concurrency + 10)

    async with aiohttp.ClientSession(
        connector=connector, timeout=timeout
    ) as session:
        print(f"\n[HTTP] concurrency={concurrency}  requests/endpoint={n_requests}")
        print(f"       target={GATEWAY_URL}")

        t_start = time.monotonic()

        health  = await run_health_flood(session, n_requests, concurrency)
        metrics = await run_metrics_flood(session, n_requests // 4, concurrency)
        reg, login, prof = await run_register_login_profile(
            session, n_requests // 2, concurrency
        )

        elapsed = time.monotonic() - t_start

    results = {
        "health": health,
        "metrics": metrics,
        "register": reg,
        "login": login,
        "profile": prof,
        "total_elapsed_s": round(elapsed, 2),
        "concurrency": concurrency,
    }

    # Aggregate
    total_req = sum(r.total   for r in [health, metrics, reg, login, prof])
    total_ok  = sum(r.success for r in [health, metrics, reg, login, prof])
    total_fail= sum(r.failure for r in [health, metrics, reg, login, prof])

    print(f"\n[HTTP] Results  (elapsed={elapsed:.2f}s  total_rps={total_req/elapsed:.1f})")
    print("-" * 82)
    for r in [health, metrics, reg, login, prof]:
        r.print_summary()
    print("-" * 82)
    print(
        f"  TOTAL  requests={total_req}  success={total_ok}  "
        f"failure={total_fail}  success_rate={total_ok/total_req*100:.1f}%"
    )
    results["total_requests"] = total_req
    results["total_success"]  = total_ok
    results["total_failure"]  = total_fail

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="HTTP gateway load test")
    parser.add_argument("--concurrency", type=int, default=HTTP_CONCURRENCY)
    parser.add_argument("--requests",    type=int, default=HTTP_REQUESTS)
    parser.add_argument("--url",         type=str, default=GATEWAY_URL)
    args = parser.parse_args()

    import load_tests.config as cfg
    cfg.GATEWAY_URL = args.url

    asyncio.run(run(args.concurrency, args.requests))


if __name__ == "__main__":
    main()
