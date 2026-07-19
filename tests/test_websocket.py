"""
Tests for WebSocket server, client connectivity, and protocol.

Uses a free local port per test to avoid conflicts.
"""

import asyncio
import json

import pytest
import pytest_asyncio
import websockets

from game.server.protocol import handle_message
from game.server.websocket_server import GameWebSocketServer


# --- Protocol unit tests (no networking) ---


class TestProtocol:
    """Protocol message handling logic."""

    def test_ping_returns_pong(self):
        assert handle_message("ping") == "pong"

    def test_echo_returns_json(self):
        result = json.loads(handle_message("hello"))
        assert result["type"] == "echo"
        assert result["payload"] == "hello"

    def test_echo_strips_whitespace_in_payload(self):
        result = json.loads(handle_message("  hello world  "))
        assert result["payload"] == "hello world"

    def test_empty_message_returns_error(self):
        result = json.loads(handle_message(""))
        assert result["type"] == "error"
        assert result["message"] == "empty_message"

    def test_whitespace_only_returns_error(self):
        result = json.loads(handle_message("   "))
        assert result["type"] == "error"
        assert result["message"] == "empty_message"

    def test_ping_with_surrounding_whitespace_is_still_ping(self):
        """'  ping  ' strips to 'ping' → pong."""
        assert handle_message("  ping  ") == "pong"

    def test_unknown_message_is_echoed(self):
        result = json.loads(handle_message("foobar123"))
        assert result["type"] == "echo"
        assert result["payload"] == "foobar123"


# --- Integration tests (require running server) ---


@pytest_asyncio.fixture
async def server():
    """Start a server on a free port, yield (server, port), stop after test."""
    srv = GameWebSocketServer(host="localhost", port=0)
    await srv.start()
    port = srv._server.sockets[0].getsockname()[1]
    yield srv, port
    await srv.stop()


@pytest.mark.asyncio
class TestServerStartup:
    async def test_server_starts(self, server):
        srv, port = server
        assert port > 0

    async def test_server_stops_cleanly(self):
        srv = GameWebSocketServer(host="localhost", port=0)
        await srv.start()
        await srv.stop()


@pytest.mark.asyncio
class TestClientConnection:
    async def test_client_can_connect(self, server):
        _, port = server
        async with websockets.connect(f"ws://localhost:{port}") as ws:
            await ws.send("ping")
            assert await ws.recv() == "pong"

    async def test_ping_returns_pong(self, server):
        _, port = server
        async with websockets.connect(f"ws://localhost:{port}") as ws:
            await ws.send("ping")
            response = await ws.recv()
            assert response == "pong"

    async def test_echo_response(self, server):
        _, port = server
        async with websockets.connect(f"ws://localhost:{port}") as ws:
            await ws.send("hello server")
            response = json.loads(await ws.recv())
            assert response["type"] == "echo"
            assert response["payload"] == "hello server"

    async def test_empty_message_error(self, server):
        _, port = server
        async with websockets.connect(f"ws://localhost:{port}") as ws:
            await ws.send("")
            response = json.loads(await ws.recv())
            assert response["type"] == "error"
            assert response["message"] == "empty_message"


@pytest.mark.asyncio
class TestMultipleClients:
    async def test_two_clients_independent(self, server):
        _, port = server
        uri = f"ws://localhost:{port}"
        async with websockets.connect(uri) as ws1, websockets.connect(uri) as ws2:
            await ws1.send("ping")
            await ws2.send("hello")
            r1 = await ws1.recv()
            r2 = json.loads(await ws2.recv())
            assert r1 == "pong"
            assert r2["payload"] == "hello"


@pytest.mark.asyncio
class TestClientDisconnect:
    async def test_disconnect_does_not_crash_server(self, server):
        srv, port = server
        uri = f"ws://localhost:{port}"

        ws = await websockets.connect(uri)
        await ws.close()
        await asyncio.sleep(0.05)

        async with websockets.connect(uri) as ws2:
            await ws2.send("ping")
            assert await ws2.recv() == "pong"


@pytest.mark.asyncio
class TestConnectionFailure:
    async def test_client_connection_refused(self):
        with pytest.raises((ConnectionRefusedError, OSError)):
            await websockets.connect("ws://localhost:19999")
