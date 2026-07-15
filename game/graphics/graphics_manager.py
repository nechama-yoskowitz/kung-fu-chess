
from game.graphics.graphic_piece import GraphicPiece
from game.graphics.renderer import Renderer
from game.graphics.sprite_manager import SpriteManager


class GraphicsManager:
    def __init__(
        self,
        sprite_manager: SpriteManager,
        piece_size: tuple[int, int],
    ):
        self.sprite_manager = sprite_manager
        self.piece_size = piece_size
        self.graphic_pieces: list[GraphicPiece] = []

    def initialize_from_board(self, board) -> None:
        self.graphic_pieces.clear()

        for row, board_row in enumerate(board):
            for col, piece in enumerate(board_row):
                if piece == ".":
                    continue

                graphic_piece = GraphicPiece(
                    piece=piece,
                    row=row,
                    col=col,
                    sprite_manager=self.sprite_manager,
                    piece_size=self.piece_size,
                    initial_state="idle",
                )

                self.graphic_pieces.append(graphic_piece)

    def update(self, delta_time_ms: float) -> None:
        for graphic_piece in self.graphic_pieces:
            graphic_piece.update(delta_time_ms)

    def draw(
        self,
        renderer: Renderer,
        rows: int,
        cols: int,
    ) -> None:
        for graphic_piece in self.graphic_pieces:
            renderer.draw_piece_in_cell(
                piece_img=graphic_piece.get_current_frame(),
                row=graphic_piece.row,
                col=graphic_piece.col,
                rows=rows,
                cols=cols,
            )