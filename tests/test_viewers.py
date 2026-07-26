"""
Tests for viewer/spectator support in rooms.

Covers:
- Third+ joiner becomes viewer
- Multiple viewers can join
- Viewer receives game state on join
- Viewer receives move broadcasts
- Viewer receives game-end broadcasts
- Viewer cannot move
- Viewer cannot jump
- Viewer disconnect doesn't stop the game
- Viewer removal updates room membership
- Room cleanup with players and viewers
"""

from unittest.mock import AsyncMock

import pytest

from game.model.constants import MOVE_DURATION_MS
from game.server.game_session_manager import GameSessionManager
from game.server.protocol import (
    decode_message,
    make_create_room,
    make_join_room,
    make_move_request,
    make_jump_request,
)
from game.server.room_manager import RoomManager
from game.server.websocket_server import GameWebSocketServer
from game.server.auth.user_repository import UserRepository
from game.server.auth.user_service import UserService


def _ws():
    ws = AsyncMock()
    ws.send = AsyncMock()
    return ws


# ─── RoomManager viewer unit tests ───────────────────────────────────────────


class TestRoomViewerRoles:
    def test_third_joiner_is_viewer(self):
        mgr = GameSessionManager()
        rm = RoomManager(mgr)
        room = rm.create_room()
        ws1, ws2, ws3 = _ws(), _ws(), _ws()

        rm.join_room(room.room_id, ws1, "a", 1200)
        rm.join_room(room.room_id, ws2, "b", 1200)
        error, role = rm.join_room(room.room_id, ws3, "c", 1200)

        assert error is None
        assert role == "viewer"
        assert room.is_viewer(ws3)
        assert not room.is_player(ws3)

    def test_multiple_viewers(self):
        mgr = GameSessionManager()
        rm = RoomManager(mgr)
        room = rm.create_room()
        ws1, ws2 = _ws(), _ws()
        rm.join_room(room.room_id, ws1, "a", 1200)
        rm.join_room(room.room_id, ws2, "b", 1200)

        viewers = []
        for i in range(5):
            ws = _ws()
            error, role = rm.join_room(room.room_id, ws, f"viewer{i}", 1200)
            assert error is None
            assert role == "viewer"
            viewers.append(ws)

        assert len(room.viewers) == 5
        assert room.member_count == 7  # 2 players + 5 viewers

    def test_get_role(self):
        mgr = GameSessionManager()
        rm = RoomManager(mgr)
        room = rm.create_room()
        ws1, ws2, ws3 = _ws(), _ws(), _ws()

        rm.join_room(room.room_id, ws1, "a", 1200)
        rm.join_room(room.room_id, ws2, "b", 1200)
        rm.join_room(room.room_id, ws3, "c", 1200)

        assert room.get_role(ws1) == "player"
        assert room.get_role(ws2) == "player"
        assert room.get_role(ws3) == "viewer"
        assert room.get_role(_ws()) is None

    def test_viewer_disconnect_keeps_room(self):
        mgr = GameSessionManager()
        rm = RoomManager(mgr)
        room = rm.create_room()
        ws1, ws2, ws3 = _ws(), _ws(), _ws()

        rm.join_room(room.room_id, ws1, "a", 1200)
        rm.join_room(room.room_id, ws2, "b", 1200)
        rm.join_room(room.room_id, ws3, "viewer1", 1200)

        rm.remove_client(ws3)
        assert rm.room_count == 1
        assert ws3 not in room.viewers

    def test_room_deleted_when_all_leave(self):
        mgr = GameSessionManager()
        rm = RoomManager(mgr)
        room = rm.create_room()
        ws1, ws2, ws3 = _ws(), _ws(), _ws()

        rm.join_room(room.room_id, ws1, "a", 1200)
        rm.join_room(room.room_id, ws2, "b", 1200)
        rm.join_room(room.room_id, ws3, "c", 1200)

        rm.remove_client(ws1)
        rm.remove_client(ws2)
        assert rm.room_count == 1  # viewer keeps room alive
        rm.remove_client(ws3)
        assert rm.room_count == 0


# ─── Server integration: viewer behavior ─────────────────────────────────────


@pytest.mark.asyncio
class TestViewerServerIntegration:
    async def _setup_room_with_viewer(self):
        """Helper: create server, register 3 users, create room, add viewer."""
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        user_svc = UserService(repo)
        user_svc.register("alice", "p")
        user_svc.register("bob", "p")
        user_svc.register("carol", "p")

        srv = GameWebSocketServer(user_service=user_svc)
        ws1, ws2, ws3 = _ws(), _ws(), _ws()
        for ws in [ws1, ws2, ws3]:
            srv._connected.add(ws)

        from game.server.protocol import make_login_request
        await srv._route_message(make_login_request("alice", "p", "login"), ws1)
        await srv._route_message(make_login_request("bob", "p", "login"), ws2)
        await srv._route_message(make_login_request("carol", "p", "login"), ws3)

        result1 = await srv._route_message(make_create_room(), ws1)
        room_id = decode_message(result1)["payload"]["room_id"]
        await srv._route_message(make_join_room(room_id), ws2)

        return srv, ws1, ws2, ws3, room_id

    async def test_viewer_receives_game_state_on_join(self):
        srv, ws1, ws2, ws3, room_id = await self._setup_room_with_viewer()

        result = await srv._route_message(make_join_room(room_id), ws3)
        assert isinstance(result, list)
        assert len(result) == 2

        joined_msg = decode_message(result[0])
        assert joined_msg["type"] == "room_joined"
        assert joined_msg["payload"]["role"] == "viewer"
        assert joined_msg["payload"]["color"] is None

        state_msg = decode_message(result[1])
        assert state_msg["type"] == "game_state"
        assert "board" in state_msg["payload"]

    async def test_viewer_receives_move_broadcasts(self):
        srv, ws1, ws2, ws3, room_id = await self._setup_room_with_viewer()
        await srv._route_message(make_join_room(room_id), ws3)

        # Alice (white) makes a move
        await srv._route_message(make_move_request(6, 0, 5, 0), ws1)

        # Drain outbox — broadcasts go to all including viewer
        room = srv.room_manager.get_room(room_id)
        await room.session.drain_outbox()

        # Viewer should have received the move_accepted broadcast
        viewer_sends = [c.args[0] for c in ws3.send.call_args_list if c.args]
        broadcast_types = [decode_message(m)["type"] for m in viewer_sends
                          if decode_message(m) is not None]
        assert "move_accepted" in broadcast_types

    async def test_viewer_cannot_move(self):
        srv, ws1, ws2, ws3, room_id = await self._setup_room_with_viewer()
        await srv._route_message(make_join_room(room_id), ws3)

        result = await srv._route_message(make_move_request(6, 0, 5, 0), ws3)
        msg = decode_message(result)
        assert msg["type"] == "error"
        assert msg["payload"]["code"] == "viewer_action_forbidden"

    async def test_viewer_cannot_jump(self):
        srv, ws1, ws2, ws3, room_id = await self._setup_room_with_viewer()
        await srv._route_message(make_join_room(room_id), ws3)

        result = await srv._route_message(make_jump_request(6, 0), ws3)
        msg = decode_message(result)
        assert msg["type"] == "error"
        assert msg["payload"]["code"] == "viewer_action_forbidden"

    async def test_viewer_disconnect_does_not_stop_game(self):
        srv, ws1, ws2, ws3, room_id = await self._setup_room_with_viewer()
        await srv._route_message(make_join_room(room_id), ws3)

        # Viewer disconnects
        srv._cleanup_client(ws3)

        # Game is still playable
        result = await srv._route_message(make_move_request(6, 0, 5, 0), ws1)
        assert result is None  # Move accepted

        room = srv.room_manager.get_room(room_id)
        assert room is not None
        assert len(room.session.engine.pending_moves) == 1

    async def test_viewer_receives_game_end(self):
        """Viewer receives game_ended broadcast when king is captured."""
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        user_svc = UserService(repo)
        user_svc.register("alice", "p")
        user_svc.register("bob", "p")
        user_svc.register("viewer1", "p")

        # Use a simple board where white can capture black king in one move
        srv = GameWebSocketServer(user_service=user_svc)
        ws1, ws2, ws3 = _ws(), _ws(), _ws()
        for ws in [ws1, ws2, ws3]:
            srv._connected.add(ws)

        from game.server.protocol import make_login_request
        await srv._route_message(make_login_request("alice", "p", "login"), ws1)
        await srv._route_message(make_login_request("bob", "p", "login"), ws2)
        await srv._route_message(make_login_request("viewer1", "p", "login"), ws3)

        result1 = await srv._route_message(make_create_room(), ws1)
        room_id = decode_message(result1)["payload"]["room_id"]
        await srv._route_message(make_join_room(room_id), ws2)
        await srv._route_message(make_join_room(room_id), ws3)

        # Manually set up a quick checkmate board
        from game.model.piece import BLACK_KING, WHITE_ROOK
        room = srv.room_manager.get_room(room_id)
        for r in range(8):
            for c in range(len(room.session.engine.board[0])):
                room.session.engine.board[r][c] = None
        room.session.engine.board[0][0] = BLACK_KING
        room.session.engine.board[3][0] = WHITE_ROOK

        # White rook captures black king (same column, straight up)
        await srv._route_message(make_move_request(3, 0, 0, 0), ws1)
        room.session.tick(3 * MOVE_DURATION_MS + 1)
        await room.session.drain_outbox()

        # Check viewer received game_ended
        viewer_sends = [c.args[0] for c in ws3.send.call_args_list if c.args]
        broadcast_types = [decode_message(m)["type"] for m in viewer_sends
                          if decode_message(m) is not None]
        assert "game_ended" in broadcast_types
