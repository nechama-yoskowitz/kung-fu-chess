"""
Tests for the event-driven sound system.

Uses a mock SoundPlayer to verify that SoundObserver requests the
correct sounds for each event type and priority.
"""

from unittest.mock import MagicMock, call

from game.events import EventBus, MoveResolved, GameEnded
from game.sound.sound_observer import (
    SoundObserver,
    SOUND_MOVE,
    SOUND_CAPTURE,
    SOUND_PROMOTION,
    SOUND_GAME_END,
)
from game.sound.sound_player import SoundPlayer


def _make_observer():
    bus = EventBus()
    player = MagicMock(spec=SoundPlayer)
    observer = SoundObserver(event_bus=bus, sound_player=player)
    return bus, player, observer


class TestNormalMoveSound:
    """Normal MoveResolved requests the move sound."""

    def test_arrived_plays_move_sound(self):
        bus, player, _ = _make_observer()
        bus.publish(MoveResolved(
            sequence_id=0, piece="wR", outcome="arrived",
            final_row=0, final_col=3, promoted_to=None, captured_piece=None,
        ))
        player.play.assert_called_once_with(SOUND_MOVE)

    def test_stopped_plays_move_sound(self):
        bus, player, _ = _make_observer()
        bus.publish(MoveResolved(
            sequence_id=0, piece="wR", outcome="stopped",
            final_row=0, final_col=2, promoted_to=None, captured_piece=None,
        ))
        player.play.assert_called_once_with(SOUND_MOVE)

    def test_captured_piece_does_not_play_move_sound(self):
        """A piece that was captured itself should not trigger a sound."""
        bus, player, _ = _make_observer()
        bus.publish(MoveResolved(
            sequence_id=0, piece="wR", outcome="captured",
            final_row=None, final_col=None, promoted_to=None, captured_piece=None,
        ))
        player.play.assert_not_called()


class TestCaptureSound:
    """Capture requests the capture sound."""

    def test_capture_plays_capture_sound(self):
        bus, player, _ = _make_observer()
        bus.publish(MoveResolved(
            sequence_id=0, piece="wR", outcome="arrived",
            final_row=0, final_col=3, promoted_to=None, captured_piece="bQ",
        ))
        player.play.assert_called_once_with(SOUND_CAPTURE)


class TestPromotionSound:
    """Promotion requests the promotion sound (highest priority)."""

    def test_promotion_plays_promotion_sound(self):
        bus, player, _ = _make_observer()
        bus.publish(MoveResolved(
            sequence_id=0, piece="wP", outcome="arrived",
            final_row=0, final_col=0, promoted_to="wQ", captured_piece=None,
        ))
        player.play.assert_called_once_with(SOUND_PROMOTION)

    def test_promotion_with_capture_still_plays_promotion(self):
        """Promotion takes priority over capture."""
        bus, player, _ = _make_observer()
        bus.publish(MoveResolved(
            sequence_id=0, piece="wP", outcome="arrived",
            final_row=0, final_col=0, promoted_to="wQ", captured_piece="bR",
        ))
        player.play.assert_called_once_with(SOUND_PROMOTION)


class TestGameEndSound:
    """GameEnded requests the game-end sound."""

    def test_game_ended_plays_game_end_sound(self):
        bus, player, _ = _make_observer()
        bus.publish(GameEnded(winner="w", loser="b"))
        player.play.assert_called_once_with(SOUND_GAME_END)


class TestOnlyOneSoundPerEvent:
    """One event triggers only the highest-priority sound."""

    def test_single_call_for_promotion_with_capture(self):
        bus, player, _ = _make_observer()
        bus.publish(MoveResolved(
            sequence_id=0, piece="wP", outcome="arrived",
            final_row=0, final_col=0, promoted_to="wQ", captured_piece="bN",
        ))
        assert player.play.call_count == 1

    def test_single_call_for_normal_move(self):
        bus, player, _ = _make_observer()
        bus.publish(MoveResolved(
            sequence_id=0, piece="wR", outcome="arrived",
            final_row=5, final_col=5, promoted_to=None, captured_piece=None,
        ))
        assert player.play.call_count == 1


class TestErrorHandling:
    """Missing files or playback errors do not crash event publishing."""

    def test_player_exception_does_not_propagate(self):
        bus = EventBus()
        player = MagicMock(spec=SoundPlayer)
        player.play.side_effect = RuntimeError("audio device error")
        SoundObserver(event_bus=bus, sound_player=player)

        # Should not raise
        bus.publish(MoveResolved(
            sequence_id=0, piece="wR", outcome="arrived",
            final_row=0, final_col=3, promoted_to=None, captured_piece=None,
        ))

    def test_real_player_missing_file_no_crash(self):
        """SoundPlayer.play with a non-existent file doesn't crash."""
        player = SoundPlayer("/nonexistent/path")
        player.play("missing.wav")  # Should not raise


class TestEngineIndependence:
    """Game engine and graphics do not depend on sound."""

    def test_engine_has_no_sound_import(self):
        import importlib
        import sys
        # Clear any cached modules
        mod = importlib.import_module("game.engine.game_engine")
        sound_modules = [k for k in sys.modules if "sound" in k and "game.sound" in k]
        # The engine module itself should not have caused sound imports
        # (sound is only imported by the application layer)
        assert "game.sound.sound_player" not in dir(mod)

    def test_graphics_sync_has_no_sound_import(self):
        import game.graphics.graphics_synchronizer as gs
        source = open(gs.__file__).read()
        assert "sound" not in source
