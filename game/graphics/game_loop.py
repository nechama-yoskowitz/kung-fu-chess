import time

from game.graphics.graphics_manager import GraphicsManager
from game.graphics.graphics_synchronizer import GraphicsSynchronizer
from game.graphics.img import Img
from game.graphics.mouse_input_adapter import MouseInputAdapter
from game.graphics.renderer import Renderer

Esc = 27


class GameLoop:
    def __init__(
        self,
        renderer: Renderer,
        graphics_manager: GraphicsManager,
        rows: int,
        cols: int,
        synchronizer: GraphicsSynchronizer | None = None,
        pending_moves_provider=None,
        board_provider=None,
        engine_updater=None,
        mouse_input_adapter: MouseInputAdapter | None = None,
        selection_provider=None,
        target_fps: int = 60,
        window_name: str = "Kung-Fu Chess",
    ):
        if target_fps <= 0:
            raise ValueError("target_fps must be greater than zero")

        self.renderer = renderer
        self.graphics_manager = graphics_manager
        self.rows = rows
        self.cols = cols
        self.synchronizer = synchronizer
        self.pending_moves_provider = pending_moves_provider
        self.board_provider = board_provider
        self.engine_updater = engine_updater
        self.mouse_input_adapter = mouse_input_adapter
        self.selection_provider = selection_provider
        self.target_fps = target_fps
        self.window_name = window_name
        self.running = False

    def run(self) -> None:
        self.running = True
        previous_time = time.perf_counter()

        # Show an initial frame so the window exists before registering
        # the mouse callback.
        canvas = self.renderer.start_frame()
        self.graphics_manager.draw(
            renderer=self.renderer,
            rows=self.rows,
            cols=self.cols,
        )
        canvas.show(window_name=self.window_name, delay_ms=1)

        if self.mouse_input_adapter:
            self.mouse_input_adapter.register(self.window_name)

        try:
            while self.running:
                current_time = time.perf_counter()
                delta_time_ms = (current_time - previous_time) * 1000
                previous_time = current_time

                if self.engine_updater:
                    self.engine_updater(delta_time_ms)

                if self.synchronizer and self.board_provider and self.pending_moves_provider:
                    self.synchronizer.sync_removals(
                        self.board_provider(),
                        self.pending_moves_provider(),
                    )

                if self.synchronizer and self.pending_moves_provider:
                    self.synchronizer.sync_movements(
                        self.pending_moves_provider()
                    )

                self.graphics_manager.update(delta_time_ms)

                canvas = self.renderer.start_frame()

                self.graphics_manager.draw(
                    renderer=self.renderer,
                    rows=self.rows,
                    cols=self.cols,
                )

                # Draw selection highlight after pieces so it's visible.
                if self.selection_provider:
                    selected = self.selection_provider()
                    if selected is not None:
                        sel_row, sel_col = selected
                        self.renderer.draw_cell_highlight(
                            row=sel_row,
                            col=sel_col,
                            rows=self.rows,
                            cols=self.cols,
                        )

                delay_ms = max(1, int(1000 / self.target_fps))

                key = canvas.show(
                    window_name=self.window_name,
                    delay_ms=delay_ms,
                )

                if not Img.is_window_open(self.window_name):
                    self.running = False
                    continue

                if key == Esc:
                    self.running = False

        finally:
            Img.close_windows()
