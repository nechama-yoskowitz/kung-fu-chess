"""
Game-end fade-in animation triggered by the GameEnded event.

Manages opacity progression over a fixed duration. Exposes visual state
for the frame composer to draw. Contains no board or engine logic.
"""

from game.events.engine_events import GameEnded

FADE_DURATION_MS = 1500.0  # Time for overlay to reach full opacity
MAX_OVERLAY_ALPHA = 0.65


class GameEndAnimation:
    """
    Subscribes to GameEnded and drives a timed fade-in overlay.

    After activation, opacity increases linearly from 0 to MAX_OVERLAY_ALPHA
    over FADE_DURATION_MS milliseconds.
    """

    def __init__(self, event_bus):
        self._active = False
        self._winner: str | None = None
        self._elapsed_ms = 0.0

        event_bus.subscribe(GameEnded, self._on_game_ended)

    @property
    def active(self) -> bool:
        return self._active

    @property
    def opacity(self) -> float:
        """Current overlay opacity (0.0 to MAX_OVERLAY_ALPHA)."""
        if not self._active:
            return 0.0
        progress = min(self._elapsed_ms / FADE_DURATION_MS, 1.0)
        return progress * MAX_OVERLAY_ALPHA

    @property
    def text_opacity(self) -> float:
        """Current text visibility (0.0 to 1.0), slightly delayed from overlay."""
        if not self._active:
            return 0.0
        # Text starts fading in after 30% of the overlay duration
        text_start = FADE_DURATION_MS * 0.3
        if self._elapsed_ms < text_start:
            return 0.0
        text_progress = min((self._elapsed_ms - text_start) / (FADE_DURATION_MS * 0.7), 1.0)
        return text_progress

    @property
    def winner_text(self) -> str | None:
        """Display text for the winner, or None if not active."""
        if not self._active or self._winner is None:
            return None
        return "WHITE WINS" if self._winner == "w" else "BLACK WINS"

    def update(self, delta_ms: float) -> None:
        """Advance the animation by delta_ms. No-op if not active."""
        if not self._active:
            return
        self._elapsed_ms = min(self._elapsed_ms + delta_ms, FADE_DURATION_MS)

    def _on_game_ended(self, event: GameEnded) -> None:
        """Activate exactly once on the first GameEnded event."""
        if self._active:
            return
        self._active = True
        self._winner = event.winner
