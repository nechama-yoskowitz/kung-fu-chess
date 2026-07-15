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

    def get_cell_size(
    self,
    rows: int,
    cols: int,
    ) -> tuple[int, int]:
        if rows <= 0 or cols <= 0:
            raise ValueError("Board dimensions must be positive")

        board_height, board_width = self.board_template.img.shape[:2]

        cell_width = board_width // cols
        cell_height = board_height // rows

        return cell_width, cell_height    

    def draw_piece_in_cell(
    self,
    piece_img: Img,
    row: int,
    col: int,
    rows: int,
    cols: int,
    ) -> None:
        if not (0 <= row < rows and 0 <= col < cols):
            raise ValueError("Cell is outside the board")

        self.draw_piece_at_position(
            piece_img=piece_img,
            row=float(row),
            col=float(col),
            rows=rows,
            cols=cols,
        )    

    def draw_piece_at_position(
    self,
    piece_img: Img,
    row: float,
    col: float,
    rows: int,
    cols: int,
    ) -> None:
        if self.canvas is None:
            raise RuntimeError(
                "start_frame() must be called before drawing"
            )

        cell_width, cell_height = self.get_cell_size(rows, cols)

        piece_height, piece_width = piece_img.img.shape[:2]

        cell_x = col * cell_width
        cell_y = row * cell_height

        x = round(cell_x + (cell_width - piece_width) / 2)
        y = round(cell_y + (cell_height - piece_height) / 2)

        self.draw_piece(piece_img, x, y)