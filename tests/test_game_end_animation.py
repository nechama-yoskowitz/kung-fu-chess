"""
Tests for GameEndAnimation — event-driven fade-in game-over overlay.
"""

from unittest.mock import MagicMock

from game.events import EventBus, GameEnded
from game.graphics.game_end_animation import GameEndAnimation, FADE_DURATION_MS, MAX_OVERLAY_ALPHA


class TestActivation:
    """GameEnded event activates the animation."""

    def test_not_active_before_event(self):
        bus = EventBus()
        anim = GameEndAnimation(bus)
        assert anim.active is False

    def test_active_after_game_ended(self):
        bus = EventBus()
        anim = GameEndAnimation(bus)
        bus.publish(GameEnded(winner="w", loser="b"))
        assert anim.active is True


class TestWinnerStored:
    """Winner is stored correctly from the event."""

    def test_white_winner(self):
        bus = EventBus()
        anim = GameEndAnimation(bus)
        bus.publish(GameEnded(winner="w", loser="b"))
        assert anim.winner_text == "WHITE WINS"

    def test_black_winner(self):
        bus = EventBus()
        anim = GameEndAnimation(bus)
        bus.publish(GameEnded(winner="b", loser="w"))
        assert anim.winner_text == "BLACK WINS"

    def test_winner_text_none_before_activation(self):
        bus = EventBus()
        anim = GameEndAnimation(bus)
        assert anim.winner_text is None


class TestInitialOpacity:
    """Opacity starts at zero."""

    def test_opacity_zero_before_activation(self):
        bus = EventBus()
        anim = GameEndAnimation(bus)
        assert anim.opacity == 0.0

    def test_opacity_zero_at_activation_before_update(self):
        bus = EventBus()
        anim = GameEndAnimation(bus)
        bus.publish(GameEnded(winner="w", loser="b"))
        assert anim.opacity == 0.0


class TestProgressUpdate:
    """update(delta_ms) increases opacity."""

    def test_opacity_increases_after_update(self):
        bus = EventBus()
        anim = GameEndAnimation(bus)
        bus.publish(GameEnded(winner="w", loser="b"))
        anim.update(FADE_DURATION_MS * 0.5)
        assert anim.opacity > 0.0
        assert anim.opacity < MAX_OVERLAY_ALPHA

    def test_opacity_at_half_duration(self):
        bus = EventBus()
        anim = GameEndAnimation(bus)
        bus.publish(GameEnded(winner="w", loser="b"))
        anim.update(FADE_DURATION_MS * 0.5)
        expected = 0.5 * MAX_OVERLAY_ALPHA
        assert abs(anim.opacity - expected) < 0.01


class TestProgressClamped:
    """Progress is clamped when duration is reached."""

    def test_opacity_clamped_at_max(self):
        bus = EventBus()
        anim = GameEndAnimation(bus)
        bus.publish(GameEnded(winner="w", loser="b"))
        anim.update(FADE_DURATION_MS * 2)  # Way past duration
        assert anim.opacity == MAX_OVERLAY_ALPHA

    def test_text_opacity_clamped_at_one(self):
        bus = EventBus()
        anim = GameEndAnimation(bus)
        bus.publish(GameEnded(winner="w", loser="b"))
        anim.update(FADE_DURATION_MS * 2)
        assert anim.text_opacity == 1.0


class TestRepeatedEventIgnored:
    """Repeated GameEnded does not restart or corrupt the animation."""

    def test_second_event_ignored(self):
        bus = EventBus()
        anim = GameEndAnimation(bus)
        bus.publish(GameEnded(winner="w", loser="b"))
        anim.update(FADE_DURATION_MS * 0.8)

        # Second event with different winner should be ignored
        bus.publish(GameEnded(winner="b", loser="w"))
        assert anim.winner_text == "WHITE WINS"  # Still the first winner
        assert anim.opacity > 0  # Progress wasn't reset


class TestFrameCompositionIntegration:
    """Frame composition draws nothing before activation, draws after."""

    def test_no_draw_before_activation(self):
        bus = EventBus()
        anim = GameEndAnimation(bus)
        # Not active → compose should not draw overlay
        assert anim.active is False
        assert anim.opacity == 0.0

    def test_draws_after_activation_and_update(self):
        bus = EventBus()
        anim = GameEndAnimation(bus)
        bus.publish(GameEnded(winner="w", loser="b"))
        anim.update(FADE_DURATION_MS)
        assert anim.active is True
        assert anim.opacity > 0
        assert anim.winner_text == "WHITE WINS"


class TestMouseInputStillBlocked:
    """Mouse input blocking remains based on engine.game_over."""

    def test_mouse_blocked_by_engine_game_over(self):
        import cv2
        from game.graphics.mouse_input_adapter import MouseInputAdapter

        controller = MagicMock()
        controller.click = MagicMock()

        adapter = MouseInputAdapter(
            controller,
            game_over_provider=lambda: True,  # game over
        )

        adapter._on_mouse_event(cv2.EVENT_LBUTTONDOWN, 100, 100, 0, None)
        controller.click.assert_not_called()
