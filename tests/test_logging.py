"""
Tests for structured logging configuration and event logging.

Uses pytest caplog to verify log output without depending on formatting.
"""

import logging
from unittest.mock import AsyncMock

import pytest

from game.logging_config import setup_logging, reset_logging


@pytest.fixture(autouse=True)
def _reset_logging_state():
    """Reset the logging configured flag between tests."""
    reset_logging()
    yield
    reset_logging()


# ─── Logging configuration ────────────────────────────────────────────────────


class TestLoggingConfig:
    def test_setup_does_not_duplicate_handlers(self):
        root = logging.getLogger()
        initial_count = len(root.handlers)
        setup_logging(level="INFO")
        after_first = len(root.handlers)
        setup_logging(level="INFO")  # second call
        after_second = len(root.handlers)
        assert after_first == after_second
        # Cleanup
        for h in root.handlers[initial_count:]:
            root.removeHandler(h)

    def test_level_configuration(self):
        setup_logging(level="DEBUG")
        root = logging.getLogger()
        assert root.level == logging.DEBUG
        for h in root.handlers[:]:
            root.removeHandler(h)

    def test_env_var_level(self, monkeypatch):
        monkeypatch.setenv("KFC_LOG_LEVEL", "WARNING")
        setup_logging()
        root = logging.getLogger()
        assert root.level == logging.WARNING
        for h in root.handlers[:]:
            root.removeHandler(h)


# ─── Sensitive data never logged ──────────────────────────────────────────────


class TestSensitiveDataProtection:
    def test_password_not_in_login_logs(self, caplog):
        from game.server.websocket_server import GameWebSocketServer
        from game.server.auth.user_repository import UserRepository
        from game.server.auth.user_service import UserService
        from game.server.protocol import make_login_request

        repo = UserRepository(":memory:")
        repo.initialize_schema()
        user_svc = UserService(repo)
        user_svc.register("alice", "supersecretpassword123")

        srv = GameWebSocketServer(user_service=user_svc)
        ws = AsyncMock()
        srv._connected.add(ws)

        with caplog.at_level(logging.DEBUG):
            srv._handle_login_request(
                {"action": "login", "username": "alice", "password": "supersecretpassword123"},
                ws,
            )

        # No log record should contain the password
        for record in caplog.records:
            assert "supersecretpassword123" not in record.getMessage()


# ─── Key server events are logged ────────────────────────────────────────────


class TestServerEventLogging:
    def test_login_success_logged(self, caplog):
        from game.server.websocket_server import GameWebSocketServer
        from game.server.auth.user_repository import UserRepository
        from game.server.auth.user_service import UserService

        repo = UserRepository(":memory:")
        repo.initialize_schema()
        user_svc = UserService(repo)
        user_svc.register("bob", "pass")

        srv = GameWebSocketServer(user_service=user_svc)
        ws = AsyncMock()
        srv._connected.add(ws)

        with caplog.at_level(logging.INFO):
            srv._handle_login_request(
                {"action": "login", "username": "bob", "password": "pass"}, ws
            )

        assert any("Login success" in r.getMessage() and "bob" in r.getMessage()
                   for r in caplog.records)

    def test_login_failure_logged(self, caplog):
        from game.server.websocket_server import GameWebSocketServer
        from game.server.auth.user_repository import UserRepository
        from game.server.auth.user_service import UserService

        repo = UserRepository(":memory:")
        repo.initialize_schema()
        user_svc = UserService(repo)
        user_svc.register("carol", "pass")

        srv = GameWebSocketServer(user_service=user_svc)
        ws = AsyncMock()
        srv._connected.add(ws)

        with caplog.at_level(logging.WARNING):
            srv._handle_login_request(
                {"action": "login", "username": "carol", "password": "wrong"}, ws
            )

        assert any("Login failed" in r.getMessage() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_room_creation_logged(self, caplog):
        from game.server.websocket_server import GameWebSocketServer
        from game.server.auth.user_repository import UserRepository
        from game.server.auth.user_service import UserService
        from game.server.protocol import make_login_request, make_create_room

        repo = UserRepository(":memory:")
        repo.initialize_schema()
        user_svc = UserService(repo)
        user_svc.register("dave", "pass")

        srv = GameWebSocketServer(user_service=user_svc)
        ws = AsyncMock()
        srv._connected.add(ws)

        await srv._route_message(make_login_request("dave", "pass", "login"), ws)

        with caplog.at_level(logging.INFO):
            await srv._route_message(make_create_room(), ws)

        assert any("Room created" in r.getMessage() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_matchmaking_entry_logged(self, caplog):
        from game.server.websocket_server import GameWebSocketServer
        from game.server.auth.user_repository import UserRepository
        from game.server.auth.user_service import UserService
        from game.server.protocol import make_login_request, make_play_request

        repo = UserRepository(":memory:")
        repo.initialize_schema()
        user_svc = UserService(repo)
        user_svc.register("eve", "pass")

        srv = GameWebSocketServer(user_service=user_svc)
        ws = AsyncMock()
        srv._connected.add(ws)

        await srv._route_message(make_login_request("eve", "pass", "login"), ws)

        with caplog.at_level(logging.INFO):
            await srv._route_message(make_play_request(), ws)

        assert any("Matchmaking" in r.getMessage() and "eve" in r.getMessage()
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_reconnect_timeout_logged(self, caplog):
        from game.server.websocket_server import GameWebSocketServer
        from game.server.reconnect_manager import ReconnectManager

        clock = [0.0]
        rm = ReconnectManager(timeout=20.0, time_provider=lambda: clock[0])
        rm.start_reconnect("frank", "w", None, "session-1")

        srv = GameWebSocketServer(reconnect_manager=rm)

        clock[0] = 21.0

        with caplog.at_level(logging.WARNING):
            await srv._process_reconnect_expirations()

        assert any("Reconnect timeout" in r.getMessage() and "frank" in r.getMessage()
                   for r in caplog.records)

    def test_rating_update_logged(self, caplog):
        from game.server.auth.user_repository import UserRepository
        from game.server.rating.rating_service import RatingService

        repo = UserRepository(":memory:")
        repo.initialize_schema()
        repo.create_user("winner", "h", rating=1200)
        repo.create_user("loser", "h", rating=1200)

        svc = RatingService(repository=repo)

        with caplog.at_level(logging.INFO):
            svc.process_game_end("game-log-test", "winner", "loser")

        assert any("Rating updated" in r.getMessage() for r in caplog.records)
