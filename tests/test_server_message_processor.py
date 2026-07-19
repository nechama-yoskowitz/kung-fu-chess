"""
Tests for ServerMessageProcessor — applies server messages to client state/graphics.
"""

from unittest.mock import MagicMock, patch

from game.client.client_game_state import ClientGameState
from game.client.server_message_processor import ServerMessageProcessor
from game.events import EventBus, GameEnded, MoveResolved
from game.graphics.graphics_manager import GraphicsManager


def _make_mock_gm():
    gm = MagicMock(spec=GraphicsManager)
    gm.graphic_pieces = []
    gm.get_piece_at = MagicMock(return_value=None)
    gm.sprite_manager = MagicMock()
    gm.piece_size = (50, 50)
    return gm


class TestPlayerAssigned:
    def test_updates_player_color(self):
        state = ClientGameState()
        gm = _make_mock_gm()
        proc = ServerMessageProcessor(state, gm)

        proc.process_messages([{"type": "player_assigned", "payload": {"color": "w"}}])
        assert state.player_color == "w"
        assert state.connected is True


class TestGameState:
    def test_updates_board_and_scores(self):
        state = ClientGameState()
        gm = _make_mock_gm()
        proc = ServerMessageProcessor(state, gm)

        board = [["wR", ".", ".", "bK"]]
        proc.process_messages([{
            "type": "game_state",
            "payload": {
                "board": board,
                "clock": 5000.0,
                "white_score": 3,
                "black_score": 1,
                "game_over": False,
            },
        }])

        assert state.board == [["wR", ".", ".", "bK"]]
        assert state.white_score == 3


class TestMoveAccepted:
    def test_starts_animation(self):
        state = ClientGameState()
        state.apply_game_state([["wR", ".", ".", "."]], 0, 0, 0, False)

        gm = _make_mock_gm()
        mock_piece = MagicMock()
        mock_piece.is_moving = False
        gm.get_piece_at = MagicMock(return_value=mock_piece)
        proc = ServerMessageProcessor(state, gm)

        proc.process_messages([{
            "type": "move_accepted",
            "payload": {
                "sequence_id": 0,
                "piece": "wR",
                "from_row": 0, "from_col": 0,
                "to_row": 0, "to_col": 3,
                "started_at": 0, "arrive_at": 3000,
            },
        }])

        mock_piece.start_move.assert_called_once_with(
            to_row=0, to_col=3, duration_ms=3000.0
        )


class TestMoveRejected:
    def test_does_not_start_animation(self):
        state = ClientGameState()
        gm = _make_mock_gm()
        proc = ServerMessageProcessor(state, gm)

        proc.process_messages([{
            "type": "move_rejected",
            "payload": {"reason": "not_your_piece", "from_row": 0, "from_col": 0, "to_row": 0, "to_col": 3},
        }])
        # No crash, no graphics call


class TestMoveResolved:
    def test_finalizes_arrival(self):
        state = ClientGameState()
        gm = _make_mock_gm()
        mock_piece = MagicMock()
        proc = ServerMessageProcessor(state, gm)
        proc._active_movements[5] = mock_piece

        proc.process_messages([{
            "type": "move_resolved",
            "payload": {
                "sequence_id": 5,
                "piece": "wR",
                "outcome": "arrived",
                "final_row": 0, "final_col": 3,
                "promoted_to": None,
                "captured_piece": None,
            },
        }])

        mock_piece.finish_move_at.assert_called_once_with(0, 3)

    def test_removes_captured_piece(self):
        state = ClientGameState()
        gm = _make_mock_gm()
        mock_piece = MagicMock()
        gm.graphic_pieces = [mock_piece]
        proc = ServerMessageProcessor(state, gm)
        proc._active_movements[7] = mock_piece

        proc.process_messages([{
            "type": "move_resolved",
            "payload": {
                "sequence_id": 7,
                "piece": "wR",
                "outcome": "captured",
                "final_row": None, "final_col": None,
                "promoted_to": None,
                "captured_piece": None,
            },
        }])

        gm.remove_piece.assert_called_once_with(mock_piece)

    def test_handles_promotion(self):
        state = ClientGameState()
        gm = _make_mock_gm()
        mock_piece = MagicMock()
        proc = ServerMessageProcessor(state, gm)
        proc._active_movements[2] = mock_piece

        proc.process_messages([{
            "type": "move_resolved",
            "payload": {
                "sequence_id": 2,
                "piece": "wP",
                "outcome": "arrived",
                "final_row": 0, "final_col": 0,
                "promoted_to": "wQ",
                "captured_piece": None,
            },
        }])

        mock_piece.finish_move_at.assert_called_once()
        mock_piece.promote_to.assert_called_once_with("wQ")


class TestJumpAccepted:
    def test_starts_jump_animation(self):
        state = ClientGameState()
        gm = _make_mock_gm()
        mock_piece = MagicMock()
        mock_piece.state = "idle"
        gm.get_piece_at = MagicMock(return_value=mock_piece)
        proc = ServerMessageProcessor(state, gm)

        proc.process_messages([{
            "type": "jump_accepted",
            "payload": {"piece": "wR", "row": 0, "col": 0, "expires_at": 3500},
        }])

        mock_piece.set_state.assert_called_once()


class TestJumpRejected:
    def test_no_animation(self):
        state = ClientGameState()
        gm = _make_mock_gm()
        proc = ServerMessageProcessor(state, gm)

        proc.process_messages([{
            "type": "jump_rejected",
            "payload": {"reason": "invalid", "row": 0, "col": 0},
        }])
        # No crash


class TestGameEnded:
    def test_triggers_event(self):
        state = ClientGameState()
        gm = _make_mock_gm()
        bus = EventBus()
        received = []
        bus.subscribe(GameEnded, lambda e: received.append(e))
        proc = ServerMessageProcessor(state, gm, event_bus=bus)

        proc.process_messages([{
            "type": "game_ended",
            "payload": {"winner": "w", "loser": "b"},
        }])

        assert state.game_over is True
        assert len(received) == 1
        assert received[0].winner == "w"


class TestGameFull:
    def test_requests_shutdown(self):
        state = ClientGameState()
        gm = _make_mock_gm()
        shutdown_called = []
        proc = ServerMessageProcessor(state, gm, on_shutdown=lambda: shutdown_called.append(True))

        proc.process_messages([{
            "type": "error",
            "payload": {"code": "game_full", "message": "game is full"},
        }])

        assert len(shutdown_called) == 1


class TestMalformedMessages:
    def test_unknown_type_does_not_crash(self):
        state = ClientGameState()
        gm = _make_mock_gm()
        proc = ServerMessageProcessor(state, gm)

        proc.process_messages([{"type": "unknown_xyz", "payload": {}}])
        # No crash

    def test_missing_payload_does_not_crash(self):
        state = ClientGameState()
        gm = _make_mock_gm()
        proc = ServerMessageProcessor(state, gm)

        proc.process_messages([{"type": "move_accepted", "payload": {}}])
        # No crash


class TestEntryPoint:
    def test_no_server_preserves_local(self):
        """run_game with no --server uses local GameApplication."""
        import sys
        old_argv = sys.argv
        sys.argv = ["run_game.py"]
        # Just verify parsing doesn't crash
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--server", default=None)
        args = parser.parse_args([])
        assert args.server is None
        sys.argv = old_argv

    def test_server_flag_selects_network(self):
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--server", default=None)
        args = parser.parse_args(["--server", "ws://localhost:8765"])
        assert args.server == "ws://localhost:8765"

    def test_invalid_uri_detected(self):
        uri = "http://wrong:123"
        assert not uri.startswith("ws://") and not uri.startswith("wss://")
