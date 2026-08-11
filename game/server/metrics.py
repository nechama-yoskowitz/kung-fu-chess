"""
Lightweight metrics collection for production observability.

Tracks:
- Active WebSocket connections
- Active rooms/games
- Matchmaking queue size
- HTTP requests (when used with gateway)
- Errors
- Basic latency

Thread-safe counters and gauges that can be exposed via /metrics endpoint.
"""

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict


@dataclass
class MetricsSnapshot:
    """Immutable snapshot of current metrics."""
    active_connections: int = 0
    active_rooms: int = 0
    matchmaking_queue_size: int = 0
    total_http_requests: int = 0
    total_errors: int = 0
    http_requests_by_endpoint: Dict[str, int] = field(default_factory=dict)
    errors_by_type: Dict[str, int] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class MetricsCollector:
    """
    Thread-safe metrics collector.
    
    Tracks counters and gauges that can be incremented/decremented
    from multiple threads or async contexts.
    """
    
    def __init__(self):
        self._lock = threading.Lock()
        
        # Gauges (current values)
        self._active_connections = 0
        self._active_rooms = 0
        self._matchmaking_queue_size = 0
        
        # Counters (cumulative)
        self._total_http_requests = 0
        self._total_errors = 0
        self._http_requests_by_endpoint: Dict[str, int] = defaultdict(int)
        self._errors_by_type: Dict[str, int] = defaultdict(int)
    
    # ── Connection metrics ────────────────────────────────────────────────────
    
    def connection_opened(self) -> None:
        """Increment active WebSocket connection count."""
        with self._lock:
            self._active_connections += 1
    
    def connection_closed(self) -> None:
        """Decrement active WebSocket connection count."""
        with self._lock:
            self._active_connections = max(0, self._active_connections - 1)
    
    def get_active_connections(self) -> int:
        """Get current number of active WebSocket connections."""
        with self._lock:
            return self._active_connections
    
    # ── Room metrics ──────────────────────────────────────────────────────────
    
    def room_created(self) -> None:
        """Increment active room count."""
        with self._lock:
            self._active_rooms += 1
    
    def room_closed(self) -> None:
        """Decrement active room count."""
        with self._lock:
            self._active_rooms = max(0, self._active_rooms - 1)
    
    def get_active_rooms(self) -> int:
        """Get current number of active rooms."""
        with self._lock:
            return self._active_rooms
    
    # ── Matchmaking metrics ───────────────────────────────────────────────────
    
    def set_matchmaking_queue_size(self, size: int) -> None:
        """Set the current matchmaking queue size."""
        with self._lock:
            self._matchmaking_queue_size = max(0, size)
    
    def get_matchmaking_queue_size(self) -> int:
        """Get current matchmaking queue size."""
        with self._lock:
            return self._matchmaking_queue_size
    
    # ── HTTP metrics ──────────────────────────────────────────────────────────
    
    def http_request(self, endpoint: str) -> None:
        """Record an HTTP request to a specific endpoint."""
        with self._lock:
            self._total_http_requests += 1
            self._http_requests_by_endpoint[endpoint] += 1
    
    def get_total_http_requests(self) -> int:
        """Get total number of HTTP requests."""
        with self._lock:
            return self._total_http_requests
    
    def get_http_requests_by_endpoint(self) -> Dict[str, int]:
        """Get HTTP request counts by endpoint."""
        with self._lock:
            return dict(self._http_requests_by_endpoint)
    
    # ── Error metrics ─────────────────────────────────────────────────────────
    
    def error_occurred(self, error_type: str = "unknown") -> None:
        """Record an error occurrence."""
        with self._lock:
            self._total_errors += 1
            self._errors_by_type[error_type] += 1
    
    def get_total_errors(self) -> int:
        """Get total number of errors."""
        with self._lock:
            return self._total_errors
    
    def get_errors_by_type(self) -> Dict[str, int]:
        """Get error counts by type."""
        with self._lock:
            return dict(self._errors_by_type)
    
    # ── Snapshot ──────────────────────────────────────────────────────────────
    
    def snapshot(self) -> MetricsSnapshot:
        """Return an immutable snapshot of current metrics."""
        with self._lock:
            return MetricsSnapshot(
                active_connections=self._active_connections,
                active_rooms=self._active_rooms,
                matchmaking_queue_size=self._matchmaking_queue_size,
                total_http_requests=self._total_http_requests,
                total_errors=self._total_errors,
                http_requests_by_endpoint=dict(self._http_requests_by_endpoint),
                errors_by_type=dict(self._errors_by_type),
                timestamp=time.time(),
            )
    
    def reset(self) -> None:
        """Reset all metrics (for testing)."""
        with self._lock:
            self._active_connections = 0
            self._active_rooms = 0
            self._matchmaking_queue_size = 0
            self._total_http_requests = 0
            self._total_errors = 0
            self._http_requests_by_endpoint.clear()
            self._errors_by_type.clear()


# Global metrics collector instance
_metrics_collector: MetricsCollector | None = None


def get_metrics_collector() -> MetricsCollector:
    """Get the global metrics collector instance."""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector


def reset_metrics_collector() -> None:
    """Reset the global metrics collector (for testing)."""
    global _metrics_collector
    _metrics_collector = None


def format_prometheus(snapshot: MetricsSnapshot, server_id: str = "unknown") -> str:
    """
    Format metrics snapshot as Prometheus text format.
    
    Example output:
        # HELP kfc_active_connections Number of active WebSocket connections
        # TYPE kfc_active_connections gauge
        kfc_active_connections{server_id="server-1"} 42
    """
    lines = []
    
    # Active connections
    lines.append("# HELP kfc_active_connections Number of active WebSocket connections")
    lines.append("# TYPE kfc_active_connections gauge")
    lines.append(f'kfc_active_connections{{server_id="{server_id}"}} {snapshot.active_connections}')
    lines.append("")
    
    # Active rooms
    lines.append("# HELP kfc_active_rooms Number of active game rooms")
    lines.append("# TYPE kfc_active_rooms gauge")
    lines.append(f'kfc_active_rooms{{server_id="{server_id}"}} {snapshot.active_rooms}')
    lines.append("")
    
    # Matchmaking queue
    lines.append("# HELP kfc_matchmaking_queue_size Current matchmaking queue size")
    lines.append("# TYPE kfc_matchmaking_queue_size gauge")
    lines.append(f'kfc_matchmaking_queue_size{{server_id="{server_id}"}} {snapshot.matchmaking_queue_size}')
    lines.append("")
    
    # Total HTTP requests
    lines.append("# HELP kfc_http_requests_total Total number of HTTP requests")
    lines.append("# TYPE kfc_http_requests_total counter")
    lines.append(f'kfc_http_requests_total{{server_id="{server_id}"}} {snapshot.total_http_requests}')
    lines.append("")
    
    # HTTP requests by endpoint
    if snapshot.http_requests_by_endpoint:
        lines.append("# HELP kfc_http_requests_by_endpoint HTTP requests by endpoint")
        lines.append("# TYPE kfc_http_requests_by_endpoint counter")
        for endpoint, count in sorted(snapshot.http_requests_by_endpoint.items()):
            lines.append(f'kfc_http_requests_by_endpoint{{server_id="{server_id}",endpoint="{endpoint}"}} {count}')
        lines.append("")
    
    # Total errors
    lines.append("# HELP kfc_errors_total Total number of errors")
    lines.append("# TYPE kfc_errors_total counter")
    lines.append(f'kfc_errors_total{{server_id="{server_id}"}} {snapshot.total_errors}')
    lines.append("")
    
    # Errors by type
    if snapshot.errors_by_type:
        lines.append("# HELP kfc_errors_by_type Errors by type")
        lines.append("# TYPE kfc_errors_by_type counter")
        for error_type, count in sorted(snapshot.errors_by_type.items()):
            lines.append(f'kfc_errors_by_type{{server_id="{server_id}",error_type="{error_type}"}} {count}')
        lines.append("")
    
    return "\n".join(lines)
