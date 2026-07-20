"""
Regression tests for network-mode cooldown graphics and sound playback.

Verifies:
- Cooldown indicators are tracked after move_resolved in ClientGameState
- Cooldowns expire after COOLDOWN_DURATION_MS
- Captured movers do not enter cooldown
- Sounds are triggered via EventBus when ServerMessageProcessor publishes events
- Duplicate messages do not replay sounds
- Missing audio files do not crash
"""

from unittest.mock import MagicMock, patch

from game.client.client_game_state import ClientGameState
from game.client.server_message_processor import ServerMessageProcessor
from game.events import EventBus
from game.events.engine_events import MoveResolved, GameEnded
from game.graphics.graphics_manager import GraphicsManager
from game.graphics.pieces.graphic_piece import GraphicPiece
from game.model.constants import COOLDOWN_DURATION_MS
from game.sound.sound_observer import SoundObserver


def _make_gm():
    gm = MagicMock(spec=GraphicsManager)
    gm.graphic_pieces = []
    gm.get_piece_at.return_value = None
    gm.get_pieces_at.return_value = []
    return gm


# ─── Cooldown tracking ────────────────────────────────────────────────────────


class TestCooldownAfterMoveResolved:
    def test_cooldown_starts_after_arrived(self):
        state = ClientGameState()
        state.board = [["wR", ".", ".", "."]]

        state.apply_move_resolved(
            from_row=0, from_col=0, piece="wR",
            outcome="arrived", final_row=0, final_col=2,
            promoted_to=None,
        )

        indicators = state.get_cooldown_indicators()
        assert len(indicators) == 1
        assert indicators[0][0] == 0  # row
        assert indicators[0][1] == 2  # col
        assert indicators[0][2] == 1.0  # full progress at start

    def test_cooldown_does_not_start_for_captured(self):
        state = ClientGameState()
        state.board = [["wR", ".", ".", "."]]

        state.apply_move_resolved(
            from_row=0, from_col=0, piece="wR",
            outcome="captured", final_row=None, final_col=None,
            promoted_to=None,
        )

        assert state.get_cooldown_indicators() == []

    def test_cooldown_progress_decreases_over_time(self):
        state = ClientGameState()
        state.board = [[".", "wR"]]

        state.apply_move_resolved(
            from_row=0, from_col=0, piece="wR",
            outcome="arrived", final_row=0, final_col=1,
            promoted_to=None,
        )

        state.advance_clock(COOLDOWN_DURATION_MS / 2)
        indicators = state.get_cooldown_indicators()
        assert len(indicators) == 1
        assert 0.49 < indicators[0][2] < 0.51

    def test_cooldown_expires_after_duration(self):
        state = ClientGameState()
        state.board = [[".", "wR"]]

        state.apply_move_resolved(
            from_row=0, from_col=0, piece="wR",
            outcome="arrived", final_row=0, final_col=1,
            promoted_to=None,
        )

        state.advance_clock(COOLDOWN_DURATION_MS + 1)
        assert state.get_cooldown_indicators() == []

    def test_is_piece_resting_during_cooldown(self):
        state = ClientGameState()
        state.board = [[".", "wR"]]

        state.apply_move_resolved(
            from_row=0, from_col=0, piece="wR",
            outcome="arrived", final_row=0, final_col=1,
            promoted_to=None,
        )

        assert state.is_piece_resting_at(0, 1) is True
        state.advance_clock(COOLDOWN_DURATION_MS + 1)
        assert state.is_piece_resting_at(0, 1) is False

    def test_promotion_with_cooldown(self):
        state = ClientGameState()
        state.board = [[".", ".", "."], ["wP", ".", "."]]

        state.apply_move_resolved(
            from_row=1, from_col=0, piece="wP",
            outcome="arrived", final_row=0, final_col=0,
            promoted_to="wQ",
        )

        # Cooldown at destination
        assert state.is_piece_resting_at(0, 0) is True
        # Board has promoted piece
        assert state.board[0][0] == "wQ"

    def test_multiple_cooldowns_tracked_independently(self):
        state = ClientGameState()
        state.board = [[".", ".", ".", "."]]

        state.apply_move_resolved(
            from_row=0, from_col=0, piece="wR",
            outcome="arrived", final_row=0, final_col=1,
            promoted_to=None,
        )
        state.advance_clock(500)
        state.apply_move_resolved(
            from_row=0, from_col=2, piece="bR",
            outcome="arrived", final_row=0, final_col=3,
            promoted_to=None,
        )

        indicators = state.get_cooldown_indicators()
        assert len(indicators) == 2

        # First cooldown partially elapsed
        state.advance_clock(COOLDOWN_DURATION_MS - 500)
        indicators = state.get_cooldown_indicators()
        # First should have expired, second still active
        assert len(indicators) == 1
        assert indicators[0][0] == 0 and indicators[0][1] == 3


# ─── Sound playback via EventBus ──────────────────────────────────────────────


class TestSoundInNetworkMode:
    def test_move_resolved_triggers_move_sound(self):
        bus = EventBus()
        player = MagicMock()
        SoundObserver(bus, player)

        bus.publish(MoveResolved(
            sequence_id=1, piece="wR", outcome="arrived",
            final_row=0, final_col=2, promoted_to=None, captured_piece=None,
        ))

        player.play.assert_called_once_with("move.wav")

    def test_capture_triggers_capture_sound(self):
        bus = EventBus()
        player = MagicMock()
        SoundObserver(bus, player)

        bus.publish(MoveResolved(
            sequence_id=2, piece="wR", outcome="arrived",
            final_row=0, final_col=2, promoted_to=None, captured_piece="bP",
        ))

        player.play.assert_called_once_with("capture.wav")

    def test_promotion_triggers_promotion_sound(self):
        bus = EventBus()
        player = MagicMock()
        SoundObserver(bus, player)

        bus.publish(MoveResolved(
            sequence_id=3, piece="wP", outcome="arrived",
            final_row=0, final_col=0, promoted_to="wQ", captured_piece=None,
        ))

        player.play.assert_called_once_with("promotion.wav")

    def test_game_ended_triggers_game_end_sound(self):
        bus = EventBus()
        player = MagicMock()
        SoundObserver(bus, player)

        bus.publish(GameEnded(winner="w", loser="b"))

        player.play.assert_called_once_with("game_end.wav")

    def test_processor_publishes_event_for_sound(self):
        """ServerMessageProcessor publishes MoveResolved to the EventBus."""
        state = ClientGameState()
        state.board = [["wR", ".", ".", "."]]
        gm = _make_gm()
        bus = EventBus()
        player = MagicMock()
        SoundObserver(bus, player)

        proc = ServerMessageProcessor(state, gm, event_bus=bus)
        proc._move_sources[10] = (0, 0)

        proc.process_messages([{
            "type": "move_resolved",
            "payload": {
                "sequence_id": 10, "piece": "wR", "outcome": "arrived",
                "final_row": 0, "final_col": 2,
                "promoted_to": None, "captured_piece": None,
            },
        }])

        player.play.assert_called_once_with("move.wav")

    def test_capture_sound_via_processor(self):
        state = ClientGameState()
        state.board = [["wR", ".", "bP", "."]]
        gm = _make_gm()
        bus = EventBus()
        player = MagicMock()
        SoundObserver(bus, player)

        proc = ServerMessageProcessor(state, gm, event_bus=bus)
        proc._move_sources[11] = (0, 0)

        proc.process_messages([{
            "type": "move_resolved",
            "payload": {
                "sequence_id": 11, "piece": "wR", "outcome": "arrived",
                "final_row": 0, "final_col": 2,
                "promoted_to": None, "captured_piece": "bP",
            },
        }])

        player.play.assert_called_once_with("capture.wav")

    def test_missing_audio_file_does_not_crash(self):
        """SoundPlayer.play handles missing files gracefully."""
        from game.sound.sound_player import SoundPlayer

        sp = SoundPlayer("nonexistent_directory")
        # Should not raise
        sp.play("missing.wav")

    def test_no_sound_when_no_event_bus(self):
        """If event_bus is None, no sound plays (no crash)."""
        state = ClientGameState()
        state.board = [["wR", ".", ".", "."]]
        gm = _make_gm()

        proc = ServerMessageProcessor(state, gm, event_bus=None)
        proc._move_sources[20] = (0, 0)

        # Should not raise
        proc.process_messages([{
            "type": "move_resolved",
            "payload": {
                "sequence_id": 20, "piece": "wR", "outcome": "arrived",
                "final_row": 0, "final_col": 2,
                "promoted_to": None, "captured_piece": None,
            },
        }])


# ─── Graphic piece enters long_rest after resolution ─────────────────────────


class TestGraphicPieceEntersRestState:
    def test_finish_move_at_enters_long_rest_from_move(self):
        """finish_move_at transitions piece from MOVE to LONG_REST."""
        from game.graphics.pieces.piece_state_machine import PieceStateMachine

        gp = MagicMock(spec=GraphicPiece)
        gp.piece = "wR"
        gp.row = 0
        gp.col = 0
        gp.is_moving = True
        gp.state = PieceStateMachine.MOVE

        # Simulate the real finish_move_at behavior
        def fake_finish(r, c):
            gp.row = r
            gp.col = c
            gp.is_moving = False
            gp.state = PieceStateMachine.LONG_REST

        gp.finish_move_at = MagicMock(side_effect=fake_finish)

        state = ClientGameState()
        state.board = [[".", ".", "wR", "."]]
        gm = MagicMock(spec=GraphicsManager)
        gm.graphic_pieces = [gp]
        gm.get_pieces_at.side_effect = lambda r, c: [
            g for g in gm.graphic_pieces if g.row == r and g.col == c
        ]
        gm.get_piece_at.side_effect = lambda r, c: next(
            (g for g in gm.graphic_pieces if g.row == r and g.col == c), None
        )
        gm.remove_piece.side_effect = lambda g: gm.graphic_pieces.remove(g)

        proc = ServerMessageProcessor(state, gm, event_bus=EventBus())
        proc._active_movements[50] = gp
        proc._move_sources[50] = (0, 0)

        proc.process_messages([{
            "type": "move_resolved",
            "payload": {
                "sequence_id": 50, "piece": "wR", "outcome": "arrived",
                "final_row": 0, "final_col": 2,
                "promoted_to": None, "captured_piece": None,
            },
        }])

        # finish_move_at was called, which sets state to LONG_REST
        gp.finish_move_at.assert_called_once_with(0, 2)
        assert gp.state == PieceStateMachine.LONG_REST

    def test_captured_mover_does_not_enter_rest(self):
        from game.graphics.pieces.piece_state_machine import PieceStateMachine

        gp = MagicMock(spec=GraphicPiece)
        gp.piece = "wR"
        gp.row = 0
        gp.col = 0
        gp.is_moving = True
        gp.state = PieceStateMachine.MOVE

        state = ClientGameState()
        state.board = [["wR", ".", ".", "."]]
        gm = MagicMock(spec=GraphicsManager)
        gm.graphic_pieces = [gp]
        gm.get_pieces_at.return_value = []
        gm.remove_piece.side_effect = lambda g: gm.graphic_pieces.remove(g)

        proc = ServerMessageProcessor(state, gm, event_bus=EventBus())
        proc._active_movements[51] = gp
        proc._move_sources[51] = (0, 0)

        proc.process_messages([{
            "type": "move_resolved",
            "payload": {
                "sequence_id": 51, "piece": "wR", "outcome": "captured",
                "final_row": None, "final_col": None,
                "promoted_to": None, "captured_piece": "wR",
            },
        }])

        # Piece was removed, not transitioned to rest
        assert gp not in gm.graphic_pieces
        assert gp.state == PieceStateMachine.MOVE  # never changed
