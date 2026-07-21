"""
Focused tests for ELO-based matchmaking.

Covers:
- MatchmakingService queue operations
- Rating-based matching (±100 threshold)
- Timeout behavior
- Cancellation and disconnect
- Protocol message format
- Server integration: authenticated-only, duplicate prevention
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from game.server.matchmaking.matchmaking_service import (
    MatchmakingService,
    QueueEntry,
    RATING_THRESHOLD,
    TIMEOUT_SECONDS,
)
from game.server.protocol import (
    decode_message,
    make_match_found,
    make_matchmaking_cancelled,
    make_matchmaking_started,
    make_matchmaking_timeout,
    make_play_request,
    make_cancel_matchmaking,
)
from game.server.websocket_server import GameWebSocketServer
from game.server.auth.user_repository import UserRepository
from game.server.auth.user_service import UserService
from game.server.game_session import GameSession


def _ws():
    """Create a mock websocket."""
    ws = AsyncMock()
    ws.send = AsyncMock()
    return ws


# ─── MatchmakingService unit tests ───────────────────────────────────────────


class TestMatchmakingEnqueue:
    def test_enqueue_returns_true(self):
        svc = MatchmakingService()
        ws = _ws()
        assert svc.enqueue(ws, "alice", 1200) is True
        assert svc.queue_size == 1

    def test_same_player_cannot_enqueue_twice(self):
        svc = MatchmakingService()
        ws = _ws()
        svc.enqueue(ws, "alice", 1200)
        assert svc.enqueue(ws, "alice", 1200) is False
        assert svc.queue_size == 1

    def test_same_username_cannot_enqueue_twice(self):
        svc = MatchmakingService()
        ws1, ws2 = _ws(), _ws()
        svc.enqueue(ws1, "alice", 1200)
        assert svc.enqueue(ws2, "alice", 1300) is False

    def test_different_players_enqueue(self):
        svc = MatchmakingService()
        svc.enqueue(_ws(), "alice", 1200)
        svc.enqueue(_ws(), "bob", 1250)
        assert svc.queue_size == 2


class TestMatchmakingMatching:
    def test_within_100_elo_matched(self):
        svc = MatchmakingService()
        ws1, ws2 = _ws(), _ws()
        svc.enqueue(ws1, "alice", 1200)
        svc.enqueue(ws2, "bob", 1250)

        result = svc.try_match()
        assert result is not None
        assert result.player1.username == "alice"
        assert result.player2.username == "bob"
        assert svc.queue_size == 0

    def test_exactly_100_elo_apart_matched(self):
        svc = MatchmakingService()
        ws1, ws2 = _ws(), _ws()
        svc.enqueue(ws1, "alice", 1200)
        svc.enqueue(ws2, "bob", 1300)

        result = svc.try_match()
        assert result is not None

    def test_more_than_100_elo_not_matched(self):
        svc = MatchmakingService()
        ws1, ws2 = _ws(), _ws()
        svc.enqueue(ws1, "alice", 1200)
        svc.enqueue(ws2, "bob", 1301)

        result = svc.try_match()
        assert result is None
        assert svc.queue_size == 2

    def test_oldest_compatible_selected(self):
        svc = MatchmakingService()
        ws1, ws2, ws3 = _ws(), _ws(), _ws()
        svc.enqueue(ws1, "alice", 1200)
        svc.enqueue(ws2, "bob", 1500)  # too far from alice
        svc.enqueue(ws3, "carol", 1250)  # compatible with alice

        result = svc.try_match()
        assert result is not None
        assert {result.player1.username, result.player2.username} == {"alice", "carol"}
        assert svc.queue_size == 1  # bob remains

    def test_matched_players_removed_from_queue(self):
        svc = MatchmakingService()
        ws1, ws2 = _ws(), _ws()
        svc.enqueue(ws1, "alice", 1200)
        svc.enqueue(ws2, "bob", 1200)
        svc.try_match()

        assert not svc.is_queued(ws1)
        assert not svc.is_queued(ws2)

    def test_no_self_match(self):
        svc = MatchmakingService()
        ws = _ws()
        svc.enqueue(ws, "alice", 1200)

        result = svc.try_match()
        assert result is None


class TestMatchmakingTimeout:
    def test_timeout_after_duration(self):
        svc = MatchmakingService(timeout_seconds=0.0)  # immediate timeout
        ws = _ws()
        svc.enqueue(ws, "alice", 1200)

        timed_out = svc.get_timed_out()
        assert len(timed_out) == 1
        assert timed_out[0].username == "alice"
        assert svc.queue_size == 0

    def test_not_timed_out_within_duration(self):
        svc = MatchmakingService(timeout_seconds=9999)
        ws = _ws()
        svc.enqueue(ws, "alice", 1200)

        timed_out = svc.get_timed_out()
        assert len(timed_out) == 0
        assert svc.queue_size == 1


class TestMatchmakingCancel:
    def test_cancel_removes_player(self):
        svc = MatchmakingService()
        ws = _ws()
        svc.enqueue(ws, "alice", 1200)

        assert svc.cancel(ws) is True
        assert svc.queue_size == 0

    def test_cancel_not_queued_returns_false(self):
        svc = MatchmakingService()
        ws = _ws()
        assert svc.cancel(ws) is False


class TestMatchmakingDisconnect:
    def test_disconnect_removes_player(self):
        svc = MatchmakingService()
        ws = _ws()
        svc.enqueue(ws, "alice", 1200)

        entry = svc.remove_by_websocket(ws)
        assert entry is not None
        assert entry.username == "alice"
        assert svc.queue_size == 0

    def test_disconnect_unknown_returns_none(self):
        svc = MatchmakingService()
        ws = _ws()
        assert svc.remove_by_websocket(ws) is None


# ─── Protocol messages ────────────────────────────────────────────────────────


class TestMatchmakingProtocol:
    def test_play_request_format(self):
        msg = decode_message(make_play_request())
        assert msg["type"] == "play_request"

    def test_cancel_matchmaking_format(self):
        msg = decode_message(make_cancel_matchmaking())
        assert msg["type"] == "cancel_matchmaking"

    def test_matchmaking_started_format(self):
        msg = decode_message(make_matchmaking_started())
        assert msg["type"] == "matchmaking_started"

    def test_match_found_format(self):
        raw = make_match_found("bob", "w", 1200, 1250)
        msg = decode_message(raw)
        assert msg["type"] == "match_found"
        assert msg["payload"]["opponent_username"] == "bob"
        assert msg["payload"]["color"] == "w"
        assert msg["payload"]["own_rating"] == 1200
        assert msg["payload"]["opponent_rating"] == 1250

    def test_matchmaking_timeout_format(self):
        msg = decode_message(make_matchmaking_timeout())
        assert msg["type"] == "matchmaking_timeout"

    def test_matchmaking_cancelled_format(self):
        msg = decode_message(make_matchmaking_cancelled())
        assert msg["type"] == "matchmaking_cancelled"


# ─── Server integration ───────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestServerMatchmakingIntegration:
    async def test_unauthenticated_cannot_play(self):
        srv = GameWebSocketServer()
        ws = _ws()
        srv._connected.add(ws)

        raw = make_play_request()
        result = await srv._route_message(raw, ws)
        msg = decode_message(result)
        assert msg["type"] == "error"
        assert msg["payload"]["code"] == "not_logged_in"

    async def test_authenticated_enters_queue(self):
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        user_svc = UserService(repo)
        user_svc.register("alice", "pass")

        srv = GameWebSocketServer(user_service=user_svc)
        ws = _ws()
        srv._connected.add(ws)

        # Authenticate
        from game.server.protocol import make_login_request
        await srv._route_message(make_login_request("alice", "pass", "login"), ws)

        # Request matchmaking
        result = await srv._route_message(make_play_request(), ws)
        msg = decode_message(result)
        assert msg["type"] == "matchmaking_started"
        assert srv.matchmaking.queue_size == 1

    async def test_duplicate_play_request_rejected(self):
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        user_svc = UserService(repo)
        user_svc.register("alice", "pass")

        srv = GameWebSocketServer(user_service=user_svc)
        ws = _ws()
        srv._connected.add(ws)

        from game.server.protocol import make_login_request
        await srv._route_message(make_login_request("alice", "pass", "login"), ws)
        await srv._route_message(make_play_request(), ws)

        result = await srv._route_message(make_play_request(), ws)
        msg = decode_message(result)
        assert msg["type"] == "error"
        assert msg["payload"]["code"] == "already_queued"

    async def test_cancel_matchmaking(self):
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        user_svc = UserService(repo)
        user_svc.register("alice", "pass")

        srv = GameWebSocketServer(user_service=user_svc)
        ws = _ws()
        srv._connected.add(ws)

        from game.server.protocol import make_login_request
        await srv._route_message(make_login_request("alice", "pass", "login"), ws)
        await srv._route_message(make_play_request(), ws)

        result = await srv._route_message(make_cancel_matchmaking(), ws)
        msg = decode_message(result)
        assert msg["type"] == "matchmaking_cancelled"
        assert srv.matchmaking.queue_size == 0

    async def test_match_found_sends_to_both(self):
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
        await srv._route_message(make_play_request(), ws1)
        await srv._route_message(make_play_request(), ws2)

        # Process matchmaking
        await srv._process_matchmaking()

        # Both should receive match_found
        ws1.send.assert_called()
        ws2.send.assert_called()

        # Parse the match_found messages
        calls1 = [decode_message(c.args[0]) for c in ws1.send.call_args_list
                   if c.args and "match_found" in str(c.args[0])]
        calls2 = [decode_message(c.args[0]) for c in ws2.send.call_args_list
                   if c.args and "match_found" in str(c.args[0])]

        assert len(calls1) == 1
        assert calls1[0]["payload"]["color"] == "w"
        assert calls1[0]["payload"]["opponent_username"] == "bob"

        assert len(calls2) == 1
        assert calls2[0]["payload"]["color"] == "b"
        assert calls2[0]["payload"]["opponent_username"] == "alice"

    async def test_players_over_100_elo_not_matched(self):
        repo = UserRepository(":memory:")
        repo.initialize_schema()
        user_svc = UserService(repo)
        # Register with proper hashing, then manually set ratings
        user_svc.register("pro", "pass")
        user_svc.register("noob", "pass")
        repo.update_rating("pro", 1500)
        repo.update_rating("noob", 1200)

        srv = GameWebSocketServer(user_service=user_svc)
        ws1, ws2 = _ws(), _ws()
        srv._connected.add(ws1)
        srv._connected.add(ws2)

        from game.server.protocol import make_login_request
        await srv._route_message(make_login_request("pro", "pass", "login"), ws1)
        await srv._route_message(make_login_request("noob", "pass", "login"), ws2)
        await srv._route_message(make_play_request(), ws1)
        await srv._route_message(make_play_request(), ws2)

        await srv._process_matchmaking()

        # No match_found should have been sent (300 ELO apart)
        match_calls_1 = [c for c in ws1.send.call_args_list
                         if "match_found" in str(c.args[0])]
        match_calls_2 = [c for c in ws2.send.call_args_list
                         if "match_found" in str(c.args[0])]
        assert len(match_calls_1) == 0
        assert len(match_calls_2) == 0
        assert srv.matchmaking.queue_size == 2
