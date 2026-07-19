"""
Tests for GameSession — server-side adapter between WebSocket and GameEngine.

All sends are properly awaited. No asyncio warnings.
"""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from game.server.game_session import GameSession
from game.server.protocol import (
    decode_message,
    make_jump_request,
    make_move_request,
)
from game.model.constants import MOVE_DURATION_MS


def _make_mock_client():
    """Mock WebSocket client with async send."""
    client = AsyncMock()
    client.send = AsyncMock()
    return client


# ─── Initial state ────────────────────────────────────────────────────────────


class TestNewClientReceivesGameState:
    def test_initial_messages_include_game_state(self):
        session = GameSession()
        client = _make_mock_client()
        messages = session.add_client(client)

        # Should have player_assigned + game_state
        assert len(messages) == 2
        state_msg = decode_message(messages[1])
        assert state_msg["type"] == "game_state"
        assert len(state_msg["payload"]["board"]) == 8

    def test_initial_scores_zero(self):
        session = GameSession()
        client = _make_mock_client()
        messages = session.add_client(client)
        state_msg = decode_message(messages[1])
        assert state_msg["payload"]["white_score"] == 0


# ─── Player assignment ────────────────────────────────────────────────────────


class TestPlayerAssignment:
    def test_first_client_assigned_white(self):
        session = GameSession()
        client = _make_mock_client()
        messages = session.add_client(client)
        assigned = decode_message(messages[0])
        assert assigned["type"] == "player_assigned"
        assert assigned["payload"]["color"] == "w"

    def test_second_client_assigned_black(self):
        session = GameSession()
        c1 = _make_mock_client()
        c2 = _make_mock_client()
        session.add_client(c1)
        messages = session.add_client(c2)
        assigned = decode_message(messages[0])
        assert assigned["payload"]["color"] == "b"

    def test_third_client_rejected(self):
        session = GameSession()
        c1, c2, c3 = _make_mock_client(), _make_mock_client(), _make_mock_client()
        session.add_client(c1)
        session.add_client(c2)
        messages = session.add_client(c3)

        # Should get a game_full error
        assert len(messages) == 1
        error = decode_message(messages[0])
        assert error["type"] == "error"
        assert "full" in error["payload"]["message"]
        assert c3 not in session._clients

    def test_disconnect_frees_color(self):
        session = GameSession()
        c1 = _make_mock_client()
        c2 = _make_mock_client()
        session.add_client(c1)
        session.add_client(c2)

        session.remove_client(c1)

        # New client gets the freed white slot
        c3 = _make_mock_client()
        messages = session.add_client(c3)
        assigned = decode_message(messages[0])
        assert assigned["payload"]["color"] == "w"


# ─── Ownership validation ─────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestOwnership:
    async def test_white_can_move_white_piece(self):
        session = GameSession()
        white = _make_mock_client()
        session.add_client(white)

        raw = make_move_request(6, 0, 5, 0)  # wP forward
        result = await session.handle_message(raw, sender=white)
        # Accepted → no direct response (broadcast queued)
        assert result is None

    async def test_white_cannot_move_black_piece(self):
        session = GameSession()
        white = _make_mock_client()
        session.add_client(white)

        raw = make_move_request(1, 0, 2, 0)  # bP — not white's piece
        result = await session.handle_message(raw, sender=white)
        msg = decode_message(result)
        assert msg["type"] == "move_rejected"
        assert msg["payload"]["reason"] == "not_your_piece"

    async def test_black_can_move_black_piece(self):
        session = GameSession()
        white = _make_mock_client()
        black = _make_mock_client()
        session.add_client(white)
        session.add_client(black)

        raw = make_move_request(1, 0, 2, 0)  # bP forward
        result = await session.handle_message(raw, sender=black)
        assert result is None  # Accepted

    async def test_black_cannot_move_white_piece(self):
        session = GameSession()
        white = _make_mock_client()
        black = _make_mock_client()
        session.add_client(white)
        session.add_client(black)

        raw = make_move_request(6, 0, 5, 0)  # wP — not black's piece
        result = await session.handle_message(raw, sender=black)
        msg = decode_message(result)
        assert msg["payload"]["reason"] == "not_your_piece"

    async def test_ownership_rejection_does_not_reach_engine(self):
        session = GameSession()
        white = _make_mock_client()
        session.add_client(white)

        # Try to move opponent's piece
        raw = make_move_request(1, 0, 2, 0)
        await session.handle_message(raw, sender=white)

        # Engine should have no pending moves
        assert len(session.engine.pending_moves) == 0

    async def test_ownership_applies_to_jump(self):
        session = GameSession()
        white = _make_mock_client()
        session.add_client(white)

        # Try to jump black piece
        raw = make_jump_request(0, 0)  # bR
        result = await session.handle_message(raw, sender=white)
        msg = decode_message(result)
        assert msg["type"] == "move_rejected"
        assert msg["payload"]["reason"] == "not_your_piece"


# ─── Move delegation ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestMoveDelegation:
    async def test_accepted_move_queues_broadcast(self):
        session = GameSession()
        white = _make_mock_client()
        session.add_client(white)

        raw = make_move_request(6, 4, 4, 4)  # wP two steps
        await session.handle_message(raw, sender=white)

        pending = session.get_pending_broadcasts()
        assert len(pending) >= 1
        msg = decode_message(pending[0])
        assert msg["type"] == "move_accepted"

    async def test_rejected_move_returns_reason(self):
        session = GameSession()
        white = _make_mock_client()
        session.add_client(white)

        raw = make_move_request(3, 3, 4, 4)  # empty cell
        result = await session.handle_message(raw, sender=white)
        msg = decode_message(result)
        assert msg["type"] == "move_rejected"


# ─── Event broadcasts ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestEventBroadcasts:
    async def test_move_resolved_broadcast(self):
        session = GameSession()
        white = _make_mock_client()
        session.add_client(white)

        session.engine.request_move(6, 0, 5, 0)
        session.tick(MOVE_DURATION_MS + 1)

        pending = session.get_pending_broadcasts()
        resolved = [decode_message(m) for m in pending if "move_resolved" in m]
        assert len(resolved) >= 1

    async def test_game_ended_broadcast(self):
        board = [["wR", ".", ".", "bK"]]
        session = GameSession(board=board)
        white = _make_mock_client()
        session.add_client(white)

        session.engine.request_move(0, 0, 0, 3)
        session.tick(3 * MOVE_DURATION_MS + 1)

        pending = session.get_pending_broadcasts()
        ended = [decode_message(m) for m in pending if "game_ended" in m]
        assert len(ended) >= 1

    async def test_drain_outbox_sends_to_clients(self):
        session = GameSession()
        white = _make_mock_client()
        session.add_client(white)

        session.engine.request_move(6, 0, 5, 0)
        session.tick(MOVE_DURATION_MS + 1)

        await session.drain_outbox()
        assert white.send.called


# ─── Disconnect handling ──────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestDisconnect:
    async def test_remove_client(self):
        session = GameSession()
        client = _make_mock_client()
        session.add_client(client)
        session.remove_client(client)
        assert session.client_count == 0

    async def test_broken_client_removed_during_broadcast(self):
        session = GameSession()
        good = _make_mock_client()
        bad = _make_mock_client()
        bad.send = AsyncMock(side_effect=Exception("disconnected"))

        session.add_client(good)
        session.add_client(bad)

        # Queue a broadcast
        session._queue_broadcast("test message")
        await session.drain_outbox()

        # Bad client removed, good client received
        assert bad not in session._clients
        good.send.assert_called_with("test message")


# ─── Invalid payloads ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestInvalidPayload:
    async def test_missing_fields(self):
        session = GameSession()
        white = _make_mock_client()
        session.add_client(white)

        raw = json.dumps({
            "version": 1, "type": "move_request",
            "payload": {"from_row": 6, "from_col": 0, "to_row": 5},
        })
        result = await session.handle_message(raw, sender=white)
        msg = decode_message(result)
        assert msg["type"] == "error"


# ─── Legacy ping ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestLegacyPing:
    async def test_ping_pong(self):
        session = GameSession()
        white = _make_mock_client()
        session.add_client(white)
        result = await session.handle_message("ping", sender=white)
        assert result == "pong"
