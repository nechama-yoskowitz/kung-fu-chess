"""
Regression tests for the reconnect restoration flow.

Verifies that a disconnected player who logs in again before timeout
is automatically restored to their game without going through the lobby.
"""

from unittest.mock import AsyncMock

import pytest

from game.server.protocol import (
    decode_message,
    make_create_room,
    make_join_room,
    make_login_request,
)
from game.server.reconnect_manager import ReconnectManager
from game.server.websocket_server import GameWebSocketServer
from game.server.auth.user_repository import UserRepository
from game.server.auth.user_service import UserService


def _ws():
    ws = AsyncMock()
    ws.send = AsyncMock()
    return ws


async def _setup_game_in_room(reconnect_mgr=None):
    """Create server, two players in a room, return all objects."""
    repo = UserRepository(":memory:")
    repo.initialize_schema()
    user_svc = UserService(repo)
    user_svc.register("alice", "pass")
    user_svc.register("bob", "pass")

    srv = GameWebSocketServer(
        user_service=user_svc,
        reconnect_manager=reconnect_mgr,
    )
    ws1, ws2 = _ws(), _ws()
    srv._connected.add(ws1)
    srv._connected.add(ws2)

    await srv._route_message(make_login_request("alice", "pass", "login"), ws1)
    await srv._route_message(make_login_request("bob", "pass", "login"), ws2)

    result1 = await srv._route_message(make_create_room(), ws1)
    room_id = decode_message(result1)["payload"]["room_id"]
    await srv._route_message(make_join_room(room_id), ws2)

    return srv, ws1, ws2, room_id


@pytest.mark.asyncio
class TestReconnectRestoration:
    async def test_reconnect_returns_login_success_with_color(self):
        """Reconnecting user gets login_success with their original color and reconnected=True."""
        clock = [0.0]
        rm = ReconnectManager(timeout=20.0, time_provider=lambda: clock[0])
        srv, ws1, ws2, room_id = await _setup_game_in_room(rm)

        # Alice disconnects
        srv._cleanup_client(ws1)
        assert rm.has_pending("alice")

        # Alice reconnects with new websocket
        clock[0] = 5.0
        ws_new = _ws()
        srv._connected.add(ws_new)
        result = srv._handle_login_request(
            {"action": "login", "username": "alice", "password": "pass"}, ws_new
        )

        # Should get login_success with color "w" and reconnected=True
        assert isinstance(result, list)
        login_msg = decode_message(result[0])
        assert login_msg["type"] == "login_success"
        assert login_msg["payload"]["color"] == "w"
        assert login_msg["payload"]["reconnected"] is True

    async def test_reconnect_returns_game_state(self):
        """Reconnecting user gets current game_state."""
        clock = [0.0]
        rm = ReconnectManager(timeout=20.0, time_provider=lambda: clock[0])
        srv, ws1, ws2, room_id = await _setup_game_in_room(rm)

        srv._cleanup_client(ws1)
        clock[0] = 5.0
        ws_new = _ws()
        srv._connected.add(ws_new)
        result = srv._handle_login_request(
            {"action": "login", "username": "alice", "password": "pass"}, ws_new
        )

        assert isinstance(result, list)
        assert len(result) == 2
        state_msg = decode_message(result[1])
        assert state_msg["type"] == "game_state"
        assert "board" in state_msg["payload"]

    async def test_reconnect_cancels_timer(self):
        """Successful reconnect cancels the auto-resign timer."""
        clock = [0.0]
        rm = ReconnectManager(timeout=20.0, time_provider=lambda: clock[0])
        srv, ws1, ws2, room_id = await _setup_game_in_room(rm)

        srv._cleanup_client(ws1)
        clock[0] = 5.0
        ws_new = _ws()
        srv._connected.add(ws_new)
        srv._handle_login_request(
            {"action": "login", "username": "alice", "password": "pass"}, ws_new
        )

        assert rm.pending_count == 0

        # Advance past original deadline — no auto-resign
        clock[0] = 25.0
        await srv._process_reconnect_expirations()
        room = srv.room_manager.get_room(room_id)
        assert room.session.engine.game_over is False

    async def test_reconnect_preserves_color(self):
        """Reconnected player keeps the same color (White)."""
        clock = [0.0]
        rm = ReconnectManager(timeout=20.0, time_provider=lambda: clock[0])
        srv, ws1, ws2, room_id = await _setup_game_in_room(rm)

        srv._cleanup_client(ws1)
        clock[0] = 5.0
        ws_new = _ws()
        srv._connected.add(ws_new)
        srv._handle_login_request(
            {"action": "login", "username": "alice", "password": "pass"}, ws_new
        )

        room = srv.room_manager.get_room(room_id)
        assert room.session.get_player_color(ws_new) == "w"

    async def test_reconnect_not_added_as_viewer(self):
        """Reconnected player is a player, not a viewer."""
        clock = [0.0]
        rm = ReconnectManager(timeout=20.0, time_provider=lambda: clock[0])
        srv, ws1, ws2, room_id = await _setup_game_in_room(rm)

        srv._cleanup_client(ws1)
        clock[0] = 5.0
        ws_new = _ws()
        srv._connected.add(ws_new)
        srv._handle_login_request(
            {"action": "login", "username": "alice", "password": "pass"}, ws_new
        )

        room = srv.room_manager.get_room(room_id)
        assert not room.session.is_viewer(ws_new)
        assert room.session.get_player_color(ws_new) == "w"

    async def test_opponent_receives_player_reconnected(self):
        """Opponent (Bob) receives player_reconnected notification."""
        clock = [0.0]
        rm = ReconnectManager(timeout=20.0, time_provider=lambda: clock[0])
        srv, ws1, ws2, room_id = await _setup_game_in_room(rm)

        srv._cleanup_client(ws1)
        clock[0] = 5.0
        ws_new = _ws()
        srv._connected.add(ws_new)
        srv._handle_login_request(
            {"action": "login", "username": "alice", "password": "pass"}, ws_new
        )

        room = srv.room_manager.get_room(room_id)
        await room.session.drain_outbox()

        bob_sends = [c.args[0] for c in ws2.send.call_args_list if c.args]
        bob_types = [decode_message(m)["type"] for m in bob_sends
                     if decode_message(m) is not None]
        assert "player_reconnected" in bob_types

    async def test_reconnect_after_timeout_fails(self):
        """After timeout, reconnect attempt goes to lobby instead."""
        clock = [0.0]
        rm = ReconnectManager(timeout=20.0, time_provider=lambda: clock[0])
        srv, ws1, ws2, room_id = await _setup_game_in_room(rm)

        srv._cleanup_client(ws1)
        clock[0] = 21.0
        await srv._process_reconnect_expirations()

        # Try to reconnect after timeout
        ws_new = _ws()
        srv._connected.add(ws_new)
        result = srv._handle_login_request(
            {"action": "login", "username": "alice", "password": "pass"}, ws_new
        )

        # Should get normal login_success with empty color (lobby)
        msg = decode_message(result) if isinstance(result, str) else decode_message(result[0])
        assert msg["type"] == "login_success"
        # No game_state follows — user goes to lobby
        if isinstance(result, list):
            assert len(result) == 1 or decode_message(result[1])["type"] != "game_state"

    async def test_reconnect_uses_new_websocket(self):
        """The new websocket is routed to the game session."""
        clock = [0.0]
        rm = ReconnectManager(timeout=20.0, time_provider=lambda: clock[0])
        srv, ws1, ws2, room_id = await _setup_game_in_room(rm)

        srv._cleanup_client(ws1)
        clock[0] = 5.0
        ws_new = _ws()
        srv._connected.add(ws_new)
        srv._handle_login_request(
            {"action": "login", "username": "alice", "password": "pass"}, ws_new
        )

        # New websocket is routed to the session
        session = srv.session_manager.get_session_for_client(ws_new)
        assert session is not None
        room = srv.room_manager.get_room(room_id)
        assert session is room.session


    async def test_normal_login_has_reconnected_false(self):
        """Normal login (no pending reconnect) has reconnected=False."""
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        user_svc = UserService(repo)
        user_svc.register("newuser", "pass")

        srv = GameWebSocketServer(user_service=user_svc)
        ws = _ws()
        srv._connected.add(ws)
        result = srv._handle_login_request(
            {"action": "login", "username": "newuser", "password": "pass"}, ws
        )

        msg = decode_message(result) if isinstance(result, str) else decode_message(result[0])
        assert msg["type"] == "login_success"
        assert msg["payload"].get("reconnected", False) is False
