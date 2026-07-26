"""
Tests for GameSessionManager — multi-session support.

Covers:
- Multiple sessions exist simultaneously
- Players routed to the correct session
- Moves from one game don't affect another
- Finished sessions can be removed
- Players can play again after finishing
- Matchmaking creates a fresh session
"""

from unittest.mock import AsyncMock

import pytest

from game.server.game_session import GameSession
from game.server.game_session_manager import GameSessionManager
from game.server.matchmaking.matchmaking_service import MatchmakingService
from game.server.protocol import decode_message, make_move_request
from game.server.websocket_server import GameWebSocketServer
from game.server.auth.user_repository import UserRepository
from game.server.auth.user_service import UserService
from game.model.constants import MOVE_DURATION_MS


def _ws():
    ws = AsyncMock()
    ws.send = AsyncMock()
    return ws


class TestGameSessionManagerBasics:
    def test_create_session(self):
        mgr = GameSessionManager()
        session = mgr.create_session()
        assert session is not None
        assert mgr.active_session_count == 1

    def test_multiple_sessions(self):
        mgr = GameSessionManager()
        s1 = mgr.create_session()
        s2 = mgr.create_session()
        assert mgr.active_session_count == 2
        assert s1 is not s2

    def test_get_session_by_id(self):
        mgr = GameSessionManager()
        session = mgr.create_session()
        sid = mgr.get_session_id(session)
        assert mgr.get_session_by_id(sid) is session

    def test_assign_client_to_session(self):
        mgr = GameSessionManager()
        session = mgr.create_session()
        ws = _ws()
        mgr.assign_client_to_session(ws, session)
        assert mgr.get_session_for_client(ws) is session

    def test_remove_client(self):
        mgr = GameSessionManager()
        session = mgr.create_session()
        ws = _ws()
        mgr.assign_client_to_session(ws, session)
        mgr.remove_client(ws)
        assert mgr.get_session_for_client(ws) is None

    def test_remove_session(self):
        mgr = GameSessionManager()
        session = mgr.create_session()
        ws = _ws()
        mgr.assign_client_to_session(ws, session)
        mgr.remove_session(session)
        assert mgr.active_session_count == 0
        assert mgr.get_session_for_client(ws) is None

    def test_is_client_in_session(self):
        mgr = GameSessionManager()
        session = mgr.create_session()
        ws = _ws()
        assert mgr.is_client_in_session(ws) is False
        mgr.assign_client_to_session(ws, session)
        assert mgr.is_client_in_session(ws) is True


class TestMultipleSimultaneousGames:
    def test_two_games_independent_boards(self):
        mgr = GameSessionManager()
        s1 = mgr.create_session()
        s2 = mgr.create_session()

        # They have separate engines
        assert s1.engine is not s2.engine
        assert s1.engine.board is not s2.engine.board

    def test_moves_in_one_game_dont_affect_another(self):
        mgr = GameSessionManager()
        s1 = mgr.create_session()
        s2 = mgr.create_session()

        ws1 = _ws()
        s1.add_client(ws1)
        s1.login_client(ws1, "alice")

        ws2 = _ws()
        s2.add_client(ws2)
        s2.login_client(ws2, "bob")

        # Move in session 1
        s1.engine.request_move(6, 0, 5, 0)  # white pawn
        s1.tick(MOVE_DURATION_MS + 1)

        # Session 2 board is unchanged
        assert s2.engine.board[6][0] == "wP"
        assert s2.engine.board[5][0] is None

    def test_players_routed_to_correct_session(self):
        mgr = GameSessionManager()
        s1 = mgr.create_session()
        s2 = mgr.create_session()

        ws_a = _ws()
        ws_b = _ws()
        mgr.assign_client_to_session(ws_a, s1)
        mgr.assign_client_to_session(ws_b, s2)

        assert mgr.get_session_for_client(ws_a) is s1
        assert mgr.get_session_for_client(ws_b) is s2

    def test_finished_session_removed(self):
        mgr = GameSessionManager()
        session = mgr.create_session()
        ws = _ws()
        mgr.assign_client_to_session(ws, session)

        mgr.remove_session(session)
        assert mgr.active_session_count == 0
        assert not mgr.is_client_in_session(ws)

    def test_player_can_play_again_after_session_removed(self):
        mgr = GameSessionManager()
        s1 = mgr.create_session()
        ws = _ws()
        mgr.assign_client_to_session(ws, s1)

        mgr.remove_session(s1)

        # Player can be assigned to a new session
        s2 = mgr.create_session()
        mgr.assign_client_to_session(ws, s2)
        assert mgr.get_session_for_client(ws) is s2


@pytest.mark.asyncio
class TestMatchmakingCreatesSession:
    async def test_match_creates_new_session(self):
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
        await srv._route_message(make_play_request(), ws1)
        await srv._route_message(make_play_request(), ws2)

        assert srv.session_manager.active_session_count == 0

        await srv._process_matchmaking()

        # A new session should have been created
        assert srv.session_manager.active_session_count == 1

    async def test_matched_players_assigned_to_same_session(self):
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
        await srv._route_message(make_play_request(), ws1)
        await srv._route_message(make_play_request(), ws2)

        await srv._process_matchmaking()

        # Both in the same session
        s1 = srv.session_manager.get_session_for_client(ws1)
        s2 = srv.session_manager.get_session_for_client(ws2)
        assert s1 is not None
        assert s1 is s2

    async def test_two_matches_create_two_sessions(self):
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        user_svc = UserService(repo)
        user_svc.register("a", "p")
        user_svc.register("b", "p")
        user_svc.register("c", "p")
        user_svc.register("d", "p")

        srv = GameWebSocketServer(user_service=user_svc)
        ws_a, ws_b, ws_c, ws_d = _ws(), _ws(), _ws(), _ws()
        for ws in [ws_a, ws_b, ws_c, ws_d]:
            srv._connected.add(ws)

        from game.server.protocol import make_login_request, make_play_request
        await srv._route_message(make_login_request("a", "p", "login"), ws_a)
        await srv._route_message(make_login_request("b", "p", "login"), ws_b)
        await srv._route_message(make_login_request("c", "p", "login"), ws_c)
        await srv._route_message(make_login_request("d", "p", "login"), ws_d)

        await srv._route_message(make_play_request(), ws_a)
        await srv._route_message(make_play_request(), ws_b)
        await srv._route_message(make_play_request(), ws_c)
        await srv._route_message(make_play_request(), ws_d)

        # Process twice to get both matches
        await srv._process_matchmaking()
        await srv._process_matchmaking()

        assert srv.session_manager.active_session_count == 2

        # a and b in one session, c and d in another
        s_ab = srv.session_manager.get_session_for_client(ws_a)
        s_cd = srv.session_manager.get_session_for_client(ws_c)
        assert s_ab is not None
        assert s_cd is not None
        assert s_ab is not s_cd

    async def test_gameplay_routes_to_correct_session(self):
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
        await srv._route_message(make_play_request(), ws1)
        await srv._route_message(make_play_request(), ws2)

        await srv._process_matchmaking()

        session = srv.session_manager.get_session_for_client(ws1)
        assert session is not None

        # Alice (white) can move a white pawn
        raw = make_move_request(6, 0, 5, 0)
        result = await srv._route_message(raw, ws1)
        # Accepted — no error returned, broadcast queued
        assert result is None
        assert len(session.engine.pending_moves) == 1
