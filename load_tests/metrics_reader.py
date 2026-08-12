"""
Read and parse the /metrics Prometheus endpoint.

Returns a dict of metric_name -> float (the first value found for each
metric name, regardless of labels).  For labelled series the raw label
string is also preserved.
"""

from __future__ import annotations

import re
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Dict


@dataclass
class MetricsSnapshot:
    """Parsed values from the /metrics Prometheus endpoint."""
    active_connections: float = 0.0
    active_rooms: float = 0.0
    matchmaking_queue_size: float = 0.0
    http_requests_total: float = 0.0
    errors_total: float = 0.0
    raw: Dict[str, float] = field(default_factory=dict)
    server_id: str = "unknown"

    def __str__(self) -> str:
        return (
            f"MetricsSnapshot("
            f"connections={self.active_connections:.0f}, "
            f"rooms={self.active_rooms:.0f}, "
            f"queue={self.matchmaking_queue_size:.0f}, "
            f"http_req={self.http_requests_total:.0f}, "
            f"errors={self.errors_total:.0f}, "
            f"server_id={self.server_id!r})"
        )


def read_metrics(gateway_url: str = "http://localhost:30080") -> MetricsSnapshot:
    """
    Fetch and parse the /metrics endpoint.

    Raises urllib.error.URLError if the endpoint is unreachable.
    """
    url = f"{gateway_url}/metrics"
    with urllib.request.urlopen(url, timeout=5) as resp:
        body = resp.read().decode()

    snap = MetricsSnapshot()
    raw: Dict[str, float] = {}

    for line in body.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        # Extract metric name (with optional labels) and value
        m = re.match(r'^(\w+)(\{[^}]*\})?\s+([\d.e+\-]+)', line)
        if not m:
            continue
        name, labels, value_str = m.group(1), m.group(2) or "", m.group(3)
        try:
            value = float(value_str)
        except ValueError:
            continue

        raw[f"{name}{labels}"] = value
        # Also store the bare name (first occurrence wins)
        if name not in raw:
            raw[name] = value

        # Extract server_id from labels
        if labels:
            sid_m = re.search(r'server_id="([^"]+)"', labels)
            if sid_m:
                snap.server_id = sid_m.group(1)

    snap.raw = raw
    snap.active_connections    = raw.get("kfc_active_connections", 0.0)
    snap.active_rooms          = raw.get("kfc_active_rooms", 0.0)
    snap.matchmaking_queue_size = raw.get("kfc_matchmaking_queue_size", 0.0)
    snap.http_requests_total   = raw.get("kfc_http_requests_total", 0.0)
    snap.errors_total          = raw.get("kfc_errors_total", 0.0)
    return snap
