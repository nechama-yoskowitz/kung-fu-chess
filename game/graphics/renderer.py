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
    ) -> tuple[float, float]:
        if rows <= 0 or cols <= 0:
            raise ValueError("Board dimensions must be positive")

        board_height, board_width = self.board_template.img.shape[:2]

        cell_width = board_width / cols
        cell_height = board_height / rows

        return cell_width, cell_height

    def get_cell_bounds(
    self,
    row: int,
    col: int,
    rows: int,
    cols: int,
    ) -> tuple[int, int, int, int]:
        """
        Compute exact pixel boundaries for a board cell.

        Returns (left, top, right, bottom) where:
        - left/top are inclusive pixel coordinates,
        - right/bottom are exclusive (first pixel of the next cell).

        Adjacent cells share the same boundary with no gaps or overlaps.
        The full board width/height is exactly covered.
        """
        board_height, board_width = self.board_template.img.shape[:2]

        left = round(col * board_width / cols)
        right = round((col + 1) * board_width / cols)
        top = round(row * board_height / rows)
        bottom = round((row + 1) * board_height / rows)

        return left, top, right, bottom

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

    def draw_cooldown_indicator(
    self,
    row: int,
    col: int,
    progress: float,
    rows: int,
    cols: int,
    color: tuple = (0, 255, 255),
    alpha: float = 0.4,
    ) -> None:
        """
        Draw a semi-transparent overlay covering a board cell from top,
        shrinking downward as cooldown expires.

        Parameters
        ----------
        row, col : int
            Cell coordinates of the resting piece.
        progress : float
            Remaining cooldown fraction (1.0 = full cell, 0.0 = gone).
        rows, cols : int
            Board dimensions.
        color : tuple
            BGR color for the overlay (default: yellow).
        alpha : float
            Opacity of the overlay (0.0–1.0).
        """
        if self.canvas is None:
            raise RuntimeError(
                "start_frame() must be called before drawing"
            )

        if progress <= 0.0:
            return

        progress = min(progress, 1.0)

        left, top, right, bottom = self.get_cell_bounds(row, col, rows, cols)
        cell_width = right - left
        cell_height = bottom - top

        overlay_height = round(cell_height * progress)

        if overlay_height <= 0:
            return

        self.canvas.blend_rectangle(
            x=left,
            y=top,
            width=cell_width,
            height=overlay_height,
            color=color,
            alpha=alpha,
        )

    def draw_cell_highlight(
    self,
    row: int,
    col: int,
    rows: int,
    cols: int,
    color: tuple = (0, 255, 255),
    thickness: int = 3,
    ) -> None:
        """
        Draw a rectangular border around a board cell.

        Parameters
        ----------
        row, col : int
            Cell coordinates on the board.
        rows, cols : int
            Board dimensions.
        color : tuple
            BGR color for the border (default: yellow).
        thickness : int
            Border thickness in pixels.
        """
        if self.canvas is None:
            raise RuntimeError(
                "start_frame() must be called before drawing"
            )

        if not (0 <= row < rows and 0 <= col < cols):
            raise ValueError("Cell is outside the board")

        left, top, right, bottom = self.get_cell_bounds(row, col, rows, cols)

        self.canvas.draw_rectangle(
            x=left,
            y=top,
            width=right - left,
            height=bottom - top,
            color=color,
            thickness=thickness,
        )

    def draw_game_over_overlay(self, alpha: float = 0.6) -> None:
        """
        Draw a semi-transparent dark overlay over the entire board.

        Parameters
        ----------
        alpha : float
            Opacity of the dark overlay (0.0–1.0).
        """
        if self.canvas is None:
            raise RuntimeError(
                "start_frame() must be called before drawing"
            )

        h, w = self.canvas.img.shape[:2]

        self.canvas.blend_rectangle(
            x=0,
            y=0,
            width=w,
            height=h,
            color=(0, 0, 0),
            alpha=alpha,
        )

    def draw_centered_text(
    self,
    text: str,
    font_size: float = 2.0,
    color: tuple = (255, 255, 255),
    thickness: int = 3,
    ) -> None:
        """
        Draw text centered on the board.

        Parameters
        ----------
        text : str
            The text to display.
        font_size : float
            Font scale.
        color : tuple
            BGR color.
        thickness : int
            Text thickness.
        """
        if self.canvas is None:
            raise RuntimeError(
                "start_frame() must be called before drawing"
            )

        self.canvas.put_centered_text(
            txt=text,
            font_size=font_size,
            color=color,
            thickness=thickness,
        )
