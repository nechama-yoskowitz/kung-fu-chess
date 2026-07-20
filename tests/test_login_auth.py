"""
Focused tests for the integrated authentication + WebSocket login flow.

Covers:
- Protocol: register/login request format, validation
- Server integration: register assigns White, login assigns player, wrong password fails
- Duplicate registration, nonexistent user, unauthenticated move rejected
- Active duplicate username rejected, disconnect releases username
- Persistence across service instances
- GameSession does not receive raw passwords
- Password never in response
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
    validate_login_request,
)
from game.server.websocket_server import GameWebSocketServer


def _make_mock_client():
    client = AsyncMock()
    client.send = AsyncMock()
    return client


def _make_server_with_auth(board=None):
    """Create a GameWebSocketServer with in-memory auth for testing."""
    repo = UserRepository(":memory:")
    repo.initialize_schema()
    user_service = UserService(repo)
    session = GameSession(board=board)
    server = GameWebSocketServer(
        host="localhost", port=0,
        session=session,
        user_service=user_service,
    )
    return server, user_service, session


async def _register_and_login(server, client, username, password):
    """Register user then send login_request via server routing. Returns response."""
    server.user_service.register(username, password)
    raw = make_login_request(username, password, action="login")
    return await server._route_message(raw, client)


# ─── Protocol validation ──────────────────────────────────────────────────────


class TestProtocolValidation:
    def test_register_request_valid(self):
        payload = {"action": "register", "username": "Alice", "password": "pass123"}
        assert validate_login_request(payload) is None

    def test_login_request_valid(self):
        payload = {"action": "login", "username": "Alice", "password": "pass123"}
        assert validate_login_request(payload) is None

    def test_missing_action_rejected(self):
        payload = {"username": "Alice", "password": "pass"}
        error = validate_login_request(payload)
        assert error is not None
        assert "action" in error

    def test_invalid_action_rejected(self):
        payload = {"action": "hack", "username": "Alice", "password": "pass"}
        error = validate_login_request(payload)
        assert error is not None
        assert "unsupported" in error

    def test_missing_password_rejected(self):
        payload = {"action": "login", "username": "Alice"}
        error = validate_login_request(payload)
        assert error is not None
        assert "password" in error

    def test_empty_password_rejected(self):
        payload = {"action": "login", "username": "Alice", "password": ""}
        error = validate_login_request(payload)
        assert error is not None

    def test_missing_username_rejected(self):
        payload = {"action": "login", "password": "pass"}
        error = validate_login_request(payload)
        assert error is not None
        assert "username" in error

    def test_non_string_password_rejected(self):
        payload = {"action": "login", "username": "Alice", "password": 12345}
        error = validate_login_request(payload)
        assert error is not None

    def test_make_login_request_includes_all_fields(self):
        raw = make_login_request("Alice", "secret", action="register")
        msg = decode_message(raw)
        assert msg["type"] == "login_request"
        assert msg["payload"]["action"] == "register"
        assert msg["payload"]["username"] == "Alice"
        assert msg["payload"]["password"] == "secret"


# ─── Server authentication integration ───────────────────────────────────────


@pytest.mark.asyncio
class TestServerAuthIntegration:
    async def test_register_assigns_white(self):
        server, _, session = _make_server_with_auth()
        client = _make_mock_client()
        session.add_client(client)

        raw = make_login_request("Alice", "pass123", action="register")
        result = await server._route_message(raw, client)

        assert isinstance(result, list)
        success = decode_message(result[0])
        assert success["type"] == "login_success"
        assert success["payload"]["color"] == "w"
        assert success["payload"]["username"] == "Alice"

    async def test_login_assigns_player(self):
        server, user_service, session = _make_server_with_auth()
        # Pre-register user
        user_service.register("Bob", "mypass")

        client = _make_mock_client()
        session.add_client(client)

        raw = make_login_request("Bob", "mypass", action="login")
        result = await server._route_message(raw, client)

        assert isinstance(result, list)
        success = decode_message(result[0])
        assert success["type"] == "login_success"
        assert success["payload"]["color"] == "w"

    async def test_wrong_password_rejected(self):
        server, user_service, session = _make_server_with_auth()
        user_service.register("Carol", "correct")

        client = _make_mock_client()
        session.add_client(client)

        raw = make_login_request("Carol", "wrong", action="login")
        result = await server._route_message(raw, client)

        msg = decode_message(result)
        assert msg["type"] == "error"
        assert msg["payload"]["code"] == "invalid_credentials"

    async def test_nonexistent_user_login_fails(self):
        server, _, session = _make_server_with_auth()
        client = _make_mock_client()
        session.add_client(client)

        raw = make_login_request("Ghost", "pass", action="login")
        result = await server._route_message(raw, client)

        msg = decode_message(result)
        assert msg["type"] == "error"
        assert msg["payload"]["code"] == "invalid_credentials"

    async def test_duplicate_registration_fails(self):
        server, _, session = _make_server_with_auth()
        c1 = _make_mock_client()
        session.add_client(c1)

        # First register succeeds
        raw1 = make_login_request("Dave", "pass1", action="register")
        result1 = await server._route_message(raw1, c1)
        assert decode_message(result1[0])["type"] == "login_success"

        # Second register with same username fails
        c2 = _make_mock_client()
        session.add_client(c2)
        raw2 = make_login_request("Dave", "pass2", action="register")
        result2 = await server._route_message(raw2, c2)
        msg = decode_message(result2)
        assert msg["type"] == "error"
        assert msg["payload"]["code"] == "username_taken"

    async def test_second_user_receives_black(self):
        server, _, session = _make_server_with_auth()
        c1 = _make_mock_client()
        c2 = _make_mock_client()
        session.add_client(c1)
        session.add_client(c2)

        raw1 = make_login_request("Eve", "pass1", action="register")
        await server._route_message(raw1, c1)

        raw2 = make_login_request("Frank", "pass2", action="register")
        result2 = await server._route_message(raw2, c2)

        success = decode_message(result2[0])
        assert success["payload"]["color"] == "b"

    async def test_third_user_game_full(self):
        server, _, session = _make_server_with_auth()
        c1, c2, c3 = _make_mock_client(), _make_mock_client(), _make_mock_client()
        session.add_client(c1)
        session.add_client(c2)
        session.add_client(c3)

        await server._route_message(
            make_login_request("P1", "p", action="register"), c1)
        await server._route_message(
            make_login_request("P2", "p", action="register"), c2)
        result3 = await server._route_message(
            make_login_request("P3", "p", action="register"), c3)

        msg = decode_message(result3)
        assert msg["type"] == "error"
        assert msg["payload"]["code"] == "game_full"

    async def test_unauthenticated_move_rejected(self):
        server, _, session = _make_server_with_auth()
        client = _make_mock_client()
        session.add_client(client)

        raw = make_move_request(6, 0, 5, 0)
        result = await server._route_message(raw, client)

        msg = decode_message(result)
        assert msg["type"] == "error"
        assert msg["payload"]["code"] == "not_logged_in"

    async def test_active_duplicate_username_rejected(self):
        server, user_service, session = _make_server_with_auth()
        user_service.register("Grace", "pass")

        c1 = _make_mock_client()
        c2 = _make_mock_client()
        session.add_client(c1)
        session.add_client(c2)

        # First login succeeds
        raw1 = make_login_request("Grace", "pass", action="login")
        result1 = await server._route_message(raw1, c1)
        assert decode_message(result1[0])["type"] == "login_success"

        # Second login with same username while first is connected
        raw2 = make_login_request("Grace", "pass", action="login")
        result2 = await server._route_message(raw2, c2)
        msg = decode_message(result2)
        assert msg["type"] == "error"
        assert msg["payload"]["code"] == "username_in_use"

    async def test_disconnect_releases_username(self):
        server, user_service, session = _make_server_with_auth()
        user_service.register("Heidi", "pass")

        c1 = _make_mock_client()
        session.add_client(c1)
        await server._route_message(
            make_login_request("Heidi", "pass", action="login"), c1)

        # Disconnect
        session.remove_client(c1)

        # New client can use the same username
        c2 = _make_mock_client()
        session.add_client(c2)
        result = await server._route_message(
            make_login_request("Heidi", "pass", action="login"), c2)
        success = decode_message(result[0])
        assert success["type"] == "login_success"

    async def test_password_not_in_response(self):
        server, _, session = _make_server_with_auth()
        client = _make_mock_client()
        session.add_client(client)

        raw = make_login_request("Ivan", "secret123", action="register")
        result = await server._route_message(raw, client)

        # Check no response message contains the password
        for msg_str in result:
            assert "secret123" not in msg_str
            assert "password_hash" not in msg_str

    async def test_game_session_does_not_receive_password(self):
        """GameSession.login_client only receives username, never password."""
        server, _, session = _make_server_with_auth()
        client = _make_mock_client()
        session.add_client(client)

        raw = make_login_request("Judy", "pass", action="register")
        await server._route_message(raw, client)

        # Session stores only username, no password
        assert session.get_player_username(client) == "Judy"
        # No password-related attributes in session
        assert not hasattr(session, '_passwords')


# ─── Persistence across instances ─────────────────────────────────────────────


class TestPersistence:
    def test_registered_user_persists_across_service_instances(self):
        """User registered with one service instance can login with a new one."""
        import tempfile
        import os

        # Use a temp file for the DB
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            # First instance: register
            repo1 = UserRepository(db_path)
            repo1.initialize_schema()
            svc1 = UserService(repo1)
            result = svc1.register("Kate", "mypass")
            assert result.success is True

            # Second instance: authenticate
            repo2 = UserRepository(db_path)
            repo2.initialize_schema()
            svc2 = UserService(repo2)
            result = svc2.authenticate("Kate", "mypass")
            assert result.success is True
            assert result.user.username == "Kate"
            assert result.user.rating == 1200
        finally:
            os.unlink(db_path)
