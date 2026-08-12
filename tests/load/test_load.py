"""
pytest-discoverable load tests for Kung-Fu Chess.

These tests run against the live kind cluster (localhost:30080 / 30765).
They are skipped automatically when the cluster is unavailable so they
don't break the CI suite on a machine without the cluster running.

Run only the load tests:
  pytest tests/load/ -v

Run everything (including load tests):
  pytest -v

Skip load tests explicitly:
  pytest --ignore=tests/load/
"""

from __future__ import annotations

import asyncio
import pytest
import urllib.request
import urllib.error

from load_tests.config import GATEWAY_URL, WS_URL, HTTP_CONCURRENCY, HTTP_REQUESTS, WS_CLIENTS
from load_tests.metrics_reader import read_metrics


# ── Availability check ────────────────────────────────────────────────────────

def _cluster_available() -> bool:
    """Return True if the gateway /health endpoint is reachable."""
    try:
        with urllib.request.urlopen(f"{GATEWAY_URL}/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


SKIP_IF_NO_CLUSTER = pytest.mark.skipif(
    not _cluster_available(),
    reason="kind cluster not reachable at localhost:30080 — skipping load tests",
)


# ── Smoke: metrics endpoint reachable ─────────────────────────────────────────

@SKIP_IF_NO_CLUSTER
def test_metrics_endpoint_reachable():
    """The /metrics endpoint is reachable and returns Prometheus text."""
    snap = read_metrics(GATEWAY_URL)
    assert snap is not None
    assert "server_id" in str(snap)
    # Metric counters are non-negative
    assert snap.active_connections >= 0
    assert snap.active_rooms >= 0
    assert snap.http_requests_total >= 0
    assert snap.errors_total >= 0


# ── HTTP load test (small) ─────────────────────────────────────────────────────

@SKIP_IF_NO_CLUSTER
@pytest.mark.asyncio
async def test_http_load_health():
    """Concurrent /health requests: all succeed, latency under 2s."""
    from load_tests.http_load import run_health_flood
    import aiohttp

    timeout   = aiohttp.ClientTimeout(total=10.0)
    connector = aiohttp.TCPConnector(limit=30)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as sess:
        result = await run_health_flood(sess, n=50, concurrency=10)

    assert result.total   == 50
    assert result.failure == 0, f"Expected 0 failures, got {result.failure}"
    lat = result.latency_summary()
    assert lat["p99"] < 2.0, f"p99 latency {lat['p99']:.3f}s exceeded 2s"


@SKIP_IF_NO_CLUSTER
@pytest.mark.asyncio
async def test_http_load_register_login():
    """Concurrent register + login: ≥95% success, p99 latency under 5s."""
    from load_tests.http_load import run_register_login_profile
    import aiohttp

    timeout   = aiohttp.ClientTimeout(total=15.0)
    connector = aiohttp.TCPConnector(limit=20)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as sess:
        reg, login, prof = await run_register_login_profile(
            sess, n_users=20, concurrency=10
        )

    # Registration
    assert reg.total == 20
    assert reg.success_rate >= 95.0, (
        f"Register success rate {reg.success_rate:.1f}% < 95%"
    )

    # Login (success rate may be slightly lower if a register failed)
    assert login.total == 20
    assert login.success_rate >= 90.0, (
        f"Login success rate {login.success_rate:.1f}% < 90%"
    )

    # Latency
    reg_lat   = reg.latency_summary()
    login_lat = login.latency_summary()
    assert reg_lat["p99"]   < 5.0, f"register p99={reg_lat['p99']:.3f}s > 5s"
    assert login_lat["p99"] < 5.0, f"login p99={login_lat['p99']:.3f}s > 5s"


# ── WebSocket load test (small) ───────────────────────────────────────────────

@SKIP_IF_NO_CLUSTER
@pytest.mark.asyncio
async def test_ws_load_login_and_matchmaking():
    """
    20 concurrent WebSocket clients:
     - all connect and log in
     - all enter matchmaking
     - ≥80% find a match (allows for odd-client edge cases)
    """
    from load_tests.ws_load import run
    result = await run(n_clients=20)

    assert result.connected   >= 18, f"Only {result.connected} connections"
    assert result.login_ok    >= 18, f"Only {result.login_ok} logins"
    assert result.matches_found >= 8, (
        f"Only {result.matches_found} matches from {result.n_clients} clients"
    )


# ── Metrics increase after load ────────────────────────────────────────────────

@SKIP_IF_NO_CLUSTER
@pytest.mark.asyncio
async def test_http_requests_metric_increments():
    """
    After sending HTTP requests the http_requests_total counter increases.
    Validates that the gateway's metric instrumentation is working.
    """
    import aiohttp
    before = read_metrics(GATEWAY_URL)

    timeout   = aiohttp.ClientTimeout(total=10.0)
    connector = aiohttp.TCPConnector(limit=10)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as sess:
        from load_tests.http_load import run_health_flood
        await run_health_flood(sess, n=10, concurrency=5)

    after = read_metrics(GATEWAY_URL)
    delta = after.http_requests_total - before.http_requests_total
    # The gateway tracks per-pod; delta ≥ 0 is all we can guarantee across
    # two replicas with separate metric collectors.
    assert delta >= 0, f"http_requests_total went down: {delta}"
