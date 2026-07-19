"""
Main game loop — frame timing, update orchestration, and window lifecycle.
"""

import time

import cv2

from game.graphics.frame_composer import FrameComposer
from game.graphics.game_screen_composer import GameScreenComposer
from game.graphics.graphics_manager import GraphicsManager
from game.graphics.graphics_synchronizer import GraphicsSynchronizer
from game.graphics.img import Img
from game.graphics.mouse_input_adapter import MouseInputAdapter

Esc = 27


class GameLoop:
    """
    Owns the frame loop: timing, sync calls, rendering, and window events.

    Supports two rendering modes:
    - With GameScreenComposer: full responsive layout with panels.
    - With FrameComposer only: board-only rendering (legacy/test mode).
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
        screen_composer: GameScreenComposer | None = None,
        game_end_animation=None,
        game_start_animation=None,
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
        self.screen_composer = screen_composer
        self.game_end_animation = game_end_animation
        self.game_start_animation = game_start_animation
        self.target_fps = target_fps
        self.window_name = window_name
        self.running = False

    def run(self) -> None:
        self.running = True
        previous_time = time.perf_counter()

        # Create a resizable window if using screen composer.
        if self.screen_composer:
            cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(self.window_name,
                             self.screen_composer.window_width,
                             self.screen_composer.window_height)

        # Initial frame to create/show the window.
        canvas = self._render_frame()
        canvas.show(window_name=self.window_name, delay_ms=1)

        if self.mouse_input_adapter:
            self.mouse_input_adapter.register(self.window_name)

        try:
            while self.running:
                current_time = time.perf_counter()
                delta_time_ms = (current_time - previous_time) * 1000
                previous_time = current_time

                self._update(delta_time_ms)

                # Check for window resize if using screen composer.
                if self.screen_composer:
                    self._handle_resize()

                canvas = self._render_frame()

                delay_ms = max(1, int(1000 / self.target_fps))
                key = canvas.show(window_name=self.window_name, delay_ms=delay_ms)

                if not Img.is_window_open(self.window_name):
                    self.running = False
                elif key == Esc:
                    self.running = False

        finally:
            Img.close_windows()

    def _render_frame(self) -> Img:
        """Compose either full-screen or board-only frame."""
        if self.screen_composer:
            return self.screen_composer.compose()
        return self.frame_composer.compose()

    def _handle_resize(self) -> None:
        """Detect window resize and update the screen composer layout."""
        try:
            rect = cv2.getWindowImageRect(self.window_name)
            if rect is not None:
                _, _, w, h = rect
                if w > 0 and h > 0:
                    self.screen_composer.update_window_size(w, h)
        except cv2.error:
            pass

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

        if self.game_end_animation:
            self.game_end_animation.update(delta_time_ms)

        if self.game_start_animation:
            self.game_start_animation.update(delta_time_ms)
