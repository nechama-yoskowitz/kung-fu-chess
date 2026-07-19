"""
Game-start countdown animation triggered by the GameStarted event.

Displays 3 → 2 → 1 → GO! then finishes.
"""

from game.events.engine_events import GameStarted

STEP_DURATION_MS = 900.0   # Duration of each number (3, 2, 1)
GO_DURATION_MS = 600.0     # Duration of "GO!" display
TOTAL_DURATION_MS = 3 * STEP_DURATION_MS + GO_DURATION_MS

_STEPS = [
    (0, STEP_DURATION_MS, "3"),
    (STEP_DURATION_MS, 2 * STEP_DURATION_MS, "2"),
    (2 * STEP_DURATION_MS, 3 * STEP_DURATION_MS, "1"),
    (3 * STEP_DURATION_MS, TOTAL_DURATION_MS, "GO!"),
]


class GameStartAnimation:
    """
    Subscribes to GameStarted and manages a countdown timer.

    Exposes the current countdown text and whether the intro is active/finished.
    Contains no chess rules, board mutation, or rendering code.
    """

    def __init__(self, event_bus):
        self._active = False
        self._finished = False
        self._elapsed_ms = 0.0

        event_bus.subscribe(GameStarted, self._on_game_started)

    @property
    def active(self) -> bool:
        """True while the countdown is in progress (not yet finished)."""
        return self._active and not self._finished

    @property
    def finished(self) -> bool:
        return self._finished

    @property
    def current_text(self) -> str | None:
        """The countdown text to display, or None if not active."""
        if not self._active or self._finished:
            return None

        for start, end, text in _STEPS:
            if start <= self._elapsed_ms < end:
                return text

        return None

    def update(self, delta_ms: float) -> None:
        """Advance the countdown. No-op if not active or already finished."""
        if not self._active or self._finished:
            return

        self._elapsed_ms += delta_ms

        if self._elapsed_ms >= TOTAL_DURATION_MS:
            self._elapsed_ms = TOTAL_DURATION_MS
            self._finished = True

    def _on_game_started(self, event: GameStarted) -> None:
        """Activate exactly once."""
        if self._active:
            return
        self._active = True
