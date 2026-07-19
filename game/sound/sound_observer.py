"""
Event-driven sound observer. Subscribes to game events and triggers
the appropriate sound via SoundPlayer.

Does not contain game logic. Only maps events to sound file names.
"""

from game.events.engine_events import GameEnded, MoveResolved
from game.sound.sound_player import SoundPlayer

# Sound file names — actual .wav files expected under the sounds_root directory.
SOUND_MOVE = "move.wav"
SOUND_CAPTURE = "capture.wav"
SOUND_PROMOTION = "promotion.wav"
SOUND_GAME_END = "game_end.wav"


class SoundObserver:
    """
    Subscribes to MoveResolved and GameEnded events.
    Selects the highest-priority sound for each event and plays it.

    Priority for MoveResolved: promotion > capture > normal move.
    """

    def __init__(self, event_bus, sound_player: SoundPlayer):
        self._player = sound_player

        event_bus.subscribe(MoveResolved, self._on_move_resolved)
        event_bus.subscribe(GameEnded, self._on_game_ended)

    def _on_move_resolved(self, event: MoveResolved) -> None:
        """Select and play the appropriate sound for a resolved move."""
        try:
            if event.promoted_to:
                self._player.play(SOUND_PROMOTION)
            elif event.captured_piece:
                self._player.play(SOUND_CAPTURE)
            elif event.outcome in ("arrived", "stopped"):
                self._player.play(SOUND_MOVE)
        except Exception:
            pass

    def _on_game_ended(self, event: GameEnded) -> None:
        """Play the game-end sound."""
        try:
            self._player.play(SOUND_GAME_END)
        except Exception:
            pass
