"""
Tests for client state integration with all server protocol messages.

Verifies ClientGameState and ServerMessageProcessor handle all implemented
protocol messages correctly without requiring a graphical window.
"""

from unittest.mock import MagicMock

from game.client.client_game_state import ClientGameState
from game.client.server_message_processor import ServerMessageProcessor
from game.events import EventBus
from game.graphics.graphics_manager import GraphicsManager


def _make_gm():
    gm = MagicMock(spec=GraphicsManager)
    gm.graphic_pieces = []
    gm.get_piece_at.return_value = None
    gm.get_pieces_at.return_value = []
    return gm


def _make_proc(state=None):
    state = state or ClientGameState()
    gm = _make_gm()
    bus = EventBus()
    proc = ServerMessageProcessor(state, gm, event_bus=bus)
    return proc, state


# ─── Matchmaking state ────────────────────────────────────────────────────────


class TestMatchmakingState:
    def test_matchmaking_started_sets_active(self):
        proc, state = _make_proc()
        proc.process_messages([{"type": "matchmaking_started", "payload": {}}])
        assert state.matchmaking_active is True

    def test_matchmaking_timeout_clears_active(self):
        proc, state = _make_proc()
        state.matchmaking_active = True
        proc.process_messages([{"type": "matchmaking_timeout", "payload": {}}])
        assert state.matchmaking_active is False

    def test_matchmaking_cancelled_clears_active(self):
        proc, state = _make_proc()
        state.matchmaking_active = True
        proc.process_messages([{"type": "matchmaking_cancelled", "payload": {}}])
        assert state.matchmaking_active is False

    def test_match_found_clears_matchmaking(self):
        proc, state = _make_proc()
        state.matchmaking_active = True
        proc.process_messages([{
            "type": "match_found",
            "payload": {"opponent_username": "bob", "color": "w",
                        "own_rating": 1200, "opponent_rating": 1250},
        }])
        assert state.matchmaking_active is False
        assert state.opponent_username == "bob"
        assert state.player_color == "w"


# ─── Room state ───────────────────────────────────────────────────────────────


class TestRoomState:
    def test_room_created(self):
        proc, state = _make_proc()
        proc.process_messages([{
            "type": "room_created",
            "payload": {"room_id": "abc123"},
        }])
        assert state.room_id == "abc123"
        assert state.room_role == "player"

    def test_room_joined_as_player(self):
        proc, state = _make_proc()
        proc.process_messages([{
            "type": "room_joined",
            "payload": {"room_id": "xyz", "role": "player", "color": "b"},
        }])
        assert state.room_id == "xyz"
        assert state.room_role == "player"
        assert state.player_color == "b"
        assert state.is_viewer is False

    def test_room_joined_as_viewer(self):
        proc, state = _make_proc()
        proc.process_messages([{
            "type": "room_joined",
            "payload": {"room_id": "xyz", "role": "viewer", "color": None},
        }])
        assert state.room_id == "xyz"
        assert state.room_role == "viewer"
        assert state.is_viewer is True


# ─── Viewer behavior ──────────────────────────────────────────────────────────


class TestViewerState:
    def test_viewer_input_blocked(self):
        state = ClientGameState()
        state.apply_room_joined("r1", "viewer", None)
        assert state.is_viewer is True

    def test_player_input_not_blocked(self):
        state = ClientGameState()
        state.apply_room_joined("r1", "player", "w")
        assert state.is_viewer is False


# ─── Reconnect state ──────────────────────────────────────────────────────────


class TestReconnectState:
    def test_player_disconnected(self):
        proc, state = _make_proc()
        proc.process_messages([{
            "type": "player_disconnected",
            "payload": {"username": "alice", "color": "w", "remaining_seconds": 20},
        }])
        assert state.disconnected_player == "alice"
        assert state.disconnected_color == "w"
        assert state.reconnect_remaining == 20

    def test_reconnect_countdown_update(self):
        proc, state = _make_proc()
        state.disconnected_player = "alice"
        proc.process_messages([{
            "type": "reconnect_countdown",
            "payload": {"username": "alice", "color": "w", "remaining_seconds": 15},
        }])
        assert state.reconnect_remaining == 15

    def test_player_reconnected_clears_state(self):
        proc, state = _make_proc()
        state.disconnected_player = "alice"
        state.disconnected_color = "w"
        state.reconnect_remaining = 10
        proc.process_messages([{
            "type": "player_reconnected",
            "payload": {"username": "alice", "color": "w"},
        }])
        assert state.disconnected_player is None
        assert state.reconnect_remaining is None


# ─── Game-over state ──────────────────────────────────────────────────────────


class TestGameOverState:
    def test_game_ended_stores_winner(self):
        proc, state = _make_proc()
        proc.process_messages([{
            "type": "game_ended",
            "payload": {"winner": "w", "loser": "b"},
        }])
        assert state.game_over is True
        assert state.winner_color == "w"

    def test_game_ended_stores_reason(self):
        proc, state = _make_proc()
        proc.process_messages([{
            "type": "game_ended",
            "payload": {"winner": "b", "loser": "w", "reason": "auto_resign"},
        }])
        assert state.game_end_reason == "auto_resign"


# ─── Unknown message safety ───────────────────────────────────────────────────


class TestUnknownMessageSafety:
    def test_unknown_message_does_not_crash(self):
        proc, state = _make_proc()
        # Should not raise
        proc.process_messages([{
            "type": "completely_unknown_type",
            "payload": {"data": 123},
        }])
        # State unchanged
        assert state.connected is False

    def test_malformed_payload_does_not_crash(self):
        proc, state = _make_proc()
        proc.process_messages([{
            "type": "game_ended",
            "payload": {},  # Missing winner/loser — uses defaults
        }])
        assert state.game_over is True


# ─── Network board immutability ───────────────────────────────────────────────


class TestNetworkBoardAuthority:
    def test_board_not_mutated_by_move_request(self):
        """Sending a move request must not change the local board."""
        import queue
        from game.client.network_game_gateway import NetworkGameGateway

        state = ClientGameState()
        state.board = [["wR", ".", ".", "."]]
        state.player_color = "w"
        state.connected = True
        outgoing = queue.Queue()
        gw = NetworkGameGateway(state, outgoing)

        # Request a move — board must NOT change
        gw.request_move(0, 0, 0, 2)
        assert state.board[0][0] == "wR"
        assert state.board[0][2] == "."
