"""
Tests for Stage 7: structured metrics collection and /metrics endpoint.

Covers:
- MetricsCollector: counters, gauges, snapshot, thread-safety
- format_prometheus: output format correctness
- RoomManager: room_created / room_closed integration
- GET /metrics gateway endpoint
"""

import pytest
import pytest_asyncio

from game.server.metrics import (
    MetricsCollector,
    MetricsSnapshot,
    format_prometheus,
    get_metrics_collector,
    reset_metrics_collector,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_global_collector():
    """Ensure the global singleton is clean for every test."""
    reset_metrics_collector()
    yield
    reset_metrics_collector()


@pytest.fixture
def collector():
    return MetricsCollector()


# ── MetricsCollector: connection gauges ───────────────────────────────────────


class TestConnectionMetrics:
    def test_initial_connections_is_zero(self, collector):
        assert collector.get_active_connections() == 0

    def test_connection_opened_increments(self, collector):
        collector.connection_opened()
        assert collector.get_active_connections() == 1

    def test_connection_closed_decrements(self, collector):
        collector.connection_opened()
        collector.connection_opened()
        collector.connection_closed()
        assert collector.get_active_connections() == 1

    def test_connection_closed_does_not_go_below_zero(self, collector):
        collector.connection_closed()
        assert collector.get_active_connections() == 0

    def test_multiple_opens_and_closes(self, collector):
        for _ in range(5):
            collector.connection_opened()
        for _ in range(3):
            collector.connection_closed()
        assert collector.get_active_connections() == 2


# ── MetricsCollector: room gauges ─────────────────────────────────────────────


class TestRoomMetrics:
    def test_initial_rooms_is_zero(self, collector):
        assert collector.get_active_rooms() == 0

    def test_room_created_increments(self, collector):
        collector.room_created()
        assert collector.get_active_rooms() == 1

    def test_room_closed_decrements(self, collector):
        collector.room_created()
        collector.room_created()
        collector.room_closed()
        assert collector.get_active_rooms() == 1

    def test_room_closed_does_not_go_below_zero(self, collector):
        collector.room_closed()
        assert collector.get_active_rooms() == 0


# ── MetricsCollector: matchmaking gauge ───────────────────────────────────────


class TestMatchmakingMetrics:
    def test_initial_queue_size_is_zero(self, collector):
        assert collector.get_matchmaking_queue_size() == 0

    def test_set_queue_size(self, collector):
        collector.set_matchmaking_queue_size(7)
        assert collector.get_matchmaking_queue_size() == 7

    def test_set_queue_size_to_zero(self, collector):
        collector.set_matchmaking_queue_size(5)
        collector.set_matchmaking_queue_size(0)
        assert collector.get_matchmaking_queue_size() == 0

    def test_set_queue_size_negative_clamped(self, collector):
        collector.set_matchmaking_queue_size(-3)
        assert collector.get_matchmaking_queue_size() == 0


# ── MetricsCollector: HTTP request counters ───────────────────────────────────


class TestHttpMetrics:
    def test_initial_http_requests_is_zero(self, collector):
        assert collector.get_total_http_requests() == 0

    def test_http_request_increments_total(self, collector):
        collector.http_request("/health")
        assert collector.get_total_http_requests() == 1

    def test_http_request_tracks_by_endpoint(self, collector):
        collector.http_request("/health")
        collector.http_request("/health")
        collector.http_request("/metrics")
        by_ep = collector.get_http_requests_by_endpoint()
        assert by_ep["/health"] == 2
        assert by_ep["/metrics"] == 1

    def test_http_request_total_aggregates_endpoints(self, collector):
        collector.http_request("/a")
        collector.http_request("/b")
        collector.http_request("/a")
        assert collector.get_total_http_requests() == 3


# ── MetricsCollector: error counters ──────────────────────────────────────────


class TestErrorMetrics:
    def test_initial_errors_is_zero(self, collector):
        assert collector.get_total_errors() == 0

    def test_error_occurred_increments(self, collector):
        collector.error_occurred("db")
        assert collector.get_total_errors() == 1

    def test_error_default_type_is_unknown(self, collector):
        collector.error_occurred()
        assert collector.get_errors_by_type()["unknown"] == 1

    def test_error_tracks_by_type(self, collector):
        collector.error_occurred("websocket_handler")
        collector.error_occurred("websocket_handler")
        collector.error_occurred("heartbeat")
        by_type = collector.get_errors_by_type()
        assert by_type["websocket_handler"] == 2
        assert by_type["heartbeat"] == 1


# ── MetricsCollector: snapshot ────────────────────────────────────────────────


class TestSnapshot:
    def test_snapshot_is_immutable_copy(self, collector):
        collector.connection_opened()
        collector.room_created()
        snap = collector.snapshot()
        assert isinstance(snap, MetricsSnapshot)
        assert snap.active_connections == 1
        assert snap.active_rooms == 1

    def test_snapshot_not_affected_by_later_changes(self, collector):
        snap_before = collector.snapshot()
        collector.connection_opened()
        assert snap_before.active_connections == 0

    def test_snapshot_includes_timestamp(self, collector):
        snap = collector.snapshot()
        assert snap.timestamp > 0

    def test_snapshot_http_requests_by_endpoint(self, collector):
        collector.http_request("/health")
        collector.http_request("/ready")
        snap = collector.snapshot()
        assert snap.http_requests_by_endpoint["/health"] == 1
        assert snap.http_requests_by_endpoint["/ready"] == 1

    def test_snapshot_errors_by_type(self, collector):
        collector.error_occurred("db")
        snap = collector.snapshot()
        assert snap.errors_by_type["db"] == 1


# ── MetricsCollector: reset ───────────────────────────────────────────────────


class TestReset:
    def test_reset_clears_all_counters(self, collector):
        collector.connection_opened()
        collector.room_created()
        collector.http_request("/health")
        collector.error_occurred("db")
        collector.set_matchmaking_queue_size(5)
        collector.reset()
        snap = collector.snapshot()
        assert snap.active_connections == 0
        assert snap.active_rooms == 0
        assert snap.matchmaking_queue_size == 0
        assert snap.total_http_requests == 0
        assert snap.total_errors == 0
        assert snap.http_requests_by_endpoint == {}
        assert snap.errors_by_type == {}


# ── Global singleton ──────────────────────────────────────────────────────────


class TestGlobalCollector:
    def test_get_metrics_collector_returns_same_instance(self):
        c1 = get_metrics_collector()
        c2 = get_metrics_collector()
        assert c1 is c2

    def test_reset_metrics_collector_creates_fresh_instance(self):
        c1 = get_metrics_collector()
        reset_metrics_collector()
        c2 = get_metrics_collector()
        assert c1 is not c2


# ── format_prometheus ─────────────────────────────────────────────────────────


class TestFormatPrometheus:
    def test_contains_help_and_type_lines(self):
        snap = MetricsSnapshot()
        output = format_prometheus(snap, server_id="test-server")
        assert "# HELP kfc_active_connections" in output
        assert "# TYPE kfc_active_connections gauge" in output
        assert "# HELP kfc_active_rooms" in output
        assert "# HELP kfc_matchmaking_queue_size" in output
        assert "# HELP kfc_http_requests_total" in output
        assert "# HELP kfc_errors_total" in output

    def test_server_id_label_in_output(self):
        snap = MetricsSnapshot()
        output = format_prometheus(snap, server_id="srv-42")
        assert 'server_id="srv-42"' in output

    def test_gauge_values_in_output(self):
        snap = MetricsSnapshot(active_connections=3, active_rooms=2, matchmaking_queue_size=1)
        output = format_prometheus(snap, server_id="s1")
        assert 'kfc_active_connections{server_id="s1"} 3' in output
        assert 'kfc_active_rooms{server_id="s1"} 2' in output
        assert 'kfc_matchmaking_queue_size{server_id="s1"} 1' in output

    def test_counter_values_in_output(self):
        snap = MetricsSnapshot(total_http_requests=10, total_errors=2)
        output = format_prometheus(snap, server_id="s1")
        assert 'kfc_http_requests_total{server_id="s1"} 10' in output
        assert 'kfc_errors_total{server_id="s1"} 2' in output

    def test_per_endpoint_lines_present_when_non_empty(self):
        snap = MetricsSnapshot(
            http_requests_by_endpoint={"/health": 5, "/metrics": 2}
        )
        output = format_prometheus(snap, server_id="s1")
        assert 'endpoint="/health"' in output
        assert 'endpoint="/metrics"' in output

    def test_per_endpoint_absent_when_empty(self):
        snap = MetricsSnapshot()
        output = format_prometheus(snap, server_id="s1")
        assert "kfc_http_requests_by_endpoint" not in output

    def test_per_error_type_lines_present_when_non_empty(self):
        snap = MetricsSnapshot(errors_by_type={"db": 1, "heartbeat": 3})
        output = format_prometheus(snap, server_id="s1")
        assert 'error_type="db"' in output
        assert 'error_type="heartbeat"' in output

    def test_default_server_id_is_unknown(self):
        snap = MetricsSnapshot()
        output = format_prometheus(snap)
        assert 'server_id="unknown"' in output


# ── RoomManager integration ───────────────────────────────────────────────────


class TestRoomManagerMetrics:
    def test_create_room_increments_active_rooms(self):
        from game.server.room_manager import RoomManager
        from game.server.game_session_manager import GameSessionManager

        rm = RoomManager(GameSessionManager())
        collector = get_metrics_collector()
        assert collector.get_active_rooms() == 0
        rm.create_room()
        assert collector.get_active_rooms() == 1

    def test_remove_room_decrements_active_rooms(self):
        from game.server.room_manager import RoomManager
        from game.server.game_session_manager import GameSessionManager

        rm = RoomManager(GameSessionManager())
        collector = get_metrics_collector()
        room = rm.create_room()
        assert collector.get_active_rooms() == 1
        rm.remove_room(room.room_id)
        assert collector.get_active_rooms() == 0

    def test_multiple_rooms_tracked(self):
        from game.server.room_manager import RoomManager
        from game.server.game_session_manager import GameSessionManager

        rm = RoomManager(GameSessionManager())
        collector = get_metrics_collector()
        r1 = rm.create_room()
        r2 = rm.create_room()
        r3 = rm.create_room()
        assert collector.get_active_rooms() == 3
        rm.remove_room(r1.room_id)
        assert collector.get_active_rooms() == 2
        rm.remove_room(r2.room_id)
        rm.remove_room(r3.room_id)
        assert collector.get_active_rooms() == 0


# ── GET /metrics gateway endpoint ────────────────────────────────────────────


@pytest_asyncio.fixture
async def gw_client(aiohttp_client, monkeypatch):
    """Gateway test client with a clean global metrics collector."""
    monkeypatch.setenv("KFC_SERVER_ID", "test-gateway")
    from game.gateway.app import create_app
    from game.server.auth.user_repository import UserRepository
    from game.server.auth.user_service import UserService

    repo = UserRepository(":memory:")
    repo.initialize_schema()
    service = UserService(repo)
    app = create_app(service)
    return await aiohttp_client(app)


@pytest.mark.asyncio
async def test_metrics_endpoint_returns_200(gw_client):
    resp = await gw_client.get("/metrics")
    assert resp.status == 200


@pytest.mark.asyncio
async def test_metrics_endpoint_content_type_is_text_plain(gw_client):
    resp = await gw_client.get("/metrics")
    assert "text/plain" in resp.content_type


@pytest.mark.asyncio
async def test_metrics_endpoint_contains_prometheus_lines(gw_client):
    resp = await gw_client.get("/metrics")
    body = await resp.text()
    assert "# HELP kfc_active_connections" in body
    assert "# TYPE kfc_active_connections gauge" in body
    assert "kfc_active_connections" in body
    assert "kfc_active_rooms" in body
    assert "kfc_errors_total" in body


@pytest.mark.asyncio
async def test_metrics_endpoint_server_id_label(gw_client):
    resp = await gw_client.get("/metrics")
    body = await resp.text()
    assert 'server_id="test-gateway"' in body


@pytest.mark.asyncio
async def test_metrics_endpoint_reflects_connection_count(gw_client, monkeypatch):
    """Mutating the global collector should be visible in /metrics output."""
    collector = get_metrics_collector()
    collector.connection_opened()
    collector.connection_opened()
    resp = await gw_client.get("/metrics")
    body = await resp.text()
    assert 'kfc_active_connections{server_id="test-gateway"} 2' in body


@pytest.mark.asyncio
async def test_metrics_endpoint_reflects_room_count(gw_client):
    collector = get_metrics_collector()
    collector.room_created()
    resp = await gw_client.get("/metrics")
    body = await resp.text()
    assert 'kfc_active_rooms{server_id="test-gateway"} 1' in body
