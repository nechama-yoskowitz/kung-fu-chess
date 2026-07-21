"""
Tests for Rooms feature.

Covers:
- RoomManager: create, join, invalid room, full room, unique IDs, cleanup
- Server integration: protocol routing, gameplay inside rooms
- Regression: matchmaking still works alongside rooms
"""

from unittest.mock import AsyncMock

import pytest

from game.server.game_session_manager import GameSessionManager
from game.server.protocol import (
    decode_message,
    make_create_room,
    make_join_room,
    make_move_request,
)
from game.server.room_manager import RoomManager, Room
from game.server.websocket_server import GameWebSocketServer
from game.server.auth.user_repository import UserRepository
from game.server.auth.user_service import UserService


def _ws():
    ws = AsyncMock()
    ws.send = AsyncMock()
    return ws


# ─── RoomManager unit tests ──────────────────────────────────────────────────


class TestRoomManagerCreate:
    def test_create_room(self):
        mgr = GameSessionManager()
        rm = RoomManager(mgr)
        room = rm.create_room()
        assert room is not None
        assert room.room_id
        assert rm.room_count == 1

    def test_unique_room_ids(self):
        mgr = GameSessionManager()
        rm = RoomManager(mgr)
        r1 = rm.create_room()
        r2 = rm.create_room()
        assert r1.room_id != r2.room_id

    def test_room_has_session(self):
        mgr = GameSessionManager()
        rm = RoomManager(mgr)
        room = rm.create_room()
        assert room.session is not None


class TestRoomManagerJoin:
    def test_join_room_success(self):
        mgr = GameSessionManager()
        rm = RoomManager(mgr)
        room = rm.create_room()
        ws = _ws()

        error = rm.join_room(room.room_id, ws, "alice", 1200)
        assert error is None
        assert ws in room.players

    def test_join_assigns_color(self):
        mgr = GameSessionManager()
        rm = RoomManager(mgr)
        room = rm.create_room()
        ws = _ws()

        rm.join_room(room.room_id, ws, "alice", 1200)
        color = room.session.get_player_color(ws)
        assert color == "w"  # first player is White

    def test_second_player_gets_black(self):
        mgr = GameSessionManager()
        rm = RoomManager(mgr)
        room = rm.create_room()
        ws1, ws2 = _ws(), _ws()

        rm.join_room(room.room_id, ws1, "alice", 1200)
        rm.join_room(room.room_id, ws2, "bob", 1200)
        assert room.session.get_player_color(ws2) == "b"

    def test_join_nonexistent_room(self):
        mgr = GameSessionManager()
        rm = RoomManager(mgr)
        ws = _ws()

        error = rm.join_room("nonexistent", ws, "alice", 1200)
        assert error == "room_not_found"

    def test_join_full_room(self):
        mgr = GameSessionManager()
        rm = RoomManager(mgr)
        room = rm.create_room()
        ws1, ws2, ws3 = _ws(), _ws(), _ws()

        rm.join_room(room.room_id, ws1, "alice", 1200)
        rm.join_room(room.room_id, ws2, "bob", 1200)
        error = rm.join_room(room.room_id, ws3, "carol", 1200)
        assert error == "room_full"


class TestRoomManagerCleanup:
    def test_remove_room(self):
        mgr = GameSessionManager()
        rm = RoomManager(mgr)
        room = rm.create_room()
        rm.remove_room(room.room_id)
        assert rm.room_count == 0

    def test_remove_player_cleans_empty_room(self):
        mgr = GameSessionManager()
        rm = RoomManager(mgr)
        room = rm.create_room()
        ws = _ws()
        rm.join_room(room.room_id, ws, "alice", 1200)

        rm.remove_player(ws)
        assert rm.room_count == 0

    def test_remove_one_of_two_players_keeps_room(self):
        mgr = GameSessionManager()
        rm = RoomManager(mgr)
        room = rm.create_room()
        ws1, ws2 = _ws(), _ws()
        rm.join_room(room.room_id, ws1, "alice", 1200)
        rm.join_room(room.room_id, ws2, "bob", 1200)

        rm.remove_player(ws1)
        assert rm.room_count == 1
        assert ws2 in room.players


# ─── Server integration ───────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestServerRoomIntegration:
    async def test_create_room_unauthenticated_rejected(self):
        srv = GameWebSocketServer()
        ws = _ws()
        srv._connected.add(ws)

        result = await srv._route_message(make_create_room(), ws)
        msg = decode_message(result)
        assert msg["type"] == "error"
        assert msg["payload"]["code"] == "not_logged_in"

    async def test_create_room_success(self):
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        user_svc = UserService(repo)
        user_svc.register("alice", "pass")

        srv = GameWebSocketServer(user_service=user_svc)
        ws = _ws()
        srv._connected.add(ws)

        from game.server.protocol import make_login_request
        await srv._route_message(make_login_request("alice", "pass", "login"), ws)

        result = await srv._route_message(make_create_room(), ws)
        msg = decode_message(result)
        assert msg["type"] == "room_created"
        assert "room_id" in msg["payload"]
        assert srv.room_manager.room_count == 1

    async def test_join_room_success(self):
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        user_svc = UserService(repo)
        user_svc.register("alice", "pass")
        user_svc.register("bob", "pass")

        srv = GameWebSocketServer(user_service=user_svc)
        ws1, ws2 = _ws(), _ws()
        srv._connected.add(ws1)
        srv._connected.add(ws2)

        from game.server.protocol import make_login_request
        await srv._route_message(make_login_request("alice", "pass", "login"), ws1)
        await srv._route_message(make_login_request("bob", "pass", "login"), ws2)

        # Alice creates room
        result1 = await srv._route_message(make_create_room(), ws1)
        room_id = decode_message(result1)["payload"]["room_id"]

        # Bob joins
        result2 = await srv._route_message(make_join_room(room_id), ws2)
        msg = decode_message(result2)
        assert msg["type"] == "room_joined"
        assert msg["payload"]["room_id"] == room_id
        assert msg["payload"]["color"] == "b"

    async def test_join_invalid_room(self):
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        user_svc = UserService(repo)
        user_svc.register("bob", "pass")

        srv = GameWebSocketServer(user_service=user_svc)
        ws = _ws()
        srv._connected.add(ws)

        from game.server.protocol import make_login_request
        await srv._route_message(make_login_request("bob", "pass", "login"), ws)

        result = await srv._route_message(make_join_room("badid"), ws)
        msg = decode_message(result)
        assert msg["type"] == "error"
        assert msg["payload"]["code"] == "room_not_found"

    async def test_join_full_room(self):
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        user_svc = UserService(repo)
        user_svc.register("a", "p")
        user_svc.register("b", "p")
        user_svc.register("c", "p")

        srv = GameWebSocketServer(user_service=user_svc)
        ws1, ws2, ws3 = _ws(), _ws(), _ws()
        for ws in [ws1, ws2, ws3]:
            srv._connected.add(ws)

        from game.server.protocol import make_login_request
        await srv._route_message(make_login_request("a", "p", "login"), ws1)
        await srv._route_message(make_login_request("b", "p", "login"), ws2)
        await srv._route_message(make_login_request("c", "p", "login"), ws3)

        result1 = await srv._route_message(make_create_room(), ws1)
        room_id = decode_message(result1)["payload"]["room_id"]
        await srv._route_message(make_join_room(room_id), ws2)

        result3 = await srv._route_message(make_join_room(room_id), ws3)
        msg = decode_message(result3)
        assert msg["type"] == "error"
        assert msg["payload"]["code"] == "room_full"

    async def test_gameplay_inside_room(self):
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        user_svc = UserService(repo)
        user_svc.register("alice", "pass")
        user_svc.register("bob", "pass")

        srv = GameWebSocketServer(user_service=user_svc)
        ws1, ws2 = _ws(), _ws()
        srv._connected.add(ws1)
        srv._connected.add(ws2)

        from game.server.protocol import make_login_request
        await srv._route_message(make_login_request("alice", "pass", "login"), ws1)
        await srv._route_message(make_login_request("bob", "pass", "login"), ws2)

        result1 = await srv._route_message(make_create_room(), ws1)
        room_id = decode_message(result1)["payload"]["room_id"]
        await srv._route_message(make_join_room(room_id), ws2)

        # Alice (white) moves a pawn
        raw = make_move_request(6, 0, 5, 0)
        result = await srv._route_message(raw, ws1)
        assert result is None  # Accepted, broadcast queued

        room = srv.room_manager.get_room(room_id)
        assert len(room.session.engine.pending_moves) == 1

    async def test_matchmaking_still_works_alongside_rooms(self):
        """Rooms and matchmaking coexist."""
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        user_svc = UserService(repo)
        user_svc.register("alice", "pass")
        user_svc.register("bob", "pass")

        srv = GameWebSocketServer(user_service=user_svc)
        ws1, ws2 = _ws(), _ws()
        srv._connected.add(ws1)
        srv._connected.add(ws2)

        from game.server.protocol import make_login_request, make_play_request
        await srv._route_message(make_login_request("alice", "pass", "login"), ws1)
        await srv._route_message(make_login_request("bob", "pass", "login"), ws2)

        # Bob creates a room (separate feature)
        await srv._route_message(make_create_room(), ws2)
        assert srv.room_manager.room_count == 1

        # Alice enters matchmaking (separate feature)
        result = await srv._route_message(make_play_request(), ws1)
        msg = decode_message(result)
        assert msg["type"] == "matchmaking_started"
        assert srv.matchmaking.queue_size == 1
