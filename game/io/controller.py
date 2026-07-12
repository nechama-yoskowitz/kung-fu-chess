from game.model.board import is_inside_board
from game.model.constants import CELL_SIZE, EMPTY_CELL
from game.model.pieces import same_color


class Controller:
    """
    Translate user input into game requests.

    The controller is responsible for:
    - converting pixels to board cells,
    - remembering the selected cell,
    - interpreting the first and second clicks,
    - forwarding move and jump requests to the GameEngine.

    It does not validate chess rules and does not modify game state directly.
    """

    def __init__(self, engine):
        self.engine = engine
        self.selected = None

    def click(self, x, y):
        """
        Process a click at pixel coordinates.

        The first valid click selects a piece.
        The second click requests a move through the GameEngine.

        Returns True if a move was accepted,
        otherwise returns False.
        """
        row, col = self._pixel_to_cell(x, y)

        if not is_inside_board(
            self.engine.board,
            row,
            col,
        ):
            self.selected = None
            return False

        clicked_piece = self.engine.board[row][col]

        # First click: select a piece.
        if self.selected is None:
            if (
                clicked_piece != EMPTY_CELL
                and not self.engine.is_piece_moving_at(row, col)
            ):
                self.selected = (row, col)

            return False

        selected_row, selected_col = self.selected
        selected_piece = self.engine.board[selected_row][selected_col]

        # Clicking another friendly piece switches the selection.
        if (
            clicked_piece != EMPTY_CELL
            and same_color(selected_piece, clicked_piece)
        ):
            if not self.engine.is_piece_moving_at(row, col):
                self.selected = (row, col)

            return False

        # Every second click completes the current selection attempt.
        self.selected = None

        return self.engine.request_move(
            selected_row,
            selected_col,
            row,
            col,
        )

    def jump(self, x, y):
        """
        Process a jump command at pixel coordinates.

        Returns True if the jump was accepted,
        otherwise returns False.
        """
        row, col = self._pixel_to_cell(x, y)

        return self.engine.request_jump(row, col)

    @staticmethod
    def _pixel_to_cell(x, y):
        """Convert pixel coordinates to board row and column."""
        row = y // CELL_SIZE
        col = x // CELL_SIZE

        return row, col