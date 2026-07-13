from dataclasses import dataclass

from game.model.board import is_inside_board
from game.model.pieces import get_type, same_color, is_empty, is_pawn
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


@dataclass(frozen=True)
class JumpValidation:
    """
    Result returned by RuleEngine after validating a jump request.

    is_valid:
        True when the jump is allowed.

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

        if is_empty(piece):
            return MoveValidation(
                is_valid=False,
                reason="empty_source",
            )

        target = board[to_row][to_col]

        if not is_empty(target) and same_color(piece, target):
            return MoveValidation(
                is_valid=False,
                reason="friendly_destination",
            )

        if is_pawn(piece):
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

    def validate_jump(
        self,
        board,
        row,
        col,
        is_piece_moving,
        is_airborne,
    ):
        """
        Validate a jump request against the current board and realtime state.

        This method is read-only — it never modifies the board or starts a jump.

        Parameters:
            board: the current board state
            row, col: target cell
            is_piece_moving: bool indicating if the piece is currently moving
            is_airborne: bool indicating if the piece is already airborne
        """
        if not is_inside_board(board, row, col):
            return JumpValidation(
                is_valid=False,
                reason="outside_board",
            )

        piece = board[row][col]

        if is_empty(piece):
            return JumpValidation(
                is_valid=False,
                reason="empty_source",
            )

        if is_piece_moving:
            return JumpValidation(
                is_valid=False,
                reason="piece_moving",
            )

        if is_airborne:
            return JumpValidation(
                is_valid=False,
                reason="already_airborne",
            )

        return JumpValidation(
            is_valid=True,
            reason="ok",
        )