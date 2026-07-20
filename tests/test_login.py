"""
Focused tests for the username login handshake.

Covers:
- Valid login assigns correct color
- First player gets White, second gets Black
- Third player gets game_full
- Duplicate active username rejected
- Move request before login rejected
- Disconnect frees username and color
- Ownership checks still work after login
- Protocol validation (action + password required)
"""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from game.server.auth.user_repository import UserRepository
from game.server.auth.user_service import UserService
from game.server.game_session import GameSession
from game.server.protocol import (
    decode_message,
    make_login_request,
    make_move_request,
    make_jump_request,
    validate_login_request,
)
from game.server.websocket_server import GameWebSocketServer
from game.model.constants import MOVE_DURATION_MS


def _make_mock_client():
    client = AsyncMock()
    client.send = AsyncMock()
    return client


def _make_server():
    """Create a server with in-memory auth for testing."""
    repo = UserRepository(":memory:")
    repo.initialize_schema()
    user_service = UserService(repo)
    session = GameSession()
    server = GameWebSocketServer(
        host="localhost", port=0,
        session=session, user_service=user_service,
    )
    return server, user_service, session


async def _register_via_server(server, session, client, username, password="pass"):
    """Register and login a client through the server auth flow."""
    session.add_client(client)
    raw = make_login_request(username, password, action="register")
    return await server._route_message(raw, client)


# ─── Protocol validation ──────────────────────────────────────────────────────


class TestLoginValidation:
    def test_valid_login_request(self):
        payload = {"action": "login", "username": "Alice", "password": "pass"}
        assert validate_login_request(payload) is None

    def test_valid_register_request(self):
        payload = {"action": "register", "username": "Alice", "password": "pass"}
        assert validate_login_request(payload) is None

    def test_missing_action_rejected(self):
        payload = {"username": "Alice", "password": "pass"}
        error = validate_login_request(payload)
        assert error is not None
        assert "action" in error

    def test_whitespace_only_username_rejected(self):
        payload = {"action": "login", "username": "   ", "password": "pass"}
        error = validate_login_request(payload)
        assert error is not None
        assert "empty" in error

    def test_non_string_username_rejected(self):
        payload = {"action": "login", "username": 123, "password": "pass"}
        error = validate_login_request(payload)
        assert error is not None
        assert "string" in error

    def test_empty_password_rejected(self):
        payload = {"action": "login", "username": "Alice", "password": ""}
        error = validate_login_request(payload)
        assert error is not None


# ─── Login via server auth flow ───────────────────────────────────────────────


@pytest.mark.asyncio
class TestLoginAssignment:
    async def test_first_player_gets_white(self):
        server, _, session = _make_server()
        client = _make_mock_client()
        result = await _register_via_server(server, session, client, "Alice")
        success = decode_message(result[0])
        assert success["type"] == "login_success"
        assert success["payload"]["color"] == "w"

    async def test_second_player_gets_black(self):
        server, _, session = _make_server()
        c1, c2 = _make_mock_client(), _make_mock_client()
        await _register_via_server(server, session, c1, "Alice")
        result = await _register_via_server(server, session, c2, "Bob")
        success = decode_message(result[0])
        assert success["payload"]["color"] == "b"

    async def test_third_player_gets_game_full(self):
        server, _, session = _make_server()
        c1, c2, c3 = _make_mock_client(), _make_mock_client(), _make_mock_client()
        await _register_via_server(server, session, c1, "Alice")
        await _register_via_server(server, session, c2, "Bob")
        result = await _register_via_server(server, session, c3, "Charlie")
        msg = decode_message(result)
        assert msg["type"] == "error"
        assert msg["payload"]["code"] == "game_full"

    async def test_duplicate_active_username_rejected(self):
        server, user_service, session = _make_server()
        user_service.register("Dave", "pass")

        c1, c2 = _make_mock_client(), _make_mock_client()
        session.add_client(c1)
        session.add_client(c2)

        raw = make_login_request("Dave", "pass", action="login")
        await server._route_message(raw, c1)
        result = await server._route_message(raw, c2)
        msg = decode_message(result)
        assert msg["type"] == "error"
        assert msg["payload"]["code"] == "username_in_use"


# ─── Disconnect frees slot ────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestDisconnectFreesSlot:
    async def test_disconnect_frees_color_and_username(self):
        server, _, session = _make_server()
        c1, c2 = _make_mock_client(), _make_mock_client()
        await _register_via_server(server, session, c1, "Alice")
        await _register_via_server(server, session, c2, "Bob")

        session.remove_client(c1)

        c3 = _make_mock_client()
        result = await _register_via_server(server, session, c3, "Charlie")
        success = decode_message(result[0])
        assert success["payload"]["color"] == "w"


# ─── Move/jump before login rejected ─────────────────────────────────────────


@pytest.mark.asyncio
class TestNotLoggedIn:
    async def test_move_request_before_login_rejected(self):
        server, _, session = _make_server()
        client = _make_mock_client()
        session.add_client(client)

        raw = make_move_request(6, 0, 5, 0)
        result = await server._route_message(raw, client)
        msg = decode_message(result)
        assert msg["type"] == "error"
        assert msg["payload"]["code"] == "not_logged_in"

    async def test_jump_request_before_login_rejected(self):
        server, _, session = _make_server()
        client = _make_mock_client()
        session.add_client(client)

        raw = make_jump_request(6, 0)
        result = await server._route_message(raw, client)
        msg = decode_message(result)
        assert msg["type"] == "error"
        assert msg["payload"]["code"] == "not_logged_in"


# ─── Ownership still works after login ────────────────────────────────────────


@pytest.mark.asyncio
class TestOwnershipAfterLogin:
    async def test_white_can_move_own_piece(self):
        server, _, session = _make_server()
        white = _make_mock_client()
        await _register_via_server(server, session, white, "Alice")

        raw = make_move_request(6, 0, 5, 0)  # wP forward
        result = await session.handle_message(raw, sender=white)
        assert result is None  # Accepted

    async def test_white_cannot_move_black_piece(self):
        server, _, session = _make_server()
        white = _make_mock_client()
        await _register_via_server(server, session, white, "Alice")

        raw = make_move_request(1, 0, 2, 0)  # bP
        result = await session.handle_message(raw, sender=white)
        msg = decode_message(result)
        assert msg["type"] == "move_rejected"
        assert msg["payload"]["reason"] == "not_your_piece"

    async def test_black_can_move_own_piece(self):
        server, _, session = _make_server()
        white, black = _make_mock_client(), _make_mock_client()
        await _register_via_server(server, session, white, "Alice")
        await _register_via_server(server, session, black, "Bob")

        raw = make_move_request(1, 0, 2, 0)  # bP forward
        result = await session.handle_message(raw, sender=black)
        assert result is None

    async def test_black_cannot_move_white_piece(self):
        server, _, session = _make_server()
        white, black = _make_mock_client(), _make_mock_client()
        await _register_via_server(server, session, white, "Alice")
        await _register_via_server(server, session, black, "Bob")

        raw = make_move_request(6, 0, 5, 0)  # wP
        result = await session.handle_message(raw, sender=black)
        msg = decode_message(result)
        assert msg["payload"]["reason"] == "not_your_piece"

    async def test_jump_ownership_after_login(self):
        server, _, session = _make_server()
        white = _make_mock_client()
        await _register_via_server(server, session, white, "Alice")

        raw = make_jump_request(6, 0)  # wP
        result = await session.handle_message(raw, sender=white)
        assert result is None

    async def test_jump_opponent_piece_rejected(self):
        server, _, session = _make_server()
        white = _make_mock_client()
        await _register_via_server(server, session, white, "Alice")

        raw = make_jump_request(0, 0)  # bR
        result = await session.handle_message(raw, sender=white)
        msg = decode_message(result)
        assert msg["type"] == "move_rejected"
        assert msg["payload"]["reason"] == "not_your_piece"
