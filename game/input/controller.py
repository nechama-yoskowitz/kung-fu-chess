from game.board import is_inside_board
from game.constants import (
    CELL_SIZE,
    EMPTY_CELL,
    JUMP_DURATION_MS,
    MOVE_DURATION_MS,
    PIECE_PAWN,
)
from game.movement import (
    ActiveJump,
    PendingMove,
    is_destination_claimed,
    is_piece_moving,
)
from game.pieces import get_type, same_color
from game.rules import (
    is_legal_move,
    is_legal_pawn_move,
    is_path_clear,
    is_sliding_piece,
)


class Controller:
    """
    Translate user input into game actions.

    The controller owns the currently selected board cell.
    It does not modify the board directly.
    """

    def __init__(self, board):
        self.board = board
        self.selected = None

    def click(self, pending_moves, x, y, clock):
        """
        Process a click at pixel coordinates (x, y).

        Returns a new PendingMove when a legal move is requested,
        otherwise returns None.

        The board is not modified here.
        """
        row = y // CELL_SIZE
        col = x // CELL_SIZE

        if not is_inside_board(self.board, row, col):
            return None

        clicked_cell = self.board[row][col]

        # No piece selected yet.
        if self.selected is None:
            if (
                clicked_cell != EMPTY_CELL
                and not is_piece_moving(pending_moves, row, col)
            ):
                self.selected = (row, col)

            return None

        selected_row, selected_col = self.selected
        selected_piece = self.board[selected_row][selected_col]

        # Clicking a friendly piece switches the selection.
        if (
            clicked_cell != EMPTY_CELL
            and same_color(selected_piece, clicked_cell)
        ):
            if not is_piece_moving(pending_moves, row, col):
                self.selected = (row, col)

            return None

        # The second click completes the selection attempt.
        self.selected = None

        if not self._is_legal_destination(
            selected_piece,
            selected_row,
            selected_col,
            row,
            col,
        ):
            return None

        if is_destination_claimed(pending_moves, row, col):
            return None

        return PendingMove(
            piece=selected_piece,
            from_row=selected_row,
            from_col=selected_col,
            to_row=row,
            to_col=col,
            arrive_at=clock + MOVE_DURATION_MS,
        )

    def jump(self, pending_moves, active_jumps, x, y, clock):
        """
        Process a jump command at pixel coordinates (x, y).

        Returns a new ActiveJump when the jump is valid,
        otherwise returns None.
        """
        row = y // CELL_SIZE
        col = x // CELL_SIZE

        if not is_inside_board(self.board, row, col):
            return None

        piece = self.board[row][col]

        if piece == EMPTY_CELL:
            return None

        if is_piece_moving(pending_moves, row, col):
            return None

        if self._is_airborne(active_jumps, row, col):
            return None

        return ActiveJump(
            piece=piece,
            row=row,
            col=col,
            expires_at=clock + JUMP_DURATION_MS,
        )

    def _is_legal_destination(
        self,
        piece,
        from_row,
        from_col,
        to_row,
        to_col,
    ):
        """Return True if the selected piece may move to the destination."""
        if get_type(piece) == PIECE_PAWN:
            return is_legal_pawn_move(
                self.board,
                piece,
                from_row,
                from_col,
                to_row,
                to_col,
            )

        if not is_legal_move(
            piece,
            from_row,
            from_col,
            to_row,
            to_col,
        ):
            return False

        if is_sliding_piece(piece):
            return is_path_clear(
                self.board,
                from_row,
                from_col,
                to_row,
                to_col,
            )

        return True

    @staticmethod
    def _is_airborne(active_jumps, row, col):
        """Return True if the piece at the given cell is already airborne."""
        return any(
            jump.row == row and jump.col == col
            for jump in active_jumps
        )