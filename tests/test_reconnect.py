"""
Tests for player reconnect with 20-second countdown and auto-resign.

Uses an injectable time provider to avoid real 20-second waits.
"""

import time
from unittest.mock import AsyncMock

import pytest

from game.server.reconnect_manager import ReconnectManager, RECONNECT_TIMEOUT
from game.server.game_session import GameSession
from game.server.game_session_manager import GameSessionManager
from game.server.protocol import decode_message, make_move_request
from game.server.room_manager import RoomManager
from game.server.websocket_server import GameWebSocketServer
from game.server.auth.user_repository import UserRepository
from game.server.auth.user_service import UserService


def _ws():
    ws = AsyncMock()
    ws.send = AsyncMock()
    return ws


# ─── ReconnectManager unit tests ─────────────────────────────────────────────


class TestReconnectManagerBasics:
    def test_start_reconnect(self):
        clock = [0.0]
        rm = ReconnectManager(timeout=20.0, time_provider=lambda: clock[0])
        record = rm.start_reconnect("alice", "w", "room1", "session1")
        assert record.username == "alice"
        assert record.color == "w"
        assert rm.pending_count == 1

    def test_try_reconnect_within_deadline(self):
        clock = [0.0]
        rm = ReconnectManager(timeout=20.0, time_provider=lambda: clock[0])
        rm.start_reconnect("alice", "w", "room1", "session1")

        clock[0] = 10.0  # 10 seconds later
        record = rm.try_reconnect("alice")
        assert record is not None
        assert record.username == "alice"

    def test_try_reconnect_after_deadline(self):
        clock = [0.0]
        rm = ReconnectManager(timeout=20.0, time_provider=lambda: clock[0])
        rm.start_reconnect("alice", "w", "room1", "session1")

        clock[0] = 21.0  # past deadline
        record = rm.try_reconnect("alice")
        assert record is None
        assert rm.pending_count == 0

    def test_cancel(self):
        clock = [0.0]
        rm = ReconnectManager(timeout=20.0, time_provider=lambda: clock[0])
        rm.start_reconnect("alice", "w", "room1", "session1")
        rm.cancel("alice")
        assert rm.pending_count == 0

    def test_get_expired(self):
        clock = [0.0]
        rm = ReconnectManager(timeout=20.0, time_provider=lambda: clock[0])
        rm.start_reconnect("alice", "w", None, "s1")
        rm.start_reconnect("bob", "b", None, "s2")

        clock[0] = 21.0
        expired = rm.get_expired()
        assert len(expired) == 2
        assert rm.pending_count == 0

    def test_has_pending(self):
        rm = ReconnectManager()
        assert rm.has_pending("alice") is False
        rm.start_reconnect("alice", "w", None, "s1")
        assert rm.has_pending("alice") is True

    def test_remaining_seconds(self):
        clock = [0.0]
        rm = ReconnectManager(timeout=20.0, time_provider=lambda: clock[0])
        rm.start_reconnect("alice", "w", None, "s1")

        clock[0] = 5.0
        assert abs(rm.get_remaining_seconds("alice") - 15.0) < 0.01

    def test_different_username_cannot_reconnect(self):
        clock = [0.0]
        rm = ReconnectManager(timeout=20.0, time_provider=lambda: clock[0])
        rm.start_reconnect("alice", "w", None, "s1")

        record = rm.try_reconnect("bob")
        assert record is None


# ─── Server integration ───────────────────────────────────────────────────────


def _make_server_with_room():
    """Create a server with auth, two players in a room, return all objects."""
    repo = UserRepository(":memory:")
    repo.initialize_schema()
    user_svc = UserService(repo)
    user_svc.register("alice", "pass")
    user_svc.register("bob", "pass")
    return repo, user_svc


@pytest.mark.asyncio
class TestServerReconnectIntegration:
    async def _setup_game(self, reconnect_mgr=None):
        """Set up a server with two players in a room game."""
        repo, user_svc = _make_server_with_room()
        srv = GameWebSocketServer(
            user_service=user_svc,
            reconnect_manager=reconnect_mgr,
        )
        ws1, ws2 = _ws(), _ws()
        srv._connected.add(ws1)
        srv._connected.add(ws2)

        from game.server.protocol import make_login_request, make_create_room, make_join_room
        await srv._route_message(make_login_request("alice", "pass", "login"), ws1)
        await srv._route_message(make_login_request("bob", "pass", "login"), ws2)

        result = await srv._route_message(make_create_room(), ws1)
        room_id = decode_message(result)["payload"]["room_id"]
        await srv._route_message(make_join_room(room_id), ws2)

        return srv, ws1, ws2, room_id

    async def test_player_disconnect_starts_reservation(self):
        clock = [0.0]
        rm = ReconnectManager(timeout=20.0, time_provider=lambda: clock[0])
        srv, ws1, ws2, room_id = await self._setup_game(rm)

        # Alice disconnects
        srv._cleanup_client(ws1)

        assert rm.has_pending("alice")
        assert rm.pending_count == 1

    async def test_viewer_disconnect_no_reservation(self):
        clock = [0.0]
        rm = ReconnectManager(timeout=20.0, time_provider=lambda: clock[0])
        srv, ws1, ws2, room_id = await self._setup_game(rm)

        # Add a viewer
        repo, user_svc = _make_server_with_room()
        srv.user_service.register("viewer1", "pass")
        ws3 = _ws()
        srv._connected.add(ws3)
        from game.server.protocol import make_login_request, make_join_room
        await srv._route_message(make_login_request("viewer1", "pass", "login"), ws3)
        await srv._route_message(make_join_room(room_id), ws3)

        # Viewer disconnects
        srv._cleanup_client(ws3)
        assert rm.pending_count == 0

    async def test_reconnect_restores_player(self):
        clock = [0.0]
        rm = ReconnectManager(timeout=20.0, time_provider=lambda: clock[0])
        srv, ws1, ws2, room_id = await self._setup_game(rm)

        # Alice disconnects
        srv._cleanup_client(ws1)

        # Alice reconnects with new websocket
        clock[0] = 10.0
        ws_new = _ws()
        srv._connected.add(ws_new)
        from game.server.protocol import make_login_request
        result = srv._handle_login_request(
            {"action": "login", "username": "alice", "password": "pass"}, ws_new
        )

        # Should get login_success + game_state (reconnect)
        assert isinstance(result, list)
        assert len(result) == 2
        login_msg = decode_message(result[0])
        assert login_msg["type"] == "login_success"
        assert login_msg["payload"]["color"] == "w"

        # Pending reconnect cancelled
        assert rm.pending_count == 0

    async def test_reconnect_after_timeout_fails(self):
        clock = [0.0]
        rm = ReconnectManager(timeout=20.0, time_provider=lambda: clock[0])
        srv, ws1, ws2, room_id = await self._setup_game(rm)

        srv._cleanup_client(ws1)

        # Timeout expires
        clock[0] = 21.0
        # Process expirations
        await srv._process_reconnect_expirations()

        # Try to reconnect — should fail (record already expired)
        ws_new = _ws()
        srv._connected.add(ws_new)
        from game.server.protocol import make_login_request
        result = srv._handle_login_request(
            {"action": "login", "username": "alice", "password": "pass"}, ws_new
        )

        # Should NOT get a reconnect (no pending record)
        # Instead gets a normal login_success with empty color
        msg = decode_message(result) if isinstance(result, str) else decode_message(result[0])
        # After timeout, the game ended — alice gets a fresh login
        assert msg["type"] == "login_success"

    async def test_timeout_triggers_auto_resign(self):
        clock = [0.0]
        rm = ReconnectManager(timeout=20.0, time_provider=lambda: clock[0])
        srv, ws1, ws2, room_id = await self._setup_game(rm)

        srv._cleanup_client(ws1)

        clock[0] = 21.0
        await srv._process_reconnect_expirations()

        # Game should be over
        room = srv.room_manager.get_room(room_id)
        assert room.session.engine.game_over is True

    async def test_timeout_opponent_wins(self):
        clock = [0.0]
        rm = ReconnectManager(timeout=20.0, time_provider=lambda: clock[0])
        srv, ws1, ws2, room_id = await self._setup_game(rm)

        srv._cleanup_client(ws1)  # Alice (white) disconnects
        clock[0] = 21.0
        await srv._process_reconnect_expirations()

        # Bob (black) should have received game_ended with black as winner
        sends = [decode_message(c.args[0]) for c in ws2.send.call_args_list
                 if c.args and decode_message(c.args[0])]
        game_ended_msgs = [m for m in sends if m and m.get("type") == "game_ended"]
        assert len(game_ended_msgs) >= 1
        assert game_ended_msgs[0]["payload"]["winner"] == "b"

    async def test_reconnect_cancels_timeout(self):
        clock = [0.0]
        rm = ReconnectManager(timeout=20.0, time_provider=lambda: clock[0])
        srv, ws1, ws2, room_id = await self._setup_game(rm)

        srv._cleanup_client(ws1)
        assert rm.pending_count == 1

        # Reconnect before timeout
        clock[0] = 15.0
        ws_new = _ws()
        srv._connected.add(ws_new)
        from game.server.protocol import make_login_request
        srv._handle_login_request(
            {"action": "login", "username": "alice", "password": "pass"}, ws_new
        )

        assert rm.pending_count == 0

        # Advance past original deadline — should NOT trigger auto-resign
        clock[0] = 25.0
        await srv._process_reconnect_expirations()

        room = srv.room_manager.get_room(room_id)
        assert room.session.engine.game_over is False

    async def test_slot_preserved_during_disconnect(self):
        clock = [0.0]
        rm = ReconnectManager(timeout=20.0, time_provider=lambda: clock[0])
        srv, ws1, ws2, room_id = await self._setup_game(rm)

        srv._cleanup_client(ws1)

        # Room still exists, game not over
        room = srv.room_manager.get_room(room_id)
        assert room is not None
        assert room.session.engine.game_over is False
