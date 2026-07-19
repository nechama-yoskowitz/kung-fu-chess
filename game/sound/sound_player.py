"""
Platform sound playback. Loads and plays .wav files non-blocking.

Uses winsound on Windows. Falls back to a silent no-op on other platforms
or when the audio device is unavailable.
"""

import os
from pathlib import Path


class SoundPlayer:
    """
    Loads and plays .wav audio files asynchronously.

    If a file is missing or playback fails, the error is silently ignored.
    Sound must never crash the game.
    """

    def __init__(self, sounds_root: str):
        self._sounds_root = Path(sounds_root)
        self._available = self._check_platform()

    def play(self, filename: str) -> None:
        """
        Play a sound file by name (e.g. 'move.wav').

        Non-blocking. Silent no-op if the file is missing, the platform
        is unsupported, or playback raises an exception.
        """
        if not self._available:
            return

        path = self._sounds_root / filename

        if not path.exists():
            return

        try:
            import winsound
            winsound.PlaySound(
                str(path),
                winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
            )
        except Exception:
            pass

    @staticmethod
    def _check_platform() -> bool:
        """Return True if winsound is available."""
        try:
            import winsound  # noqa: F401
            return True
        except ImportError:
            return False
