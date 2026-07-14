from pathlib import Path

from game.graphics.img import Img


class Renderer:
    def __init__(self, board_path):
        self.board_template = Img().read(str(Path(board_path)))
        self.canvas = None

    def start_frame(self):
        self.canvas = Img()
        self.canvas.img = self.board_template.img.copy()

        return self.canvas

    def draw_piece(self, piece_img: Img, x: int, y: int) -> None:
        if self.canvas is None:
            raise RuntimeError("start_frame() must be called before drawing")

        piece_img.draw_on(self.canvas, x, y)    