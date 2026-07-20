"""
Focused tests for the username login handshake.

Covers:
- Valid login assigns correct color
- Whitespace-only username rejected
- First player gets White, second gets Black
- Third player gets game_full
- Duplicate active username rejected
- Move request before login rejected
- Disconnect frees username and color
- Ownership checks still work after login
"""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from game.server.game_session import GameSession
from game.server.protocol import (
    decode_message,
    make_login_request,
    make_move_request,
    make_jump_request,
    validate_login_request,
)
from game.model.constants import MOVE_DURATION_MS


def _make_mock_client():
    client = AsyncMock()
    client.send = AsyncMock()
    return client


def _login(session, client, username):
    """Helper: add_client + login_client synchronously."""
    session.add_client(client)
    return session.login_client(client, username)


# ─── Protocol validation ──────────────────────────────────────────────────────


class TestLoginValidation:
    def test_valid_username(self):
        assert validate_login_request({"username": "Alice"}) is None

    def test_missing_username_field(self):
        error = validate_login_request({})
        assert error is not None
        assert "missing" in error

    def test_whitespace_only_rejected(self):
        error = validate_login_request({"username": "   "})
        assert error is not None
        assert "empty" in error

    def test_empty_string_rejected(self):
        error = validate_login_request({"username": ""})
        assert error is not None

    def test_non_string_rejected(self):
        error = validate_login_request({"username": 123})
        assert error is not None
        assert "string" in error


# ─── Login via GameSession ────────────────────────────────────────────────────


class TestLoginAssignment:
    def test_valid_login_returns_login_success_and_game_state(self):
        session = GameSession()
        client = _make_mock_client()
        messages = _login(session, client, "Alice")

        assert len(messages) == 2
        success = decode_message(messages[0])
        assert success["type"] == "login_success"
        assert success["payload"]["username"] == "Alice"
        assert success["payload"]["color"] == "w"

        state = decode_message(messages[1])
        assert state["type"] == "game_state"

    def test_first_player_gets_white(self):
        session = GameSession()
        c1 = _make_mock_client()
        messages = _login(session, c1, "Alice")
        success = decode_message(messages[0])
        assert success["payload"]["color"] == "w"

    def test_second_player_gets_black(self):
        session = GameSession()
        c1 = _make_mock_client()
        c2 = _make_mock_client()
        _login(session, c1, "Alice")
        messages = _login(session, c2, "Bob")
        success = decode_message(messages[0])
        assert success["payload"]["color"] == "b"

    def test_third_player_gets_game_full(self):
        session = GameSession()
        c1, c2, c3 = _make_mock_client(), _make_mock_client(), _make_mock_client()
        _login(session, c1, "Alice")
        _login(session, c2, "Bob")
        messages = _login(session, c3, "Charlie")

        assert len(messages) == 1
        error = decode_message(messages[0])
        assert error["type"] == "error"
        assert error["payload"]["code"] == "game_full"

    def test_duplicate_username_rejected(self):
        session = GameSession()
        c1 = _make_mock_client()
        c2 = _make_mock_client()
        _login(session, c1, "Alice")
        messages = _login(session, c2, "Alice")

        assert len(messages) == 1
        error = decode_message(messages[0])
        assert error["type"] == "error"
        assert error["payload"]["code"] == "username_taken"

    def test_duplicate_username_case_sensitive(self):
        """Usernames are case-sensitive: 'Alice' and 'alice' are different."""
        session = GameSession()
        c1 = _make_mock_client()
        c2 = _make_mock_client()
        _login(session, c1, "Alice")
        messages = _login(session, c2, "alice")
        success = decode_message(messages[0])
        assert success["type"] == "login_success"


# ─── Disconnect frees slot ────────────────────────────────────────────────────


class TestDisconnectFreesSlot:
    def test_disconnect_frees_color_and_username(self):
        session = GameSession()
        c1 = _make_mock_client()
        c2 = _make_mock_client()
        _login(session, c1, "Alice")
        _login(session, c2, "Bob")

        session.remove_client(c1)

        # New client can use the freed White slot
        c3 = _make_mock_client()
        messages = _login(session, c3, "Charlie")
        success = decode_message(messages[0])
        assert success["payload"]["color"] == "w"

    def test_disconnect_frees_username_for_reuse(self):
        session = GameSession()
        c1 = _make_mock_client()
        _login(session, c1, "Alice")
        session.remove_client(c1)

        # Same username can be reused
        c2 = _make_mock_client()
        messages = _login(session, c2, "Alice")
        success = decode_message(messages[0])
        assert success["type"] == "login_success"


# ─── Move/jump before login rejected ─────────────────────────────────────────


@pytest.mark.asyncio
class TestNotLoggedIn:
    async def test_move_request_before_login_rejected(self):
        session = GameSession()
        client = _make_mock_client()
        session.add_client(client)

        raw = make_move_request(6, 0, 5, 0)
        result = await session.handle_message(raw, sender=client)
        msg = decode_message(result)
        assert msg["type"] == "error"
        assert msg["payload"]["code"] == "not_logged_in"

    async def test_jump_request_before_login_rejected(self):
        session = GameSession()
        client = _make_mock_client()
        session.add_client(client)

        raw = make_jump_request(6, 0)
        result = await session.handle_message(raw, sender=client)
        msg = decode_message(result)
        assert msg["type"] == "error"
        assert msg["payload"]["code"] == "not_logged_in"


# ─── Login via handle_message ─────────────────────────────────────────────────


@pytest.mark.asyncio
class TestLoginViaHandleMessage:
    async def test_login_request_message(self):
        session = GameSession()
        client = _make_mock_client()
        session.add_client(client)

        raw = make_login_request("Alice")
        result = await session.handle_message(raw, sender=client)

        # Should return list [login_success, game_state]
        assert isinstance(result, list)
        assert len(result) == 2
        success = decode_message(result[0])
        assert success["type"] == "login_success"
        assert success["payload"]["color"] == "w"

    async def test_whitespace_login_rejected_via_message(self):
        session = GameSession()
        client = _make_mock_client()
        session.add_client(client)

        raw = make_login_request("   ")
        result = await session.handle_message(raw, sender=client)
        msg = decode_message(result)
        assert msg["type"] == "error"
        assert msg["payload"]["code"] == "validation_error"

    async def test_game_full_via_login_message(self):
        session = GameSession()
        c1, c2, c3 = _make_mock_client(), _make_mock_client(), _make_mock_client()
        session.add_client(c1)
        session.add_client(c2)
        session.add_client(c3)

        await session.handle_message(make_login_request("Alice"), sender=c1)
        await session.handle_message(make_login_request("Bob"), sender=c2)
        result = await session.handle_message(make_login_request("Charlie"), sender=c3)

        msg = decode_message(result)
        assert msg["type"] == "error"
        assert msg["payload"]["code"] == "game_full"


# ─── Ownership still works after login ────────────────────────────────────────


@pytest.mark.asyncio
class TestOwnershipAfterLogin:
    async def test_white_can_move_own_piece(self):
        session = GameSession()
        white = _make_mock_client()
        session.add_client(white)
        await session.handle_message(make_login_request("Alice"), sender=white)

        raw = make_move_request(6, 0, 5, 0)  # wP forward
        result = await session.handle_message(raw, sender=white)
        assert result is None  # Accepted (broadcast queued)

    async def test_white_cannot_move_black_piece(self):
        session = GameSession()
        white = _make_mock_client()
        session.add_client(white)
        await session.handle_message(make_login_request("Alice"), sender=white)

        raw = make_move_request(1, 0, 2, 0)  # bP
        result = await session.handle_message(raw, sender=white)
        msg = decode_message(result)
        assert msg["type"] == "move_rejected"
        assert msg["payload"]["reason"] == "not_your_piece"

    async def test_black_can_move_own_piece(self):
        session = GameSession()
        white = _make_mock_client()
        black = _make_mock_client()
        session.add_client(white)
        session.add_client(black)
        await session.handle_message(make_login_request("Alice"), sender=white)
        await session.handle_message(make_login_request("Bob"), sender=black)

        raw = make_move_request(1, 0, 2, 0)  # bP forward
        result = await session.handle_message(raw, sender=black)
        assert result is None  # Accepted

    async def test_black_cannot_move_white_piece(self):
        session = GameSession()
        white = _make_mock_client()
        black = _make_mock_client()
        session.add_client(white)
        session.add_client(black)
        await session.handle_message(make_login_request("Alice"), sender=white)
        await session.handle_message(make_login_request("Bob"), sender=black)

        raw = make_move_request(6, 0, 5, 0)  # wP
        result = await session.handle_message(raw, sender=black)
        msg = decode_message(result)
        assert msg["payload"]["reason"] == "not_your_piece"

    async def test_jump_ownership_after_login(self):
        session = GameSession()
        white = _make_mock_client()
        session.add_client(white)
        await session.handle_message(make_login_request("Alice"), sender=white)

        # White can jump own piece
        raw = make_jump_request(6, 0)  # wP
        result = await session.handle_message(raw, sender=white)
        assert result is None  # Accepted

    async def test_jump_opponent_piece_rejected(self):
        session = GameSession()
        white = _make_mock_client()
        session.add_client(white)
        await session.handle_message(make_login_request("Alice"), sender=white)

        raw = make_jump_request(0, 0)  # bR
        result = await session.handle_message(raw, sender=white)
        msg = decode_message(result)
        assert msg["type"] == "move_rejected"
        assert msg["payload"]["reason"] == "not_your_piece"
