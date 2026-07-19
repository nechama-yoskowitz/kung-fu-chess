"""
Tests for GameStartAnimation — event-driven countdown before gameplay.
"""

import cv2
from unittest.mock import MagicMock

from game.events import EventBus, GameEnded
from game.events.engine_events import GameStarted
from game.graphics.game_start_animation import (
    GameStartAnimation,
    STEP_DURATION_MS,
    GO_DURATION_MS,
    TOTAL_DURATION_MS,
)
from game.graphics.mouse_input_adapter import MouseInputAdapter


class TestActivation:
    """GameStarted event activates the animation."""

    def test_inactive_before_event(self):
        bus = EventBus()
        anim = GameStartAnimation(bus)
        assert anim.active is False
        assert anim.finished is False

    def test_active_after_game_started(self):
        bus = EventBus()
        anim = GameStartAnimation(bus)
        bus.publish(GameStarted())
        assert anim.active is True
        assert anim.finished is False


class TestPublishedOnce:
    """Repeated GameStarted does not restart the animation."""

    def test_second_event_ignored(self):
        bus = EventBus()
        anim = GameStartAnimation(bus)
        bus.publish(GameStarted())
        anim.update(STEP_DURATION_MS * 2)  # past "2"

        bus.publish(GameStarted())  # should be ignored
        assert anim.current_text == "1"  # still progressing, not restarted


class TestInitialCountdown:
    """Initial countdown value is '3'."""

    def test_starts_at_three(self):
        bus = EventBus()
        anim = GameStartAnimation(bus)
        bus.publish(GameStarted())
        assert anim.current_text == "3"


class TestCountdownProgression:
    """update(delta_ms) advances from 3 → 2 → 1 → GO!"""

    def test_three_to_two(self):
        bus = EventBus()
        anim = GameStartAnimation(bus)
        bus.publish(GameStarted())
        anim.update(STEP_DURATION_MS)
        assert anim.current_text == "2"

    def test_two_to_one(self):
        bus = EventBus()
        anim = GameStartAnimation(bus)
        bus.publish(GameStarted())
        anim.update(2 * STEP_DURATION_MS)
        assert anim.current_text == "1"

    def test_one_to_go(self):
        bus = EventBus()
        anim = GameStartAnimation(bus)
        bus.publish(GameStarted())
        anim.update(3 * STEP_DURATION_MS)
        assert anim.current_text == "GO!"


class TestFinished:
    """Animation becomes finished after full duration."""

    def test_finished_after_total_duration(self):
        bus = EventBus()
        anim = GameStartAnimation(bus)
        bus.publish(GameStarted())
        anim.update(TOTAL_DURATION_MS)
        assert anim.finished is True
        assert anim.active is False

    def test_not_finished_before_total(self):
        bus = EventBus()
        anim = GameStartAnimation(bus)
        bus.publish(GameStarted())
        anim.update(TOTAL_DURATION_MS - 1)
        assert anim.finished is False
        assert anim.active is True


class TestClamping:
    """Progress is clamped at total duration."""

    def test_elapsed_clamped(self):
        bus = EventBus()
        anim = GameStartAnimation(bus)
        bus.publish(GameStarted())
        anim.update(TOTAL_DURATION_MS * 5)
        assert anim.finished is True
        assert anim.current_text is None


class TestFrameComposition:
    """Frame composition draws nothing before, correct text after."""

    def test_no_text_before_activation(self):
        bus = EventBus()
        anim = GameStartAnimation(bus)
        assert anim.current_text is None

    def test_text_after_activation(self):
        bus = EventBus()
        anim = GameStartAnimation(bus)
        bus.publish(GameStarted())
        assert anim.current_text == "3"

    def test_no_text_after_finished(self):
        bus = EventBus()
        anim = GameStartAnimation(bus)
        bus.publish(GameStarted())
        anim.update(TOTAL_DURATION_MS)
        assert anim.current_text is None


class TestMouseInputBlocked:
    """Mouse input is blocked while animation is active."""

    def test_blocked_during_countdown(self):
        bus = EventBus()
        anim = GameStartAnimation(bus)
        bus.publish(GameStarted())

        controller = MagicMock()
        controller.click = MagicMock()
        adapter = MouseInputAdapter(
            controller,
            input_blocked_provider=lambda: anim.active,
        )

        adapter._on_mouse_event(cv2.EVENT_LBUTTONDOWN, 100, 100, 0, None)
        controller.click.assert_not_called()

    def test_enabled_after_countdown_finishes(self):
        bus = EventBus()
        anim = GameStartAnimation(bus)
        bus.publish(GameStarted())
        anim.update(TOTAL_DURATION_MS)

        controller = MagicMock()
        controller.click = MagicMock()
        adapter = MouseInputAdapter(
            controller,
            input_blocked_provider=lambda: anim.active,
        )

        adapter._on_mouse_event(cv2.EVENT_LBUTTONDOWN, 100, 100, 0, None)
        controller.click.assert_called_once()


class TestGameOverStillWorks:
    """Game-over input blocking continues to work independently."""

    def test_game_over_blocks_input(self):
        controller = MagicMock()
        controller.click = MagicMock()
        adapter = MouseInputAdapter(
            controller,
            game_over_provider=lambda: True,
            input_blocked_provider=lambda: False,
        )

        adapter._on_mouse_event(cv2.EVENT_LBUTTONDOWN, 100, 100, 0, None)
        controller.click.assert_not_called()
