"""
Tests for WebSocket server integration: connectivity, messaging, disconnect.

Uses a free local port per test to avoid conflicts.
Protocol-level tests are in test_protocol.py.
"""

import asyncio
import json

import pytest
import pytest_asyncio
import websockets

from game.server.websocket_server import GameWebSocketServer


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
            # First message is player_assigned, second is game_state
            assigned = await ws.recv()
            assert "player_assigned" in assigned
            state = await ws.recv()
            assert "game_state" in state

    async def test_ping_returns_pong(self, server):
        _, port = server
        async with websockets.connect(f"ws://localhost:{port}") as ws:
            await ws.recv()  # player_assigned
            await ws.recv()  # game_state
            await ws.send("ping")
            response = await ws.recv()
            assert response == "pong"

    async def test_echo_response(self, server):
        _, port = server
        async with websockets.connect(f"ws://localhost:{port}") as ws:
            await ws.recv()  # player_assigned
            await ws.recv()  # game_state
            await ws.send("hello server")
            response = json.loads(await ws.recv())
            assert response["type"] == "echo"
            assert response["payload"] == "hello server"

    async def test_empty_message_error(self, server):
        _, port = server
        async with websockets.connect(f"ws://localhost:{port}") as ws:
            await ws.recv()  # player_assigned
            await ws.recv()  # game_state
            await ws.send("")
            response = json.loads(await ws.recv())
            assert response["type"] == "error"
            assert "empty_message" in str(response["payload"])


@pytest.mark.asyncio
class TestMultipleClients:
    async def test_two_clients_independent(self, server):
        _, port = server
        uri = f"ws://localhost:{port}"
        async with websockets.connect(uri) as ws1, websockets.connect(uri) as ws2:
            await ws1.recv()  # player_assigned
            await ws1.recv()  # game_state
            await ws2.recv()  # player_assigned
            await ws2.recv()  # game_state
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
        await ws.recv()  # player_assigned
        await ws.recv()  # game_state
        await ws.close()
        await asyncio.sleep(0.05)

        async with websockets.connect(uri) as ws2:
            await ws2.recv()  # player_assigned (gets freed white slot)
            await ws2.recv()  # game_state
            await ws2.send("ping")
            assert await ws2.recv() == "pong"


@pytest.mark.asyncio
class TestConnectionFailure:
    async def test_client_connection_refused(self):
        with pytest.raises((ConnectionRefusedError, OSError)):
            await websockets.connect("ws://localhost:19999")
