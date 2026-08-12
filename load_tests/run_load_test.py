"""
Full load-test orchestrator.

Runs in order:
  1. Capture /metrics baseline (before)
  2. HTTP gateway load test
  3. WebSocket load test
  4. Capture /metrics after load
  5. Print diff and full report

Usage:
  python load_tests/run_load_test.py
  python load_tests/run_load_test.py --http-requests 400 --ws-clients 30
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

from load_tests.config import (
    GATEWAY_URL,
    WS_URL,
    HTTP_CONCURRENCY,
    HTTP_REQUESTS,
    WS_CLIENTS,
)
from load_tests.metrics_reader import read_metrics
from load_tests import http_load, ws_load


def _print_metrics_diff(before, after, label: str) -> None:
    print(f"\n[Metrics] {label}")
    print(f"  {'Metric':<35} {'Before':>8}  {'After':>8}  {'Delta':>8}")
    print("  " + "-" * 60)
    fields = [
        ("active_connections",    "active_connections"),
        ("active_rooms",          "active_rooms"),
        ("matchmaking_queue_size","matchmaking_queue_size"),
        ("http_requests_total",   "http_requests_total"),
        ("errors_total",          "errors_total"),
    ]
    for label_str, attr in fields:
        bv = getattr(before, attr, 0)
        av = getattr(after, attr, 0)
        d  = av - bv
        sign = "+" if d >= 0 else ""
        print(f"  {label_str:<35} {bv:>8.0f}  {av:>8.0f}  {sign}{d:>7.0f}")
    print(f"  server_id (gateway): {after.server_id}")


async def run_all(
    http_concurrency: int,
    http_requests:    int,
    ws_clients:       int,
) -> dict:
    print("=" * 82)
    print("  Kung-Fu Chess — Load Test Report")
    print(f"  Gateway : {GATEWAY_URL}")
    print(f"  WS      : {WS_URL}")
    print("=" * 82)

    # ── Baseline metrics ──────────────────────────────────────────────────────
    try:
        before = read_metrics(GATEWAY_URL)
        print(f"\n[Metrics] Before load: {before}")
    except Exception as e:
        print(f"[Metrics] WARNING: could not read metrics before test: {e}")
        from load_tests.metrics_reader import MetricsSnapshot
        before = MetricsSnapshot()

    # ── HTTP load test ────────────────────────────────────────────────────────
    http_results = await http_load.run(http_concurrency, http_requests)

    # ── Metrics after HTTP ────────────────────────────────────────────────────
    try:
        after_http = read_metrics(GATEWAY_URL)
        _print_metrics_diff(before, after_http, "After HTTP load")
    except Exception as e:
        print(f"[Metrics] WARNING: {e}")
        after_http = before

    # ── WebSocket load test ───────────────────────────────────────────────────
    ws_results = await ws_load.run(ws_clients)

    # ── Final metrics ─────────────────────────────────────────────────────────
    try:
        after_ws = read_metrics(GATEWAY_URL)
        _print_metrics_diff(after_http, after_ws, "After WS load")
    except Exception as e:
        print(f"[Metrics] WARNING: {e}")
        after_ws = after_http

    # ── Summary ───────────────────────────────────────────────────────────────
    total_http_req  = http_results.get("total_requests", 0)
    total_http_ok   = http_results.get("total_success",  0)
    total_http_fail = http_results.get("total_failure",  0)
    total_http_rate = total_http_ok / total_http_req * 100 if total_http_req else 0

    print("\n" + "=" * 82)
    print("  SUMMARY")
    print("=" * 82)
    print(f"  HTTP requests    : {total_http_req}  "
          f"success={total_http_ok}  fail={total_http_fail}  "
          f"rate={total_http_rate:.1f}%")
    print(f"  WS clients       : {ws_results.n_clients}  "
          f"connected={ws_results.connected}  "
          f"login_ok={ws_results.login_ok}  "
          f"matches={ws_results.matches_found}  "
          f"moves_accepted={ws_results.moves_accepted}")
    print(f"  Errors (WS)      : {len(ws_results.errors)}")
    print(f"  Metrics observed :")
    print(f"    connections (peak observed via /metrics) : {after_ws.active_connections:.0f}")
    print(f"    rooms (after WS test)                   : {after_ws.active_rooms:.0f}")
    print(f"    http_requests_total (after HTTP test)   : {after_http.http_requests_total:.0f}")
    print(f"    errors_total                            : {after_ws.errors_total:.0f}")
    print("=" * 82)

    return {
        "http": http_results,
        "ws":   ws_results.to_dict(),
        "metrics_before": before,
        "metrics_after_http": after_http,
        "metrics_after_ws":   after_ws,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Full load test orchestrator")
    parser.add_argument("--http-concurrency", type=int, default=HTTP_CONCURRENCY)
    parser.add_argument("--http-requests",    type=int, default=HTTP_REQUESTS)
    parser.add_argument("--ws-clients",       type=int, default=WS_CLIENTS)
    args = parser.parse_args()

    asyncio.run(run_all(args.http_concurrency, args.http_requests, args.ws_clients))


if __name__ == "__main__":
    main()
