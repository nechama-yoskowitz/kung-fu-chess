from dataclasses import dataclass

from game.model.board import is_inside_board
from game.model.constants import EMPTY_CELL, PIECE_PAWN
from game.model.pieces import get_type, same_color
from game.rules.rules import (
    is_legal_move,
    is_legal_pawn_move,
    is_path_clear,
    is_sliding_piece,
)


@dataclass(frozen=True)
class MoveValidation:
    """
    Result returned by RuleEngine after validating a requested move.

    is_valid:
        True when the move is legal.

    reason:
        A stable machine-readable explanation.
    """

    is_valid: bool
    reason: str


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
        Validate a requested move against the current board state.

        This method never modifies the board.
        """
        if not is_inside_board(board, from_row, from_col):
            return MoveValidation(
                is_valid=False,
                reason="outside_board",
            )

        if not is_inside_board(board, to_row, to_col):
            return MoveValidation(
                is_valid=False,
                reason="outside_board",
            )

        piece = board[from_row][from_col]

        if piece == EMPTY_CELL:
            return MoveValidation(
                is_valid=False,
                reason="empty_source",
            )

        target = board[to_row][to_col]

        if target != EMPTY_CELL and same_color(piece, target):
            return MoveValidation(
                is_valid=False,
                reason="friendly_destination",
            )

        if get_type(piece) == PIECE_PAWN:
            if not is_legal_pawn_move(
                board,
                piece,
                from_row,
                from_col,
                to_row,
                to_col,
            ):
                return MoveValidation(
                    is_valid=False,
                    reason="illegal_piece_move",
                )

            return MoveValidation(
                is_valid=True,
                reason="ok",
            )

        if not is_legal_move(
            piece,
            from_row,
            from_col,
            to_row,
            to_col,
        ):
            return MoveValidation(
                is_valid=False,
                reason="illegal_piece_move",
            )

        if (
            is_sliding_piece(piece)
            and not is_path_clear(
                board,
                from_row,
                from_col,
                to_row,
                to_col,
            )
        ):
            return MoveValidation(
                is_valid=False,
                reason="illegal_piece_move",
            )

        return MoveValidation(
            is_valid=True,
            reason="ok",
        )