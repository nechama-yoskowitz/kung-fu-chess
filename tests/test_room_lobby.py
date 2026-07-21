"""
Regression tests for the room lobby flow.

Verifies:
- Room creator receives game_state when second player joins
- Both players can start graphical gameplay
- Creator does not time out when opponent joins
- Abandoned room cleanup works correctly
"""

from unittest.mock import AsyncMock

import pytest

from game.server.protocol import (
    decode_message,
    make_create_room,
    make_join_room,
    make_login_request,
    make_move_request,
)
from game.server.websocket_server import GameWebSocketServer
from game.server.auth.user_repository import UserRepository
from game.server.auth.user_service import UserService


def _ws():
    ws = AsyncMock()
    ws.send = AsyncMock()
    return ws


async def _setup_server_with_users(*usernames):
    """Create server with registered users."""
    repo = UserRepository(":memory:")
    repo.initialize_schema()
    user_svc = UserService(repo)
    for u in usernames:
        user_svc.register(u, "pass")
    srv = GameWebSocketServer(user_service=user_svc)
    return srv


async def _login(srv, ws, username):
    """Authenticate a websocket."""
    srv._connected.add(ws)
    await srv._route_message(make_login_request(username, "pass", "login"), ws)


@pytest.mark.asyncio
class TestRoomCreatorReceivesGameState:
    async def test_creator_receives_game_state_when_opponent_joins(self):
        """Player 1 creates room, Player 2 joins → both get game_state."""
        srv = await _setup_server_with_users("alice", "bob")
        ws1, ws2 = _ws(), _ws()
        await _login(srv, ws1, "alice")
        await _login(srv, ws2, "bob")

        # Alice creates room
        result1 = await srv._route_message(make_create_room(), ws1)
        room_id = decode_message(result1)["payload"]["room_id"]

        # Bob joins room
        result2 = await srv._route_message(make_join_room(room_id), ws2)

        # Drain the session outbox (game_state broadcast)
        room = srv.room_manager.get_room(room_id)
        await room.session.drain_outbox()

        # Player 1 (alice) should have received the game_state broadcast
        alice_sends = [c.args[0] for c in ws1.send.call_args_list if c.args]
        alice_types = [decode_message(m)["type"] for m in alice_sends
                       if decode_message(m) is not None]
        assert "game_state" in alice_types

    async def test_both_players_receive_game_state(self):
        """Both players get game_state after room becomes full."""
        srv = await _setup_server_with_users("alice", "bob")
        ws1, ws2 = _ws(), _ws()
        await _login(srv, ws1, "alice")
        await _login(srv, ws2, "bob")

        result1 = await srv._route_message(make_create_room(), ws1)
        room_id = decode_message(result1)["payload"]["room_id"]
        result2 = await srv._route_message(make_join_room(room_id), ws2)

        room = srv.room_manager.get_room(room_id)
        await room.session.drain_outbox()

        # Alice (Player 1) gets game_state via broadcast
        alice_sends = [c.args[0] for c in ws1.send.call_args_list if c.args]
        alice_game_states = [m for m in alice_sends
                             if decode_message(m) and decode_message(m)["type"] == "game_state"]
        assert len(alice_game_states) >= 1

        # Bob (Player 2) gets game_state in the broadcast too
        bob_sends = [c.args[0] for c in ws2.send.call_args_list if c.args]
        bob_game_states = [m for m in bob_sends
                           if decode_message(m) and decode_message(m)["type"] == "game_state"]
        assert len(bob_game_states) >= 1

    async def test_creator_is_white_joiner_is_black(self):
        """Player 1 is White, Player 2 is Black."""
        srv = await _setup_server_with_users("alice", "bob")
        ws1, ws2 = _ws(), _ws()
        await _login(srv, ws1, "alice")
        await _login(srv, ws2, "bob")

        result1 = await srv._route_message(make_create_room(), ws1)
        room_id = decode_message(result1)["payload"]["room_id"]
        result2 = await srv._route_message(make_join_room(room_id), ws2)

        room = srv.room_manager.get_room(room_id)
        assert room.session.get_player_color(ws1) == "w"
        assert room.session.get_player_color(ws2) == "b"

    async def test_gameplay_works_after_join(self):
        """After both join, gameplay commands are accepted."""
        srv = await _setup_server_with_users("alice", "bob")
        ws1, ws2 = _ws(), _ws()
        await _login(srv, ws1, "alice")
        await _login(srv, ws2, "bob")

        result1 = await srv._route_message(make_create_room(), ws1)
        room_id = decode_message(result1)["payload"]["room_id"]
        await srv._route_message(make_join_room(room_id), ws2)

        # Alice (White) can move
        result = await srv._route_message(make_move_request(6, 0, 5, 0), ws1)
        assert result is None  # Accepted

    async def test_room_removed_when_creator_disconnects(self):
        """If creator disconnects before anyone joins, room is cleaned up."""
        srv = await _setup_server_with_users("alice")
        ws1 = _ws()
        await _login(srv, ws1, "alice")

        result1 = await srv._route_message(make_create_room(), ws1)
        room_id = decode_message(result1)["payload"]["room_id"]
        assert srv.room_manager.room_count == 1

        # Creator disconnects
        srv._cleanup_client(ws1)

        # Room should be removed (empty)
        assert srv.room_manager.room_count == 0

    async def test_joining_removed_room_fails(self):
        """After creator disconnects, joining that room fails."""
        srv = await _setup_server_with_users("alice", "bob")
        ws1, ws2 = _ws(), _ws()
        await _login(srv, ws1, "alice")
        await _login(srv, ws2, "bob")

        result1 = await srv._route_message(make_create_room(), ws1)
        room_id = decode_message(result1)["payload"]["room_id"]

        # Creator disconnects
        srv._cleanup_client(ws1)

        # Bob tries to join — should fail
        result2 = await srv._route_message(make_join_room(room_id), ws2)
        msg = decode_message(result2)
        assert msg["type"] == "error"
        assert msg["payload"]["code"] == "room_not_found"

    async def test_viewer_still_gets_immediate_game_state(self):
        """Viewer joining a full room still gets game_state in response."""
        srv = await _setup_server_with_users("alice", "bob", "viewer1")
        ws1, ws2, ws3 = _ws(), _ws(), _ws()
        await _login(srv, ws1, "alice")
        await _login(srv, ws2, "bob")
        await _login(srv, ws3, "viewer1")

        result1 = await srv._route_message(make_create_room(), ws1)
        room_id = decode_message(result1)["payload"]["room_id"]
        await srv._route_message(make_join_room(room_id), ws2)

        # Viewer joins
        result3 = await srv._route_message(make_join_room(room_id), ws3)
        assert isinstance(result3, list)
        types = [decode_message(m)["type"] for m in result3 if decode_message(m)]
        assert "room_joined" in types
        assert "game_state" in types
