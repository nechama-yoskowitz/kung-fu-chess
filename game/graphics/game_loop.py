import time

from game.graphics.graphics_manager import GraphicsManager
from game.graphics.img import Img
from game.graphics.renderer import Renderer
 
Esc=27

class GameLoop:
    def __init__(
        self,
        renderer: Renderer,
        graphics_manager: GraphicsManager,
        rows: int,
        cols: int,
        target_fps: int = 60,
        window_name: str = "Kung-Fu Chess",
    ):
        if target_fps <= 0:
            raise ValueError("target_fps must be greater than zero")

        self.renderer = renderer
        self.graphics_manager = graphics_manager
        self.rows = rows
        self.cols = cols
        self.target_fps = target_fps
        self.window_name = window_name
        self.running = False

    def run(self) -> None:
        self.running = True
        previous_time = time.perf_counter()

        try:
            while self.running:
                current_time = time.perf_counter()
                delta_time_ms = (current_time - previous_time) * 1000
                previous_time = current_time

                self.graphics_manager.update(delta_time_ms)

                canvas = self.renderer.start_frame()

                self.graphics_manager.draw(
                    renderer=self.renderer,
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