from game.input.board_mapper import BoardMapper
from game.model.board import is_inside_board
from game.model.constants import EMPTY_CELL
from game.model.pieces import same_color


class Controller:
    """
    Translate user input into game requests.

    The controller is responsible for:
    - remembering the selected cell,
    - interpreting the first and second clicks,
    - forwarding move and jump requests to the GameEngine.

    Pixel-to-cell conversion is delegated to BoardMapper.
    The controller does not validate chess rules
    and does not modify the board directly.
    """

    def __init__(self, engine, board_mapper=None):
        self.engine = engine
        self.selected = None
        self.board_mapper = board_mapper or BoardMapper()

    def click(self, x, y):
        """
        Process a click at pixel coordinates.

        The first valid click selects a piece.
        The second click requests a move through the GameEngine.

        Returns True if a move was accepted,
        otherwise returns False.
        """
        row, col = self.board_mapper.pixel_to_cell(x, y)

        if not is_inside_board(
            self.engine.board,
            row,
            col,
        ):
            if self.selected is not None:
                self.selected = None

            return False

        clicked_piece = self.engine.board[row][col]

        # First click: select a non-moving piece.
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

        # Every second click inside the board completes the selection attempt.
        self.selected = None

        result = self.engine.request_move(
            selected_row,
            selected_col,
            row,
            col,
        )

        return result

    def jump(self, x, y):
        """
        Process a jump command at pixel coordinates.

        Returns True if the jump was accepted,
        otherwise returns False.
        """
        row, col = self.board_mapper.pixel_to_cell(x, y)

        if not is_inside_board(
            self.engine.board,
            row,
            col,
        ):
            return False

        return self.engine.request_jump(row, col)