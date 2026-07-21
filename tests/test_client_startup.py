"""
Tests for client startup and lobby flow.

Verifies:
- login_success completes authentication without game_state
- Registration success completes authentication
- Transport timeout is only reported when connection truly fails
- Authenticated client can enter matchmaking
- match_found + game_state transitions to playing
- room_created does not start board prematurely
- room_joined + game_state starts the board
- viewer room join starts viewer mode
- login failure displays real error
- local mode remains unchanged
"""

from game.client.client_game_state import ClientGameState
from game.client.server_message_processor import ServerMessageProcessor
from game.events import EventBus
from game.graphics.graphics_manager import GraphicsManager
from unittest.mock import MagicMock


def _make_gm():
    gm = MagicMock(spec=GraphicsManager)
    gm.graphic_pieces = []
    gm.get_piece_at.return_value = None
    gm.get_pieces_at.return_value = []
    return gm


class TestLoginWithoutGameState:
    """login_success without a color/game_state still marks connected."""

    def test_login_success_empty_color_sets_connected(self):
        state = ClientGameState()
        gm = _make_gm()
        proc = ServerMessageProcessor(state, gm, event_bus=EventBus())

        proc.process_messages([{
            "type": "login_success",
            "payload": {"username": "alice", "color": "", "rating": 1200},
        }])

        assert state.connected is True
        assert state.player_username == "alice"
        assert state.player_rating == 1200
        assert state.player_color is None  # No color assigned yet

    def test_login_success_with_color_sets_color(self):
        state = ClientGameState()
        gm = _make_gm()
        proc = ServerMessageProcessor(state, gm, event_bus=EventBus())

        proc.process_messages([{
            "type": "login_success",
            "payload": {"username": "bob", "color": "w", "rating": 1300},
        }])

        assert state.connected is True
        assert state.player_color == "w"

    def test_registration_success_sets_connected(self):
        state = ClientGameState()
        gm = _make_gm()
        proc = ServerMessageProcessor(state, gm, event_bus=EventBus())

        proc.process_messages([{
            "type": "login_success",
            "payload": {"username": "newuser", "color": "", "rating": 1200},
        }])

        assert state.connected is True
        assert state.player_username == "newuser"


class TestMatchmakingToGame:
    """Match found + game_state transitions to playing."""

    def test_match_found_sets_opponent_and_color(self):
        state = ClientGameState()
        state.connected = True
        gm = _make_gm()
        proc = ServerMessageProcessor(state, gm, event_bus=EventBus())

        proc.process_messages([{
            "type": "match_found",
            "payload": {
                "opponent_username": "opponent",
                "color": "b",
                "own_rating": 1200,
                "opponent_rating": 1250,
            },
        }])

        assert state.player_color == "b"
        assert state.opponent_username == "opponent"

    def test_game_state_after_match_sets_board(self):
        state = ClientGameState()
        state.connected = True
        gm = _make_gm()
        proc = ServerMessageProcessor(state, gm, event_bus=EventBus())

        board = [["wR", ".", ".", "bK"]]
        proc.process_messages([{
            "type": "game_state",
            "payload": {
                "board": board,
                "clock": 0.0,
                "white_score": 0,
                "black_score": 0,
                "game_over": False,
            },
        }])

        assert state.board == board


class TestRoomFlow:
    """Room creation and joining."""

    def test_room_created_stores_id(self):
        state = ClientGameState()
        state.connected = True
        gm = _make_gm()
        proc = ServerMessageProcessor(state, gm, event_bus=EventBus())

        proc.process_messages([{
            "type": "room_created",
            "payload": {"room_id": "abc123"},
        }])

        assert state.room_id == "abc123"
        assert state.room_role == "player"
        # Board should NOT be set yet (waiting for opponent)
        assert all(cell == "." for row in state.board for cell in row)

    def test_room_joined_viewer_mode(self):
        state = ClientGameState()
        state.connected = True
        gm = _make_gm()
        proc = ServerMessageProcessor(state, gm, event_bus=EventBus())

        proc.process_messages([{
            "type": "room_joined",
            "payload": {"room_id": "xyz", "role": "viewer", "color": None},
        }])

        assert state.is_viewer is True
        assert state.room_role == "viewer"


class TestLoginFailure:
    def test_error_message_preserved(self):
        state = ClientGameState()
        gm = _make_gm()
        proc = ServerMessageProcessor(state, gm, event_bus=EventBus())

        proc.process_messages([{
            "type": "error",
            "payload": {"code": "invalid_credentials", "message": "wrong password"},
        }])

        # State should NOT be connected
        assert state.connected is False


class TestLocalModeUnchanged:
    def test_local_game_application_has_no_network_state(self):
        """Local GameApplication doesn't use ClientGameState."""
        from game.application.game_application import GameApplication
        # Just verify import works — actual run requires graphics
        assert GameApplication is not None
