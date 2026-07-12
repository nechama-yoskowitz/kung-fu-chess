from game.model.board import is_inside_board
from game.model.constants import EMPTY_CELL, PIECE_PAWN
from game.model.pieces import get_type, same_color
from game.rules.rules import (
    is_legal_move,
    is_legal_pawn_move,
    is_path_clear,
    is_sliding_piece,
)


class RuleEngine:
    """Validate requested moves without modifying the board."""

    def validate_move(
        self,
        board,
        from_row,
        from_col,
        to_row,
        to_col,
    ):
        """
        Return True if the requested move is legal.

        This method only validates.
        It does not move pieces or modify the board.
        """
        if not is_inside_board(board, from_row, from_col):
            return False

        if not is_inside_board(board, to_row, to_col):
            return False

        piece = board[from_row][from_col]

        if piece == EMPTY_CELL:
            return False

        target = board[to_row][to_col]

        if target != EMPTY_CELL and same_color(piece, target):
            return False

        if get_type(piece) == PIECE_PAWN:
            return is_legal_pawn_move(
                board,
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
                board,
                from_row,
                from_col,
                to_row,
                to_col,
            )

        return True