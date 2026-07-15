"""
Tests for the visual cooldown indicator computation.

Verifies that GraphicsSynchronizer.get_cooldown_indicators correctly
computes progress values from ActiveCooldown objects and the engine clock.
"""

from game.graphics.graphics_synchronizer import GraphicsSynchronizer
from game.realtime.motion import ActiveCooldown


COOLDOWN_MS = 2000


class TestCooldownIndicatorFullBar:
    """Full bar at cooldown start (progress = 1.0)."""

    def test_full_bar_at_start(self):
        cooldowns = [
            ActiveCooldown(piece="wR", row=0, col=2, available_at=2000),
        ]
        clock = 0  # Just started

        indicators = GraphicsSynchronizer.get_cooldown_indicators(
            cooldowns, clock, COOLDOWN_MS
        )

        assert len(indicators) == 1
        row, col, progress = indicators[0]
        assert row == 0
        assert col == 2
        assert progress == 1.0

    def test_full_bar_capped_at_one(self):
        """If remaining > duration (shouldn't happen, but be safe)."""
        cooldowns = [
            ActiveCooldown(piece="wR", row=0, col=0, available_at=5000),
        ]
        clock = 0  # remaining=5000, duration=2000 → capped at 1.0

        indicators = GraphicsSynchronizer.get_cooldown_indicators(
            cooldowns, clock, COOLDOWN_MS
        )

        assert indicators[0][2] == 1.0


class TestCooldownIndicatorHalfBar:
    """Half bar at half cooldown (progress = 0.5)."""

    def test_half_bar_at_midpoint(self):
        cooldowns = [
            ActiveCooldown(piece="wR", row=3, col=5, available_at=2000),
        ]
        clock = 1000  # remaining=1000, duration=2000 → 0.5

        indicators = GraphicsSynchronizer.get_cooldown_indicators(
            cooldowns, clock, COOLDOWN_MS
        )

        assert len(indicators) == 1
        row, col, progress = indicators[0]
        assert row == 3
        assert col == 5
        assert progress == 0.5

    def test_quarter_bar(self):
        cooldowns = [
            ActiveCooldown(piece="wR", row=0, col=0, available_at=2000),
        ]
        clock = 1500  # remaining=500, duration=2000 → 0.25

        indicators = GraphicsSynchronizer.get_cooldown_indicators(
            cooldowns, clock, COOLDOWN_MS
        )

        assert indicators[0][2] == 0.25


class TestCooldownIndicatorDisappears:
    """Bar disappears when cooldown expires (progress <= 0)."""

    def test_no_indicator_at_expiry(self):
        cooldowns = [
            ActiveCooldown(piece="wR", row=0, col=0, available_at=2000),
        ]
        clock = 2000  # remaining=0

        indicators = GraphicsSynchronizer.get_cooldown_indicators(
            cooldowns, clock, COOLDOWN_MS
        )

        assert len(indicators) == 0

    def test_no_indicator_past_expiry(self):
        cooldowns = [
            ActiveCooldown(piece="wR", row=0, col=0, available_at=2000),
        ]
        clock = 3000  # remaining=-1000

        indicators = GraphicsSynchronizer.get_cooldown_indicators(
            cooldowns, clock, COOLDOWN_MS
        )

        assert len(indicators) == 0


class TestCooldownIndicatorMultiple:
    """Multiple cooldowns simultaneously."""

    def test_multiple_cooldowns_different_progress(self):
        cooldowns = [
            ActiveCooldown(piece="wR", row=0, col=0, available_at=2000),
            ActiveCooldown(piece="wB", row=3, col=3, available_at=3000),
            ActiveCooldown(piece="wN", row=7, col=7, available_at=1500),  # expired
        ]
        clock = 1000

        indicators = GraphicsSynchronizer.get_cooldown_indicators(
            cooldowns, clock, COOLDOWN_MS
        )

        # wN expired (available_at=1500, clock=1000 → remaining=500 > 0, still active)
        # Actually remaining for wN = 1500 - 1000 = 500 → progress = 500/2000 = 0.25
        assert len(indicators) == 3

        # Sort by row for stable assertions
        indicators.sort(key=lambda x: (x[0], x[1]))

        # wR at (0,0): remaining=1000, progress=0.5
        assert indicators[0] == (0, 0, 0.5)
        # wB at (3,3): remaining=2000, progress=1.0
        assert indicators[1] == (3, 3, 1.0)
        # wN at (7,7): remaining=500, progress=0.25
        assert indicators[2] == (7, 7, 0.25)

    def test_only_expired_cooldowns_returns_empty(self):
        cooldowns = [
            ActiveCooldown(piece="wR", row=0, col=0, available_at=1000),
            ActiveCooldown(piece="wB", row=1, col=1, available_at=500),
        ]
        clock = 2000

        indicators = GraphicsSynchronizer.get_cooldown_indicators(
            cooldowns, clock, COOLDOWN_MS
        )

        assert len(indicators) == 0

    def test_empty_cooldowns_list(self):
        indicators = GraphicsSynchronizer.get_cooldown_indicators(
            [], 1000, COOLDOWN_MS
        )

        assert len(indicators) == 0
