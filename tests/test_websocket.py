"""
Tests for WebSocket server integration: connectivity, messaging, disconnect.

Uses a free local port per test to avoid conflicts.
"""

import asyncio
import json

import pytest
import pytest_asyncio
import websockets

from game.server.auth.user_repository import UserRepository
from game.server.auth.user_service import UserService
from game.server.game_session import GameSession
from game.server.protocol import make_login_request
from game.server.websocket_server import GameWebSocketServer


@pytest_asyncio.fixture
async def server():
    """Start a server with in-memory auth and a pre-built session (legacy mode)."""
    repo = UserRepository(":memory:")
    repo.initialize_schema()
    user_service = UserService(repo)
    session = GameSession()
    srv = GameWebSocketServer(
        host="localhost", port=0,
        user_service=user_service,
        session=session,
    )
    await srv.start()
    port = srv._server.sockets[0].getsockname()[1]
    yield srv, port, user_service
    await srv.stop()


async def _connect_and_register(port, username, password="pass"):
    """Connect, register, return (ws, login_resp, state_resp)."""
    ws = await websockets.connect(f"ws://localhost:{port}")
    await ws.send(make_login_request(username, password, action="register"))
    login_resp = json.loads(await ws.recv())
    state_resp = json.loads(await ws.recv())
    return ws, login_resp, state_resp


@pytest.mark.asyncio
class TestServerStartup:
    async def test_server_starts(self, server):
        srv, port, _ = server
        assert port > 0

    async def test_server_stops_cleanly(self):
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        srv = GameWebSocketServer(
            host="localhost", port=0,
            user_service=UserService(repo),
            session=GameSession(),
        )
        await srv.start()
        await srv.stop()


@pytest.mark.asyncio
class TestClientConnection:
    async def test_client_can_register_and_login(self, server):
        _, port, _ = server
        ws, login_resp, state_resp = await _connect_and_register(port, "Alice")
        assert login_resp["type"] == "login_success"
        assert login_resp["payload"]["color"] == "w"
        assert state_resp["type"] == "game_state"
        await ws.close()

    async def test_ping_returns_pong(self, server):
        _, port, _ = server
        ws, _, _ = await _connect_and_register(port, "Alice")
        await ws.send("ping")
        response = await ws.recv()
        assert response == "pong"
        await ws.close()

    async def test_echo_response(self, server):
        _, port, _ = server
        ws, _, _ = await _connect_and_register(port, "Alice")
        await ws.send("hello server")
        response = json.loads(await ws.recv())
        assert response["type"] == "echo"
        assert response["payload"] == "hello server"
        await ws.close()

    async def test_empty_message_error(self, server):
        _, port, _ = server
        ws, _, _ = await _connect_and_register(port, "Alice")
        await ws.send("")
        response = json.loads(await ws.recv())
        assert response["type"] == "error"
        assert "empty_message" in str(response["payload"])
        await ws.close()


@pytest.mark.asyncio
class TestMultipleClients:
    async def test_two_clients_independent(self, server):
        _, port, _ = server
        ws1, _, _ = await _connect_and_register(port, "Alice")
        ws2, _, _ = await _connect_and_register(port, "Bob")
        await ws1.send("ping")
        await ws2.send("hello")
        r1 = await ws1.recv()
        r2 = json.loads(await ws2.recv())
        assert r1 == "pong"
        assert r2["payload"] == "hello"
        await ws1.close()
        await ws2.close()


@pytest.mark.asyncio
class TestClientDisconnect:
    async def test_disconnect_does_not_crash_server(self, server):
        srv, port, user_service = server
        uri = f"ws://localhost:{port}"

        ws = await websockets.connect(uri)
        await ws.send(make_login_request("Alice", "pass", action="register"))
        await ws.recv()  # login_success
        await ws.recv()  # game_state
        await ws.close()
        await asyncio.sleep(0.05)

        # New client can connect and register (gets freed white slot)
        ws2, login_resp, _ = await _connect_and_register(port, "Bob")
        assert login_resp["payload"]["color"] == "w"
        await ws2.close()


@pytest.mark.asyncio
class TestConnectionFailure:
    async def test_client_connection_refused(self):
        with pytest.raises((ConnectionRefusedError, OSError)):
            await websockets.connect("ws://localhost:19999")
