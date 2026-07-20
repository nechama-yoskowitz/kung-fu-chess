
from game.graphics.pieces.graphic_piece import GraphicPiece
from game.graphics.renderer import Renderer
from game.graphics.sprites.sprite_manager import SpriteManager


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
            renderer.draw_piece_at_position(
                piece_img=graphic_piece.get_current_frame(),
                row=graphic_piece.display_row,
                col=graphic_piece.display_col,
                rows=rows,
                cols=cols,
            )
    def get_piece_at(self, row: int, col: int) -> GraphicPiece | None:
        for graphic_piece in self.graphic_pieces:
            if (
                graphic_piece.row == row
                and graphic_piece.col == col
            ):
                return graphic_piece

        return None

    def get_pieces_at(self, row: int, col: int) -> list[GraphicPiece]:
        """Return all GraphicPieces whose logical position is (row, col)."""
        return [
            gp for gp in self.graphic_pieces
            if gp.row == row and gp.col == col
        ]

    def remove_piece(self, graphic_piece: GraphicPiece) -> None:
        """Remove a specific GraphicPiece from the managed list."""
        self.graphic_pieces.remove(graphic_piece)

    def set_piece_state(
    self,
    row: int,
    col: int,
    state: str,
    ) -> None:
        graphic_piece = self.get_piece_at(row, col)

        if graphic_piece is None:
            raise ValueError(
                f"No graphic piece found at ({row}, {col})"
            )

        graphic_piece.set_state(state)

    def move_piece(
    self,
    from_row: int,
    from_col: int,
    to_row: int,
    to_col: int,
    ) -> None:
        graphic_piece = self.get_piece_at(from_row, from_col)

        if graphic_piece is None:
            raise ValueError(
                f"No graphic piece found at ({from_row}, {from_col})"
            )

        graphic_piece.set_position(to_row, to_col)                
    def start_piece_move(
    self,
    from_row: int,
    from_col: int,
    to_row: int,
    to_col: int,
    duration_ms: float,
    ) -> None:
        graphic_piece = self.get_piece_at(from_row, from_col)

        if graphic_piece is None:
            raise ValueError(
                f"No graphic piece found at ({from_row}, {from_col})"
            )

        graphic_piece.start_move(
            to_row=to_row,
            to_col=to_col,
            duration_ms=duration_ms,
        )