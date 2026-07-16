"""
Main game loop — frame timing, update orchestration, and window lifecycle.
"""

import time

from game.graphics.frame_composer import FrameComposer
from game.graphics.graphics_manager import GraphicsManager
from game.graphics.graphics_synchronizer import GraphicsSynchronizer
from game.graphics.img import Img
from game.graphics.mouse_input_adapter import MouseInputAdapter

Esc = 27


class GameLoop:
    """
    Owns the frame loop: timing, sync calls, rendering, and window events.

    Rendering is delegated to FrameComposer.
    Sync orchestration calls the synchronizer's per-frame methods.
    """

    def __init__(
        self,
        frame_composer: FrameComposer,
        graphics_manager: GraphicsManager,
        synchronizer: GraphicsSynchronizer | None = None,
        pending_moves_provider=None,
        board_provider=None,
        active_jumps_provider=None,
        engine_updater=None,
        mouse_input_adapter: MouseInputAdapter | None = None,
        target_fps: int = 60,
        window_name: str = "Kung-Fu Chess",
    ):
        if target_fps <= 0:
            raise ValueError("target_fps must be greater than zero")

        self.frame_composer = frame_composer
        self.graphics_manager = graphics_manager
        self.synchronizer = synchronizer
        self.pending_moves_provider = pending_moves_provider
        self.board_provider = board_provider
        self.active_jumps_provider = active_jumps_provider
        self.engine_updater = engine_updater
        self.mouse_input_adapter = mouse_input_adapter
        self.target_fps = target_fps
        self.window_name = window_name
        self.running = False

    def run(self) -> None:
        self.running = True
        previous_time = time.perf_counter()

        # Initial frame creates the window before mouse callback registration.
        canvas = self.frame_composer.compose()
        canvas.show(window_name=self.window_name, delay_ms=1)

        if self.mouse_input_adapter:
            self.mouse_input_adapter.register(self.window_name)

        try:
            while self.running:
                current_time = time.perf_counter()
                delta_time_ms = (current_time - previous_time) * 1000
                previous_time = current_time

                self._update(delta_time_ms)

                canvas = self.frame_composer.compose()

                delay_ms = max(1, int(1000 / self.target_fps))
                key = canvas.show(window_name=self.window_name, delay_ms=delay_ms)

                if not Img.is_window_open(self.window_name):
                    self.running = False
                elif key == Esc:
                    self.running = False

        finally:
            Img.close_windows()

    def _update(self, delta_time_ms: float) -> None:
        """Advance engine, synchronize state, update animations."""
        if self.engine_updater:
            self.engine_updater(delta_time_ms)

        if self.synchronizer:
            if self.board_provider:
                self.synchronizer.sync_removals(self.board_provider())
            if self.pending_moves_provider:
                self.synchronizer.sync_movements(self.pending_moves_provider())
            if self.active_jumps_provider:
                self.synchronizer.sync_jumps(self.active_jumps_provider())

        self.graphics_manager.update(delta_time_ms)
